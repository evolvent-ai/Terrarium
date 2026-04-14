"""Unit tests for OpenClawAgent (no Docker required)."""
import json

import pytest
from terrarium.agent.openclaw import (
    OpenClawAgent, SESSION_DIR, SKILLS_DIR, _parse_session_message,
)
from terrarium.models.trajectory import TextBlock, ToolUseBlock, ToolResultBlock


class _FakeExecResult:
    def __init__(self, exit_code=0, stdout="", stderr=""):
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr


class _FakeFS:
    def __init__(self):
        self.make_dir_calls: list[str] = []
        self.write_file_calls: list[tuple[str, bytes]] = []
        self.upload_calls: list[tuple[str, str]] = []
        self._files: dict[str, bytes] = {}

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

    def exec(self, command, timeout=None):
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
def models_config(tmp_path):
    config = {"providers": {"test": {"baseUrl": "http://localhost", "api": "openai-completions",
              "models": [{"id": "test-model", "name": "test"}]}}}
    p = tmp_path / "models.json"
    p.write_text(json.dumps(config))
    return str(p)


def _make_agent(models_config, shell_responses=None):
    responses = shell_responses or [_FakeExecResult(stdout="openclaw version 2026.4.1")]
    workspace = _FakeWorkspace(shell_responses=responses)
    agent = OpenClawAgent(models_config_path=models_config)
    agent._workspace = workspace
    return agent, workspace


def _make_session(*entries):
    lines = [json.dumps({"type": "session", "version": 7, "id": "test-session"})]
    for entry in entries:
        lines.append(json.dumps({"type": "message", "message": entry}))
    return "\n".join(lines)


class TestParseSessionMessage:
    def test_user(self):
        msg = {"role": "user", "content": [{"type": "text", "text": "Hello"}]}
        result = _parse_session_message(msg)
        assert result.role == "user"
        assert isinstance(result.content[0], TextBlock)
        assert result.content[0].text == "Hello"

    def test_assistant_text(self):
        msg = {"role": "assistant", "content": [{"type": "text", "text": "Hi"}]}
        result = _parse_session_message(msg)
        assert result.role == "assistant"
        assert isinstance(result.content[0], TextBlock)

    def test_assistant_tool_call(self):
        msg = {
            "role": "assistant",
            "content": [{"type": "toolCall", "id": "c1", "name": "exec", "arguments": {"command": "ls"}}],
        }
        result = _parse_session_message(msg)
        assert result.role == "assistant"
        assert isinstance(result.content[0], ToolUseBlock)
        assert result.content[0].name == "exec"
        assert result.content[0].input == {"command": "ls"}

    def test_assistant_mixed_blocks(self):
        msg = {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Let me check"},
                {"type": "toolCall", "id": "c1", "name": "read", "arguments": {}},
            ],
        }
        result = _parse_session_message(msg)
        assert len(result.content) == 2
        assert isinstance(result.content[0], TextBlock)
        assert isinstance(result.content[1], ToolUseBlock)

    def test_tool_result(self):
        msg = {
            "role": "toolResult",
            "toolCallId": "c1",
            "content": [{"type": "text", "text": "file.txt"}],
        }
        result = _parse_session_message(msg)
        assert result.role == "user"
        assert isinstance(result.content[0], ToolResultBlock)
        assert result.content[0].tool_use_id == "c1"
        assert result.content[0].content == "file.txt"

    def test_unknown_role(self):
        assert _parse_session_message({"role": "system"}) is None


class TestSetup:
    def test_writes_config(self, tmp_path):
        """Writes openclaw.json with models config and exec security."""
        models_config = {
            "providers": {"mycloud": {"baseUrl": "https://api.example.com", "apiKey": "sk-test",
                          "api": "openai-completions", "models": [{"id": "m", "name": "M"}]}}
        }
        config_file = tmp_path / "models.json"
        config_file.write_text(json.dumps(models_config))

        workspace = _FakeWorkspace(shell_responses=[
            _FakeExecResult(stdout="openclaw version 2026.4.1"),
        ])
        agent = OpenClawAgent(model="mycloud/m", models_config_path=str(config_file))
        agent.setup(workspace, {})

        config_writes = [c for c in workspace.fs.write_file_calls if "openclaw.json" in c[0]]
        config = json.loads(config_writes[0][1])
        assert config["models"] == models_config
        assert config["agents"]["defaults"]["model"]["primary"] == "mycloud/m"
        assert config["tools"]["exec"]["security"] == "full"


class TestAct:
    def test_reads_session(self, models_config):
        """Reads full trajectory from session JSONL."""
        session = _make_session(
            {"role": "user", "content": [{"type": "text", "text": "Do something"}]},
            {"role": "assistant", "content": [
                {"type": "text", "text": "Running command"},
                {"type": "toolCall", "id": "c1", "name": "exec", "arguments": {"command": "ls"}},
            ], "usage": {"input": 100, "output": 20}},
            {"role": "toolResult", "toolCallId": "c1",
             "content": [{"type": "text", "text": "file.txt"}]},
            {"role": "assistant", "content": [{"type": "text", "text": "Found file.txt"}],
             "usage": {"input": 50, "output": 10}},
        )

        agent, workspace = _make_agent(models_config, [
            _FakeExecResult(stdout="openclaw version 2026.4.1"),
            _FakeExecResult(),
        ])
        agent.setup(workspace, {})
        workspace.fs.set_file(f"{SESSION_DIR}/{agent._session_id}.jsonl", session.encode())

        result = agent.act("Do something")
        assert len(result.messages) == 4
        assert result.messages[0].role == "user"
        assert isinstance(result.messages[1].content[1], ToolUseBlock)
        assert result.messages[2].role == "user"
        assert result.input_tokens == 150
        assert result.output_tokens == 30

    def test_tool_calls_in_trajectory(self, models_config):
        """get_trajectory() counts tool calls."""
        session = _make_session(
            {"role": "user", "content": [{"type": "text", "text": "Do it"}]},
            {"role": "assistant", "content": [
                {"type": "toolCall", "id": "c1", "name": "exec", "arguments": {}},
                {"type": "toolCall", "id": "c2", "name": "read", "arguments": {}},
            ], "usage": {"input": 100, "output": 20}},
            {"role": "toolResult", "toolCallId": "c1", "content": [{"type": "text", "text": "ok"}]},
            {"role": "toolResult", "toolCallId": "c2", "content": [{"type": "text", "text": "data"}]},
            {"role": "assistant", "content": [{"type": "text", "text": "Done"}],
             "usage": {"input": 50, "output": 10}},
        )

        agent, workspace = _make_agent(models_config, [
            _FakeExecResult(stdout="openclaw version 2026.4.1"),
            _FakeExecResult(),
        ])
        agent.setup(workspace, {})
        workspace.fs.set_file(f"{SESSION_DIR}/{agent._session_id}.jsonl", session.encode())
        agent.act("Do it")

        traj = agent.get_trajectory()
        assert traj.metrics.total_tool_calls == 2
        assert traj.metrics.total_llm_calls == 1

    def test_multi_turn_incremental(self, models_config):
        """Multiple act() calls only read new session entries."""
        turn1 = _make_session(
            {"role": "user", "content": [{"type": "text", "text": "Turn 1"}]},
            {"role": "assistant", "content": [{"type": "text", "text": "Response 1"}],
             "usage": {"input": 100, "output": 50}},
        )
        turn2 = turn1 + "\n" + "\n".join([
            json.dumps({"type": "message", "message": {"role": "user", "content": [{"type": "text", "text": "Turn 2"}]}}),
            json.dumps({"type": "message", "message": {"role": "assistant", "content": [{"type": "text", "text": "Response 2"}],
                        "usage": {"input": 200, "output": 75}}}),
        ])

        agent, workspace = _make_agent(models_config, [
            _FakeExecResult(stdout="openclaw version 2026.4.1"),
            _FakeExecResult(),
            _FakeExecResult(),
        ])
        agent.setup(workspace, {})
        path = f"{SESSION_DIR}/{agent._session_id}.jsonl"

        workspace.fs.set_file(path, turn1.encode())
        r1 = agent.act("Turn 1")
        assert len(r1.messages) == 2

        workspace.fs.set_file(path, turn2.encode())
        r2 = agent.act("Turn 2")
        assert len(r2.messages) == 2

        traj = agent.get_trajectory()
        assert len(traj.messages) == 4
        assert traj.metrics.total_input_tokens == 300


class TestInstallSkill:
    def test_uploads_directory(self, tmp_path, models_config):
        """Uploads skill dir to ~/.openclaw/workspace/skills/<name>."""
        skill_dir = tmp_path / "my_skill"
        skill_dir.mkdir()

        agent, workspace = _make_agent(models_config)
        agent.setup(workspace, {})
        agent.install_skill(skill_dir)

        assert workspace.fs.upload_calls == [(str(skill_dir), f"{SKILLS_DIR}/my_skill")]

    def test_rejects_missing_path(self, tmp_path, models_config):
        """Raises if path does not exist."""
        agent, workspace = _make_agent(models_config)
        agent.setup(workspace, {})
        with pytest.raises(FileNotFoundError, match="not a directory"):
            agent.install_skill(tmp_path / "nonexistent")

    def test_rejects_file(self, tmp_path, models_config):
        """Raises if path is a file, not a directory."""
        (tmp_path / "SKILL.md").write_text("not a dir")

        agent, workspace = _make_agent(models_config)
        agent.setup(workspace, {})
        with pytest.raises(FileNotFoundError, match="not a directory"):
            agent.install_skill(tmp_path / "SKILL.md")


def test_name_and_workspace_config():
    assert OpenClawAgent.name() == "openclaw"
    assert OpenClawAgent.workspace_config() == {"image": "terrarium/openclaw:latest"}
