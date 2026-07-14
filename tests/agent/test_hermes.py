"""Unit tests for HermesAgent (no Docker required)."""
import json

import pytest
import yaml

from terrarium.agent.hermes import (
    CONFIG_PATH,
    HermesAgent,
    TERRARIUM_DIR,
    _parse_hermes_messages,
)
from terrarium.models.mcp import MCPServerConfig
from terrarium.models.trajectory import (
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
)

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


@pytest.fixture
def model_config(tmp_path):
    """Minimal hermes model config YAML for HermesAgent(model_config_path=...)."""
    p = tmp_path / "hermes_model.yaml"
    p.write_text("provider: custom\napi_key: sk-test\nbase_url: https://example/\n")
    return str(p)


def _make_session(session_id="sid-1", *messages, **session_tokens):
    """Build a single-line hermes sessions-export JSON object."""
    entry = {
        "id": session_id,
        "messages": list(messages),
        "input_tokens": session_tokens.get("input_tokens", 0),
        "output_tokens": session_tokens.get("output_tokens", 0),
        "cache_read_tokens": session_tokens.get("cache_read_tokens", 0),
        "cache_write_tokens": session_tokens.get("cache_write_tokens", 0),
    }
    return json.dumps(entry) + "\n"


def _make_agent(model_config, shell_responses=None):
    """Build a HermesAgent and run setup() against a fake workspace."""
    mkdir_result = _FakeExecResult(exit_code=0)
    install_check = _FakeExecResult(exit_code=0, stdout="/usr/local/bin/hermes")
    version_check = _FakeExecResult(stdout="Hermes Agent v0.14.0 (2026.5.16)")
    extra = shell_responses or []
    workspace = _FakeWorkspace(shell_responses=[mkdir_result, install_check, version_check, *extra])
    agent = HermesAgent(model="claude-sonnet-4-6", model_config_path=model_config)
    return agent, workspace


class TestHermesAgentBasics:
    def test_name(self):
        assert HermesAgent.name() == "hermes"

    def test_workspace_config(self):
        assert HermesAgent.workspace_config() == {"image": {"name": "terrarium/hermes:latest"}}

    def test_version_before_setup(self, model_config):
        assert HermesAgent(model_config_path=model_config).version() is None


class TestBuildCommand:
    def test_first_turn_no_resume(self, model_config):
        agent = HermesAgent(model_config_path=model_config)
        cmd = agent._build_command("do something")
        assert "hermes --yolo chat" in cmd
        assert "--query" in cmd
        assert "--quiet" in cmd
        assert "--resume" not in cmd

    def test_subsequent_turn_uses_resume(self, model_config):
        agent = HermesAgent(model_config_path=model_config)
        agent._session_id = "20260101_120000_abc123"
        cmd = agent._build_command("more")
        assert "--resume" in cmd
        assert "20260101_120000_abc123" in cmd

    def test_inlines_hermes_home(self, model_config):
        agent = HermesAgent(model_config_path=model_config)
        cmd = agent._build_command("hi")
        assert f"HERMES_HOME={TERRARIUM_DIR}" in cmd


class TestExportSessionCommand:
    def test_no_session_id_exports_all(self, model_config):
        agent = HermesAgent(model_config_path=model_config)
        cmd = agent._export_session_command()
        assert "hermes sessions export -" in cmd
        assert "--session-id" not in cmd

    def test_with_session_id(self, model_config):
        agent = HermesAgent(model_config_path=model_config)
        agent._session_id = "sid-abc"
        cmd = agent._export_session_command()
        assert "--session-id" in cmd
        assert "sid-abc" in cmd


class TestEnsureInstalled:
    def test_skips_install_when_present(self, model_config):
        agent = HermesAgent(model_config_path=model_config)
        agent._workspace = _FakeWorkspace(shell_responses=[
            _FakeExecResult(exit_code=0, stdout="/usr/local/bin/hermes"),
        ])
        agent._ensure_installed()
        assert agent._workspace.shell.commands == [("command -v hermes", None)]

    def test_runs_install_as_root_when_missing(self, model_config):
        agent = HermesAgent(model_config_path=model_config)
        agent._workspace = _FakeWorkspace(shell_responses=[
            _FakeExecResult(exit_code=1),
            _FakeExecResult(exit_code=0),
        ])
        agent._ensure_installed()
        cmds = agent._workspace.shell.commands
        assert len(cmds) == 2
        install_cmd, install_user = cmds[1]
        assert "hermes-agent" in install_cmd
        assert install_user == "root"

    def test_raises_when_install_fails(self, model_config):
        agent = HermesAgent(model_config_path=model_config)
        agent._workspace = _FakeWorkspace(shell_responses=[
            _FakeExecResult(exit_code=1),
            _FakeExecResult(exit_code=1, stderr="curl: 404"),
        ])
        with pytest.raises(RuntimeError, match="Failed to install Hermes CLI"):
            agent._ensure_installed()


class TestInstallSkill:
    def test_uploads_directory(self, tmp_path, model_config):
        skill_dir = tmp_path / "my_skill"
        skill_dir.mkdir()

        agent = HermesAgent(model_config_path=model_config)
        agent._workspace = _FakeWorkspace()
        agent.install_skill(skill_dir)

        fs = agent._workspace.fs
        assert fs.make_dir_calls == [SKILLS_DIR]
        assert fs.upload_calls == [(str(skill_dir.resolve()), f"{SKILLS_DIR}/my_skill")]

    def test_accepts_string_path(self, tmp_path, model_config):
        skill_dir = tmp_path / "parser"
        skill_dir.mkdir()

        agent = HermesAgent(model_config_path=model_config)
        agent._workspace = _FakeWorkspace()
        agent.install_skill(str(skill_dir))

        assert agent._workspace.fs.upload_calls[0][1] == f"{SKILLS_DIR}/parser"

    def test_rejects_missing_path(self, tmp_path, model_config):
        agent = HermesAgent(model_config_path=model_config)
        agent._workspace = _FakeWorkspace()
        with pytest.raises(FileNotFoundError, match="not a directory"):
            agent.install_skill(tmp_path / "nonexistent")

    def test_rejects_file(self, tmp_path, model_config):
        (tmp_path / "SKILL.md").write_text("not a dir")

        agent = HermesAgent(model_config_path=model_config)
        agent._workspace = _FakeWorkspace()
        with pytest.raises(FileNotFoundError, match="not a directory"):
            agent.install_skill(tmp_path / "SKILL.md")


class TestSkillsDir:
    def test_returns_in_container_skills_path(self, model_config):
        assert HermesAgent(model_config_path=model_config).skills_dir == SKILLS_DIR


class TestSetup:
    def test_creates_terrarium_dir_as_root(self, model_config):
        agent, workspace = _make_agent(model_config)
        agent.setup(workspace, {})
        first_cmd, first_user = workspace.shell.commands[0]
        assert TERRARIUM_DIR in first_cmd
        assert "1777" in first_cmd
        assert first_user == "root"

    def test_writes_config_yaml(self, model_config):
        """setup() writes config.yaml merging user model config + adapter default."""
        agent, workspace = _make_agent(model_config)
        agent.setup(workspace, {})

        writes = [(p, c) for p, c in workspace.fs.write_file_calls if p == CONFIG_PATH]
        assert len(writes) == 1
        config = yaml.safe_load(writes[0][1].decode())
        # user-supplied fields merged in
        assert config["model"]["provider"] == "custom"
        assert config["model"]["api_key"] == "sk-test"
        assert config["model"]["base_url"] == "https://example/"
        # adapter overwrites `default` with the model_name kwarg
        assert config["model"]["default"] == "claude-sonnet-4-6"

    def test_mcp_servers_three_transports(self, model_config):
        """add_mcp_server emits stdio / sse / streamable-http with the right schema."""
        agent, workspace = _make_agent(model_config)
        agent.setup(workspace, {})

        agent.add_mcp_server(MCPServerConfig(
            name="fs", transport="stdio", command="mcp-fs", args=["--root", "/"],
        ))
        agent.add_mcp_server(MCPServerConfig(
            name="events", transport="sse", url="https://example.invalid/sse",
        ))
        agent.add_mcp_server(MCPServerConfig(
            name="api", transport="streamable-http", url="https://example.invalid/mcp",
            headers={"X-Auth": "tok"},
        ))

        last = [c for p, c in workspace.fs.write_file_calls if p == CONFIG_PATH][-1]
        config = yaml.safe_load(last.decode())
        servers = config["mcp_servers"]
        # stdio: command/args/env, no transport field
        assert servers["fs"]["command"] == "mcp-fs"
        assert "transport" not in servers["fs"]
        # sse: url/headers/transport=sse
        assert servers["events"]["transport"] == "sse"
        assert servers["events"]["url"] == "https://example.invalid/sse"
        # streamable-http: url/headers, no transport field
        assert servers["api"]["url"] == "https://example.invalid/mcp"
        assert servers["api"]["headers"] == {"X-Auth": "tok"}
        assert "transport" not in servers["api"]


class TestAct:
    def test_first_turn_captures_session_id_and_tokens(self, model_config):
        """First act() reads session id and cumulative tokens from sessions export."""
        export = _make_session(
            "sid-1",
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
            input_tokens=100, output_tokens=20, cache_read_tokens=5, cache_write_tokens=2,
        )
        agent, workspace = _make_agent(model_config, [
            _FakeExecResult(),                 # hermes chat
            _FakeExecResult(stdout=export),    # sessions export
        ])
        agent.setup(workspace, {})

        result = agent.act("hi")
        assert agent._session_id == "sid-1"
        assert result.input_tokens == 100
        assert result.output_tokens == 20
        assert result.cache_read_tokens == 5
        assert result.cache_creation_tokens == 2
        assert len(result.messages) == 2

    def test_multi_turn_token_delta(self, model_config):
        """Per-turn tokens are deltas against the previous cumulative export."""
        turn1 = _make_session(
            "sid-1",
            {"role": "user", "content": "Q1"},
            {"role": "assistant", "content": "A1"},
            input_tokens=100, output_tokens=50,
        )
        turn2 = _make_session(
            "sid-1",
            {"role": "user", "content": "Q1"},
            {"role": "assistant", "content": "A1"},
            {"role": "user", "content": "Q2"},
            {"role": "assistant", "content": "A2"},
            input_tokens=300, output_tokens=125,
        )
        agent, workspace = _make_agent(model_config, [
            _FakeExecResult(),                 # chat 1
            _FakeExecResult(stdout=turn1),     # export 1
            _FakeExecResult(),                 # chat 2 (--resume)
            _FakeExecResult(stdout=turn2),     # export 2
        ])
        agent.setup(workspace, {})

        r1 = agent.act("Q1")
        r2 = agent.act("Q2")
        assert r1.input_tokens == 100 and r1.output_tokens == 50
        assert r2.input_tokens == 200 and r2.output_tokens == 75
        # subsequent chat command uses --resume
        chat_cmds = [c for c, _ in workspace.shell.commands if "hermes --yolo chat" in c]
        assert "--resume" in chat_cmds[1]

    def test_tool_calls_in_trajectory(self, model_config):
        """ToolUseBlocks are counted across acts via get_trajectory()."""
        export = _make_session(
            "sid-1",
            {"role": "user", "content": "run"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": "c1", "type": "function",
                    "function": {"name": "exec", "arguments": json.dumps({"cmd": "ls"})},
                }],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "ok"},
            {"role": "assistant", "content": "done"},
        )
        agent, workspace = _make_agent(model_config, [
            _FakeExecResult(),
            _FakeExecResult(stdout=export),
        ])
        agent.setup(workspace, {})
        agent.act("run")

        traj = agent.get_trajectory()
        assert traj.metrics.total_tool_calls == 1
        assert traj.metrics.total_turns == 1

    def test_raises_on_empty_export(self, model_config):
        """If sessions export returns empty stdout, act() raises (can't get session id)."""
        agent, workspace = _make_agent(model_config, [
            _FakeExecResult(),                       # chat (exit 0)
            _FakeExecResult(exit_code=0, stdout=""),  # export — empty
        ])
        agent.setup(workspace, {})
        with pytest.raises(RuntimeError, match="hermes sessions export failed"):
            agent.act("hi")

    def test_raises_on_multiple_sessions_in_export(self, model_config):
        """If export returns >1 session line, act() raises (assumption violated)."""
        two_sessions = (
            _make_session("sid-a", {"role": "user", "content": "a"})
            + _make_session("sid-b", {"role": "user", "content": "b"})
        )
        agent, workspace = _make_agent(model_config, [
            _FakeExecResult(),
            _FakeExecResult(stdout=two_sessions),
        ])
        agent.setup(workspace, {})
        with pytest.raises(RuntimeError, match="Expected exactly 1 hermes session"):
            agent.act("hi")


class TestParseHermesMessages:
    def test_user_string(self):
        out = _parse_hermes_messages([{"role": "user", "content": "hi"}])
        assert len(out) == 1
        assert isinstance(out[0].content[0], TextBlock)
        assert out[0].content[0].text == "hi"

    def test_user_multi_part(self):
        """OpenAI list-of-parts content yields one TextBlock per text part."""
        out = _parse_hermes_messages([{
            "role": "user",
            "content": [
                {"type": "text", "text": "Part 1"},
                {"type": "text", "text": "Part 2"},
                {"type": "image_url", "image_url": {"url": "..."}},  # non-text part skipped
            ],
        }])
        assert len(out[0].content) == 2
        assert [b.text for b in out[0].content] == ["Part 1", "Part 2"]

    def test_assistant_text_and_tool_call(self):
        out = _parse_hermes_messages([{
            "role": "assistant",
            "content": "running",
            "tool_calls": [{
                "id": "c1", "type": "function",
                "function": {"name": "exec", "arguments": json.dumps({"cmd": "ls"})},
            }],
        }])
        assert isinstance(out[0].content[0], TextBlock)
        assert isinstance(out[0].content[1], ToolUseBlock)
        assert out[0].content[1].name == "exec"
        assert out[0].content[1].input == {"cmd": "ls"}

    def test_assistant_reasoning_prefixes_text(self):
        """reasoning_content becomes a ThinkingBlock prepended to other blocks."""
        out = _parse_hermes_messages([{
            "role": "assistant",
            "reasoning_content": "let me think",
            "content": "answer",
        }])
        assert [type(b).__name__ for b in out[0].content] == ["ThinkingBlock", "TextBlock"]
        assert out[0].content[0].thinking == "let me think"

    def test_reasoning_fallback_to_short_field(self):
        """When reasoning_content is missing, fall back to `reasoning`."""
        out = _parse_hermes_messages([{
            "role": "assistant",
            "reasoning": "short summary",
            "content": "answer",
        }])
        assert isinstance(out[0].content[0], ThinkingBlock)
        assert out[0].content[0].thinking == "short summary"

    def test_consecutive_tool_results_collapse(self):
        """Multiple consecutive `role=tool` messages collapse into one user Message."""
        out = _parse_hermes_messages([
            {"role": "tool", "tool_call_id": "a", "content": "R1"},
            {"role": "tool", "tool_call_id": "b", "content": "R2"},
        ])
        assert len(out) == 1
        assert all(isinstance(b, ToolResultBlock) for b in out[0].content)
        assert [b.tool_use_id for b in out[0].content] == ["a", "b"]

    def test_tool_result_list_content_flattened(self):
        """A tool result with list-of-parts content gets flattened to a single string."""
        out = _parse_hermes_messages([{
            "role": "tool", "tool_call_id": "c1",
            "content": [{"text": "line 1"}, {"text": "line 2"}],
        }])
        assert out[0].content[0].content == "line 1\nline 2"

    def test_full_conversation_shape(self):
        """A realistic 5-entry conversation maps to 4 Terrarium Messages."""
        out = _parse_hermes_messages([
            {"role": "user", "content": "Q"},
            {
                "role": "assistant", "content": "thinking",
                "tool_calls": [{
                    "id": "c1",
                    "function": {"name": "exec", "arguments": "{}"},
                }],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "out"},
            {"role": "assistant", "content": "done"},
        ])
        assert [m.role for m in out] == ["user", "assistant", "user", "assistant"]
