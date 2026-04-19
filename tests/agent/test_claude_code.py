"""Unit tests for ClaudeCodeAgent (no Docker required)."""
import pytest
from terrarium.agent.claude_code import SKILLS_DIR, ClaudeCodeAgent


class _FakeExecResult:
    def __init__(self, exit_code=0, stdout="", stderr=""):
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr


class _FakeFS:
    def __init__(self):
        self.make_dir_calls: list[str] = []
        self.upload_calls: list[tuple[str, str]] = []

    def make_dir(self, path: str) -> None:
        self.make_dir_calls.append(path)

    def upload(self, local_path: str, sandbox_path: str) -> None:
        self.upload_calls.append((local_path, sandbox_path))


class _FakeShell:
    def __init__(self, responses=None):
        self._responses = responses or []
        self._call_index = 0
        self.commands: list[str] = []

    def exec(self, command, timeout=None):
        self.commands.append(command)
        if self._call_index < len(self._responses):
            result = self._responses[self._call_index]
            self._call_index += 1
            return result
        return _FakeExecResult()


class _FakeWorkspace:
    def __init__(self, shell_responses=None):
        self.fs = _FakeFS()
        self.shell = _FakeShell(shell_responses)


def _make_agent(shell_responses=None):
    agent = ClaudeCodeAgent()
    agent._workspace = _FakeWorkspace(shell_responses=shell_responses)
    return agent


class TestEnsureInstalled:
    def test_skips_install_when_present(self):
        """If `claude` is on PATH, no install command is run."""
        agent = _make_agent(shell_responses=[
            _FakeExecResult(exit_code=0, stdout="/usr/local/bin/claude"),
        ])
        agent._ensure_installed()
        assert agent._workspace.shell.commands == ["command -v claude"]

    def test_runs_install_when_missing(self):
        """If `claude` is absent, the install script is executed."""
        agent = _make_agent(shell_responses=[
            _FakeExecResult(exit_code=1),  # command -v claude → not found
            _FakeExecResult(exit_code=0),  # install succeeds
        ])
        agent._ensure_installed()
        cmds = agent._workspace.shell.commands
        assert len(cmds) == 2
        assert cmds[0] == "command -v claude"
        assert "claude.ai/install.sh" in cmds[1]

    def test_raises_when_install_fails(self):
        """RuntimeError is raised if the install script exits non-zero."""
        agent = _make_agent(shell_responses=[
            _FakeExecResult(exit_code=1),
            _FakeExecResult(exit_code=1, stderr="install.sh 404"),
        ])
        with pytest.raises(RuntimeError, match="Failed to install Claude Code CLI"):
            agent._ensure_installed()


class TestInstallSkill:
    def test_uploads_directory(self, tmp_path):
        """Uploads the skill dir to /root/.claude/skills/<name>."""
        skill_dir = tmp_path / "db_helper"
        skill_dir.mkdir()

        agent = _make_agent()
        agent.install_skill(skill_dir)

        fs = agent._workspace.fs
        assert fs.make_dir_calls == [SKILLS_DIR]
        assert fs.upload_calls == [(str(skill_dir.resolve()), f"{SKILLS_DIR}/db_helper")]

    def test_accepts_string_path(self, tmp_path):
        """Accepts str path, not just Path."""
        skill_dir = tmp_path / "parser"
        skill_dir.mkdir()

        agent = _make_agent()
        agent.install_skill(str(skill_dir))

        assert agent._workspace.fs.upload_calls[0][1] == f"{SKILLS_DIR}/parser"

    def test_rejects_missing_path(self, tmp_path):
        """Raises if path does not exist."""
        agent = _make_agent()
        with pytest.raises(FileNotFoundError, match="not a directory"):
            agent.install_skill(tmp_path / "nonexistent")

    def test_rejects_file(self, tmp_path):
        """Raises if path is a file, not a directory."""
        (tmp_path / "SKILL.md").write_text("not a dir")

        agent = _make_agent()
        with pytest.raises(FileNotFoundError, match="not a directory"):
            agent.install_skill(tmp_path / "SKILL.md")

    def test_multiple(self, tmp_path):
        """Multiple install_skill calls all land in /root/.claude/skills."""
        (tmp_path / "a").mkdir()
        (tmp_path / "b").mkdir()

        agent = _make_agent()
        agent.install_skill(tmp_path / "a")
        agent.install_skill(tmp_path / "b")

        dests = [call[1] for call in agent._workspace.fs.upload_calls]
        assert dests == [f"{SKILLS_DIR}/a", f"{SKILLS_DIR}/b"]

    def test_skills_dir_property(self):
        """skills_dir property exposes the in-container skills path."""
        assert _make_agent().skills_dir == SKILLS_DIR
