"""Unit tests for ClaudeCodeAgent (no Docker required)."""
import pytest
from terrarium.agent.claude_code import SKILLS_DIR, ClaudeCodeAgent


class _FakeFS:
    def __init__(self):
        self.make_dir_calls: list[str] = []
        self.upload_calls: list[tuple[str, str]] = []

    def make_dir(self, path: str) -> None:
        self.make_dir_calls.append(path)

    def upload(self, local_path: str, sandbox_path: str) -> None:
        self.upload_calls.append((local_path, sandbox_path))


class _FakeWorkspace:
    def __init__(self):
        self.fs = _FakeFS()


def _make_agent():
    agent = ClaudeCodeAgent()
    agent._workspace = _FakeWorkspace()
    return agent


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
