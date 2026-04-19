"""Integration test: each agent installs itself into a vanilla ubuntu image.

Requires:
- Docker daemon running
"""
from __future__ import annotations

import json

from terrarium.agent.claude_code import ClaudeCodeAgent
from terrarium.agent.codex import CodexAgent
from terrarium.agent.openclaw import OpenClawAgent
from terrarium.environment.environment import ComposableEnvironment
from tests.conftest import skip_no_docker

pytestmark = [skip_no_docker]


def _run_setup(agent, cli: str) -> None:
    """Start a vanilla ubuntu workspace and run the agent's setup.

    Asserts the CLI is absent before setup and on PATH after.
    """
    env = ComposableEnvironment(
        capabilities=["workspace"],
        config={"workspace": {"image": {"name": "ubuntu:24.04"}}},
    )
    env.start()
    try:
        workspace = env.workspace
        probe = workspace.shell.exec(f"command -v {cli}")
        print(f"Before setup: command -v {cli} → exit={probe.exit_code}")
        assert probe.exit_code != 0, f"ubuntu:24.04 unexpectedly has {cli} pre-installed"

        agent.setup(workspace, {})
        print(f"Agent version: {agent.version()!r}")

        check = workspace.shell.exec(f"{cli} --version")
        print(f"After setup: {cli} --version → exit={check.exit_code} stdout={check.stdout.strip()!r}")
        assert check.exit_code == 0
    finally:
        env.stop()


class TestSelfInstall:
    def test_claude_code(self):
        """ClaudeCodeAgent installs claude via curl+install.sh, symlinks to /usr/local/bin."""
        _run_setup(ClaudeCodeAgent(), "claude")

    def test_codex(self):
        """CodexAgent installs NVM + Node 22 + codex via npm, symlinks node+codex."""
        _run_setup(CodexAgent(), "codex")

    def test_openclaw(self, tmp_path):
        """OpenClawAgent installs via install.sh (npm-based); binary already on PATH."""
        models_cfg = tmp_path / "models.json"
        models_cfg.write_text(json.dumps({
            "providers": {"smoke": {"baseUrl": "https://example.invalid", "apiKey": "na",
                                     "api": "openai-completions",
                                     "models": [{"id": "m", "name": "m"}]}},
        }))
        _run_setup(OpenClawAgent(models_config_path=str(models_cfg)), "openclaw")
