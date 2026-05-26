"""Unit tests for CodexAgent (no Docker required)."""
import json

import pytest
from terrarium.agent.codex import (
    CodexAgent,
    SESSION_DIR,
    TERRARIUM_DIR,
    _parse_codex_session,
    _parse_json_arguments,
)
from terrarium.models.trajectory import ThinkingBlock, ToolUseBlock

SKILLS_DIR = f"{TERRARIUM_DIR}/skills"


class _FakeExecResult:
    def __init__(self, exit_code=0, stdout="", stderr=""):
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr


class _FakeFS:
    def __init__(self):
        self._files: dict[str, bytes] = {}
        self.make_dir_calls: list[str] = []
        self.write_file_calls: list[tuple[str, bytes]] = []
        self.upload_calls: list[tuple[str, str]] = []

    def make_dir(self, path: str) -> None:
        self.make_dir_calls.append(path)

    def write_file(self, path: str, content: bytes) -> None:
        self.write_file_calls.append((path, content))
        self._files[path] = content

    def upload(self, local_path: str, sandbox_path: str) -> None:
        self.upload_calls.append((local_path, sandbox_path))

    def read_file(self, path: str) -> bytes:
        if path not in self._files:
            raise FileNotFoundError(path)
        return self._files[path]

    def set_file(self, path: str, content: bytes) -> None:
        self._files[path] = content


class _FakeShell:
    def __init__(self, responses=None):
        self._responses = responses or []
        self._call_index = 0
        self.commands: list[tuple[str, str | None]] = []

    def exec(self, command, timeout=None, env=None, user=None):
        self.commands.append((command, user))
        if self._call_index < len(self._responses):
            result = self._responses[self._call_index]
            self._call_index += 1
            return result
        return _FakeExecResult()


class _FakeWorkspace:
    def __init__(self, shell_responses=None):
        self.fs = _FakeFS()
        self.shell = _FakeShell(shell_responses)


def _make_session(session_id="thread-1", *entries):
    """Build a JSONL session string: session_meta line + given entries."""
    lines = [json.dumps({"type": "session_meta", "payload": {"id": session_id}})]
    for entry in entries:
        lines.append(json.dumps(entry))
    return "\n".join(lines)


def _make_agent(shell_responses=None):
    # setup() runs: mkdir TERRARIUM_DIR (root), command -v codex, (install?), codex --version
    mkdir_result = _FakeExecResult(exit_code=0)
    install_check = _FakeExecResult(exit_code=0, stdout="/usr/local/bin/codex")
    extra = shell_responses or [_FakeExecResult(stdout="codex-cli 0.118.0")]
    workspace = _FakeWorkspace(shell_responses=[mkdir_result, install_check, *extra])
    agent = CodexAgent(model="gpt-5.4", api_key="sk-test")
    return agent, workspace


class TestCodexAgentBasics:
    def test_name(self):
        assert CodexAgent.name() == "codex"

    def test_workspace_config(self):
        assert CodexAgent.workspace_config() == {"image": {"name": "terrarium/codex:latest"}}

    def test_version_before_setup(self):
        assert CodexAgent().version() is None


class TestBuildCommand:
    def _make_agent(self):
        return CodexAgent(model="gpt-5.4", api_key="sk-test")

    def test_first_turn_uses_exec(self):
        agent = self._make_agent()
        cmd = agent._build_command("do something")
        assert "codex exec " in cmd
        assert "resume" not in cmd

    def test_subsequent_turn_uses_resume(self):
        agent = self._make_agent()
        agent._session_id = "sess-abc-123"
        cmd = agent._build_command("do more")
        assert "exec resume" in cmd
        assert "sess-abc-123" in cmd

    def test_includes_bypass_flag(self):
        agent = self._make_agent()
        cmd = agent._build_command("test")
        assert "--dangerously-bypass-approvals-and-sandbox" in cmd

    def test_includes_model(self):
        agent = self._make_agent()
        cmd = agent._build_command("test")
        assert "gpt-5.4" in cmd

    def test_includes_api_key(self):
        agent = self._make_agent()
        cmd = agent._build_command("test")
        assert "OPENAI_API_KEY=" in cmd
        assert "sk-test" in cmd


class TestEnsureInstalled:
    def test_skips_install_when_present(self):
        """If `codex` is on PATH, no install command is run."""
        agent = CodexAgent()
        agent._workspace = _FakeWorkspace(shell_responses=[
            _FakeExecResult(exit_code=0, stdout="/usr/local/bin/codex"),
        ])
        agent._ensure_installed()
        assert agent._workspace.shell.commands == [("command -v codex", None)]

    def test_runs_install_as_root_when_missing(self):
        """If `codex` is absent, the install script is executed as root."""
        agent = CodexAgent()
        agent._workspace = _FakeWorkspace(shell_responses=[
            _FakeExecResult(exit_code=1),
            _FakeExecResult(exit_code=0),
        ])
        agent._ensure_installed()
        cmds = agent._workspace.shell.commands
        assert len(cmds) == 2
        assert cmds[0] == ("command -v codex", None)
        install_cmd, install_user = cmds[1]
        assert "npm install -g @openai/codex" in install_cmd
        assert install_user == "root"

    def test_raises_when_install_fails(self):
        """RuntimeError is raised if the install script exits non-zero."""
        agent = CodexAgent()
        agent._workspace = _FakeWorkspace(shell_responses=[
            _FakeExecResult(exit_code=1),
            _FakeExecResult(exit_code=1, stderr="npm ENOENT"),
        ])
        with pytest.raises(RuntimeError, match="Failed to install Codex CLI"):
            agent._ensure_installed()


class TestSessionFileDiscovery:
    def test_no_files_raises(self):
        """Raises if no session file is found on first read."""
        workspace = _FakeWorkspace(shell_responses=[_FakeExecResult(stdout="")])
        agent = CodexAgent()
        agent._workspace = workspace
        with pytest.raises(RuntimeError, match="found 0"):
            agent._read_new_session_entries()

    def test_multiple_files_raises(self):
        """Raises if multiple session files are found."""
        workspace = _FakeWorkspace(shell_responses=[
            _FakeExecResult(stdout="/a/rollout-1.jsonl\n/a/rollout-2.jsonl\n"),
        ])
        agent = CodexAgent()
        agent._workspace = workspace
        with pytest.raises(RuntimeError, match="found 2"):
            agent._read_new_session_entries()


class TestInstallSkill:
    def test_uploads_directory(self, tmp_path):
        """Uploads the skill dir to <skills_dir>/<name>."""
        skill_dir = tmp_path / "my_skill"
        skill_dir.mkdir()

        agent = CodexAgent()
        agent._workspace = _FakeWorkspace()
        agent.install_skill(skill_dir)

        fs = agent._workspace.fs
        assert fs.make_dir_calls == [SKILLS_DIR]
        assert fs.upload_calls == [(str(skill_dir.resolve()), f"{SKILLS_DIR}/my_skill")]

    def test_accepts_string_path(self, tmp_path):
        """Accepts str path, not just Path."""
        skill_dir = tmp_path / "parser"
        skill_dir.mkdir()

        agent = CodexAgent()
        agent._workspace = _FakeWorkspace()
        agent.install_skill(str(skill_dir))

        assert agent._workspace.fs.upload_calls[0][1] == f"{SKILLS_DIR}/parser"

    def test_rejects_missing_path(self, tmp_path):
        """Raises if path does not exist."""
        agent = CodexAgent()
        agent._workspace = _FakeWorkspace()
        with pytest.raises(FileNotFoundError, match="not a directory"):
            agent.install_skill(tmp_path / "nonexistent")

    def test_rejects_file(self, tmp_path):
        """Raises if path is a file, not a directory."""
        (tmp_path / "SKILL.md").write_text("not a dir")

        agent = CodexAgent()
        agent._workspace = _FakeWorkspace()
        with pytest.raises(FileNotFoundError, match="not a directory"):
            agent.install_skill(tmp_path / "SKILL.md")


class TestSkillsDir:
    def test_returns_in_container_skills_path(self):
        """skills_dir property exposes the in-container skills path."""
        assert CodexAgent().skills_dir == SKILLS_DIR


class TestSetup:
    def test_creates_terrarium_dir_as_root(self):
        """setup() provisions TERRARIUM_DIR as root with permissive mode."""
        agent, workspace = _make_agent()
        agent.setup(workspace, {})
        first_cmd, first_user = workspace.shell.commands[0]
        assert TERRARIUM_DIR in first_cmd
        assert "1777" in first_cmd
        assert first_user == "root"

    def test_writes_config_toml(self, monkeypatch):
        """setup() writes a config.toml pointing codex at a custom provider."""
        monkeypatch.setenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
        agent, workspace = _make_agent()
        agent.setup(workspace, {})

        writes = [(p, c) for p, c in workspace.fs.write_file_calls if p.endswith("config.toml")]
        assert len(writes) == 1
        path, content = writes[0]
        text = content.decode()
        assert path == f"{TERRARIUM_DIR}/config.toml"
        assert 'model_provider = "terrarium"' in text
        assert '[model_providers.terrarium]' in text
        assert 'base_url = "https://openrouter.ai/api/v1"' in text
        assert 'env_key = "OPENAI_API_KEY"' in text

    def test_config_toml_defaults_to_openai(self, monkeypatch):
        """Without OPENAI_BASE_URL the config points at OpenAI's endpoint."""
        monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
        agent, workspace = _make_agent()
        agent.setup(workspace, {})

        writes = [(p, c) for p, c in workspace.fs.write_file_calls if p.endswith("config.toml")]
        assert len(writes) == 1
        _, content = writes[0]
        assert 'base_url = "https://api.openai.com/v1"' in content.decode()


class TestAct:
    def test_reads_session(self):
        """End-to-end: exec → find session file → parse → ActResult."""
        session_path = f"{SESSION_DIR}/2026/04/17/rollout-abc-thread-1.jsonl"
        session = _make_session(
            "thread-1",
            {"type": "response_item", "payload": {"type": "message", "role": "user",
             "content": [{"type": "input_text", "text": "list"}]}},
            {"type": "response_item", "payload": {"type": "function_call", "name": "exec_command",
             "arguments": "{\"cmd\":\"ls\"}", "call_id": "c1"}},
            {"type": "response_item", "payload": {"type": "function_call_output",
             "call_id": "c1", "output": "a.txt\n"}},
            {"type": "response_item", "payload": {"type": "message", "role": "assistant",
             "content": [{"type": "output_text", "text": "Found a.txt"}]}},
            {"type": "event_msg", "payload": {"type": "token_count",
             "info": {"last_token_usage": {"input_tokens": 500, "output_tokens": 100,
                      "cached_input_tokens": 200, "reasoning_output_tokens": 0}}}},
        )

        agent, workspace = _make_agent([
            _FakeExecResult(stdout="codex-cli 0.118.0"),  # setup version
            _FakeExecResult(),                             # codex exec
            _FakeExecResult(stdout=f"{session_path}\n"),   # find session file
        ])
        agent.setup(workspace, {})
        workspace.fs.set_file(session_path, session.encode())

        result = agent.act("list")
        assert len(result.messages) == 4
        assert agent._session_id == "thread-1"
        assert result.input_tokens == 500
        assert result.output_tokens == 100
        assert result.cache_read_tokens == 200

    def test_tool_calls_in_trajectory(self):
        """get_trajectory() counts tool calls across acts."""
        session_path = f"{SESSION_DIR}/2026/04/17/rollout-abc-thread-1.jsonl"
        session = _make_session(
            "thread-1",
            {"type": "response_item", "payload": {"type": "function_call", "name": "exec_command",
             "arguments": "{}", "call_id": "c1"}},
            {"type": "response_item", "payload": {"type": "function_call_output",
             "call_id": "c1", "output": "ok"}},
            {"type": "response_item", "payload": {"type": "function_call", "name": "exec_command",
             "arguments": "{}", "call_id": "c2"}},
            {"type": "response_item", "payload": {"type": "function_call_output",
             "call_id": "c2", "output": "done"}},
        )

        agent, workspace = _make_agent([
            _FakeExecResult(stdout="codex-cli 0.118.0"),
            _FakeExecResult(),
            _FakeExecResult(stdout=f"{session_path}\n"),
        ])
        agent.setup(workspace, {})
        workspace.fs.set_file(session_path, session.encode())
        agent.act("run")

        traj = agent.get_trajectory()
        assert traj.metrics.total_tool_calls == 2
        assert traj.metrics.total_llm_calls == 1

    def test_multi_turn_incremental(self):
        """Second act() uses resume and reads only new session entries."""
        session_path = f"{SESSION_DIR}/2026/04/17/rollout-abc-thread-1.jsonl"
        turn1 = _make_session(
            "thread-1",
            {"type": "response_item", "payload": {"type": "message", "role": "assistant",
             "content": [{"type": "output_text", "text": "First response"}]}},
            {"type": "event_msg", "payload": {"type": "token_count",
             "info": {"last_token_usage": {"input_tokens": 100, "output_tokens": 50,
                      "cached_input_tokens": 0, "reasoning_output_tokens": 0}}}},
        )
        turn2 = turn1 + "\n" + "\n".join([
            json.dumps({"type": "response_item", "payload": {"type": "message", "role": "assistant",
                        "content": [{"type": "output_text", "text": "Second response"}]}}),
            json.dumps({"type": "event_msg", "payload": {"type": "token_count",
                        "info": {"last_token_usage": {"input_tokens": 200, "output_tokens": 75,
                                 "cached_input_tokens": 50, "reasoning_output_tokens": 0}}}}),
        ])

        agent, workspace = _make_agent([
            _FakeExecResult(stdout="codex-cli 0.118.0"),
            _FakeExecResult(),                             # first codex exec
            _FakeExecResult(stdout=f"{session_path}\n"),   # find session file
            _FakeExecResult(),                             # second codex exec (resume)
        ])
        agent.setup(workspace, {})

        workspace.fs.set_file(session_path, turn1.encode())
        r1 = agent.act("Turn 1")
        assert len(r1.messages) == 1
        assert r1.messages[0].content[0].text == "First response"
        assert r1.input_tokens == 100

        workspace.fs.set_file(session_path, turn2.encode())
        r2 = agent.act("Turn 2")
        # Only new entries; turn2 - turn1
        assert len(r2.messages) == 1
        assert r2.messages[0].content[0].text == "Second response"
        assert r2.input_tokens == 200

        # Second exec command should use resume with the captured session id.
        second_exec, _ = workspace.shell.commands[-1]
        assert "exec resume" in second_exec
        assert "thread-1" in second_exec

        traj = agent.get_trajectory()
        assert len(traj.messages) == 2
        assert traj.metrics.total_input_tokens == 300


class TestParseCodexSession:
    def test_empty_input(self):
        messages, usage, session_id = _parse_codex_session([])
        assert messages == []
        assert usage["input_tokens"] == 0
        assert session_id is None

    def test_session_meta(self):
        line = '{"type":"session_meta","payload":{"id":"abc-123","cwd":"/tmp"}}'
        _, _, session_id = _parse_codex_session([line])
        assert session_id == "abc-123"

    def test_assistant_message(self):
        line = '{"type":"response_item","payload":{"type":"message","role":"assistant","content":[{"type":"output_text","text":"Hello!"}]}}'
        messages, _, _ = _parse_codex_session([line])
        assert len(messages) == 1
        assert messages[0].role == "assistant"
        assert messages[0].content[0].text == "Hello!"

    def test_user_message(self):
        line = '{"type":"response_item","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":"hi"}]}}'
        messages, _, _ = _parse_codex_session([line])
        assert len(messages) == 1
        assert messages[0].role == "user"
        assert messages[0].content[0].text == "hi"

    def test_developer_message(self):
        line = '{"type":"response_item","payload":{"type":"message","role":"developer","content":[{"type":"input_text","text":"system prompt"}]}}'
        messages, _, _ = _parse_codex_session([line])
        assert len(messages) == 1
        assert messages[0].role == "developer"
        assert messages[0].content[0].text == "system prompt"

    def test_function_call(self):
        line = '{"type":"response_item","payload":{"type":"function_call","name":"exec_command","arguments":"{\\"cmd\\":\\"ls\\"}","call_id":"call_abc"}}'
        messages, _, _ = _parse_codex_session([line])
        assert len(messages) == 1
        assert messages[0].role == "assistant"
        block = messages[0].content[0]
        assert block.name == "exec_command"
        assert block.id == "call_abc"
        assert block.input == {"cmd": "ls"}

    def test_function_call_output(self):
        line = '{"type":"response_item","payload":{"type":"function_call_output","call_id":"call_abc","output":"file.txt\\n"}}'
        messages, _, _ = _parse_codex_session([line])
        assert len(messages) == 1
        assert messages[0].role == "user"
        block = messages[0].content[0]
        assert block.tool_use_id == "call_abc"
        assert block.content == "file.txt\n"

    def test_custom_tool_call(self):
        line = '{"type":"response_item","payload":{"type":"custom_tool_call","name":"my_tool","input":"{\\"x\\":1}","call_id":"c1"}}'
        messages, _, _ = _parse_codex_session([line])
        assert len(messages) == 1
        block = messages[0].content[0]
        assert block.name == "my_tool"
        assert block.input == {"x": 1}

    def test_custom_tool_call_output(self):
        line = '{"type":"response_item","payload":{"type":"custom_tool_call_output","call_id":"c1","output":"done"}}'
        messages, _, _ = _parse_codex_session([line])
        assert len(messages) == 1
        assert messages[0].role == "user"
        assert messages[0].content[0].content == "done"

    def test_web_search_call(self):
        line = '{"type":"response_item","payload":{"type":"web_search_call","id":"ws1","action":{"type":"search","query":"python asyncio"}}}'
        messages, _, _ = _parse_codex_session([line])
        assert len(messages) == 1
        block = messages[0].content[0]
        assert block.name == "web_search_call"
        assert block.input == {"action_type": "search", "query": "python asyncio"}

    def test_token_count(self):
        line = '{"type":"event_msg","payload":{"type":"token_count","info":{"last_token_usage":{"input_tokens":100,"output_tokens":50,"cached_input_tokens":20,"reasoning_output_tokens":10}}}}'
        _, usage, _ = _parse_codex_session([line])
        assert usage["input_tokens"] == 100
        # output + reasoning combined
        assert usage["output_tokens"] == 60
        assert usage["cached_input_tokens"] == 20

    def test_token_count_null_info(self):
        """First token_count event in a session has info=null (just rate limits)."""
        line = '{"type":"event_msg","payload":{"type":"token_count","info":null,"rate_limits":{}}}'
        _, usage, _ = _parse_codex_session([line])
        assert usage["input_tokens"] == 0

    def test_token_count_accumulates(self):
        """Multiple token_count events accumulate."""
        lines = [
            '{"type":"event_msg","payload":{"type":"token_count","info":{"last_token_usage":{"input_tokens":100,"output_tokens":50,"cached_input_tokens":0,"reasoning_output_tokens":0}}}}',
            '{"type":"event_msg","payload":{"type":"token_count","info":{"last_token_usage":{"input_tokens":200,"output_tokens":100,"cached_input_tokens":50,"reasoning_output_tokens":0}}}}',
        ]
        _, usage, _ = _parse_codex_session(lines)
        assert usage["input_tokens"] == 300
        assert usage["output_tokens"] == 150

    def test_reasoning_empty_summary(self):
        """Reasoning with empty summary produces no ThinkingBlock."""
        lines = [
            '{"type":"response_item","payload":{"type":"reasoning","summary":[],"content":null,"encrypted_content":"..."}}',
            '{"type":"response_item","payload":{"type":"message","role":"assistant","content":[{"type":"output_text","text":"hi"}]}}',
        ]
        messages, _, _ = _parse_codex_session(lines)
        assert len(messages) == 1
        assert len(messages[0].content) == 1
        assert messages[0].content[0].text == "hi"

    def test_reasoning_prepends_to_next_assistant_message(self):
        """Reasoning summary is prepended to the next assistant message's blocks."""
        lines = [
            '{"type":"response_item","payload":{"type":"reasoning","summary":[{"type":"summary_text","text":"Thinking..."}]}}',
            '{"type":"response_item","payload":{"type":"message","role":"assistant","content":[{"type":"output_text","text":"Done"}]}}',
        ]
        messages, _, _ = _parse_codex_session(lines)
        assert len(messages) == 1
        assert len(messages[0].content) == 2
        assert isinstance(messages[0].content[0], ThinkingBlock)
        assert messages[0].content[0].thinking == "Thinking..."
        assert messages[0].content[1].text == "Done"

    def test_reasoning_multiple_summary_items(self):
        """Multiple summary_text items become separate ThinkingBlocks."""
        lines = [
            '{"type":"response_item","payload":{"type":"reasoning","summary":['
            '{"type":"summary_text","text":"First thought"},'
            '{"type":"summary_text","text":"Second thought"}'
            ']}}',
            '{"type":"response_item","payload":{"type":"message","role":"assistant","content":[{"type":"output_text","text":"ok"}]}}',
        ]
        messages, _, _ = _parse_codex_session(lines)
        assert len(messages) == 1
        assert len(messages[0].content) == 3
        assert messages[0].content[0].thinking == "First thought"
        assert messages[0].content[1].thinking == "Second thought"
        assert messages[0].content[2].text == "ok"

    def test_reasoning_prepends_to_next_tool_call(self):
        """Reasoning summary is prepended to the next tool call."""
        lines = [
            '{"type":"response_item","payload":{"type":"reasoning","summary":[{"type":"summary_text","text":"Let me list"}]}}',
            '{"type":"response_item","payload":{"type":"function_call","name":"exec_command","arguments":"{}","call_id":"c1"}}',
        ]
        messages, _, _ = _parse_codex_session(lines)
        assert len(messages) == 1
        assert len(messages[0].content) == 2
        assert isinstance(messages[0].content[0], ThinkingBlock)
        assert isinstance(messages[0].content[1], ToolUseBlock)

    def test_user_message_drops_pending_reasoning(self):
        """User message drops pending reasoning (doesn't attach, doesn't survive)."""
        lines = [
            '{"type":"response_item","payload":{"type":"reasoning","summary":[{"type":"summary_text","text":"thinking"}]}}',
            '{"type":"response_item","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":"hi"}]}}',
            '{"type":"response_item","payload":{"type":"message","role":"assistant","content":[{"type":"output_text","text":"bye"}]}}',
        ]
        messages, _, _ = _parse_codex_session(lines)
        assert len(messages) == 2
        assert messages[0].role == "user"
        assert len(messages[0].content) == 1
        assert messages[1].role == "assistant"
        assert len(messages[1].content) == 1
        assert not isinstance(messages[1].content[0], ThinkingBlock)

    def test_reasoning_overwrites_previous(self):
        """A new reasoning event overwrites any previous pending reasoning."""
        lines = [
            '{"type":"response_item","payload":{"type":"reasoning","summary":[{"type":"summary_text","text":"first"}]}}',
            '{"type":"response_item","payload":{"type":"reasoning","summary":[{"type":"summary_text","text":"second"}]}}',
            '{"type":"response_item","payload":{"type":"message","role":"assistant","content":[{"type":"output_text","text":"ok"}]}}',
        ]
        messages, _, _ = _parse_codex_session(lines)
        assert len(messages) == 1
        assert messages[0].content[0].thinking == "second"

    def test_invalid_json_skipped(self):
        messages, _, _ = _parse_codex_session(["not json"])
        assert messages == []

    def test_full_turn(self):
        """Parse a realistic single-turn conversation."""
        lines = [
            '{"type":"session_meta","payload":{"id":"thread-1"}}',
            '{"type":"response_item","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":"list files"}]}}',
            '{"type":"response_item","payload":{"type":"reasoning","encrypted_content":"..."}}',
            '{"type":"response_item","payload":{"type":"function_call","name":"exec_command","arguments":"{\\"cmd\\":\\"ls\\"}","call_id":"c1"}}',
            '{"type":"response_item","payload":{"type":"function_call_output","call_id":"c1","output":"a.txt\\n"}}',
            '{"type":"response_item","payload":{"type":"message","role":"assistant","content":[{"type":"output_text","text":"Found a.txt"}]}}',
            '{"type":"event_msg","payload":{"type":"token_count","info":{"last_token_usage":{"input_tokens":500,"output_tokens":100,"cached_input_tokens":200,"reasoning_output_tokens":0}}}}',
        ]
        messages, usage, session_id = _parse_codex_session(lines)
        assert session_id == "thread-1"
        assert len(messages) == 4
        assert messages[0].role == "user"
        assert messages[0].content[0].text == "list files"
        assert messages[1].content[0].name == "exec_command"
        assert messages[2].role == "user"
        assert messages[2].content[0].content == "a.txt\n"
        assert messages[3].content[0].text == "Found a.txt"
        assert usage["input_tokens"] == 500


class TestParseJsonArguments:
    def test_json_string(self):
        assert _parse_json_arguments('{"a": 1}') == {"a": 1}

    def test_invalid_json_string(self):
        assert _parse_json_arguments("not json") == {"input": "not json"}

    def test_none(self):
        assert _parse_json_arguments(None) == {}

    def test_non_string_non_none(self):
        sentinel = object()
        assert _parse_json_arguments(sentinel) == {"value": sentinel}
