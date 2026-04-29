"""Integration test: run a real Trial with ClaudeCodeAgent.

Requires:
- Docker daemon running
- ANTHROPIC_API_KEY environment variable set
"""
from pathlib import Path

from terrarium.execution.trial import Trial
from terrarium.models.config import AgentConfig, TaskConfig, TrialConfig
from tests.conftest import skip_no_anthropic_key, skip_no_docker

pytestmark = [skip_no_docker, skip_no_anthropic_key]

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


class TestClaudeCodeTrial:
    async def test_single_turn(self, tmp_path):
        """Run sample_task with a real Claude Code agent."""
        config = TrialConfig(
            task=TaskConfig(path=str(FIXTURES_DIR / "sample_task")),
            agent=AgentConfig(
                name="claude_code",
                import_path="terrarium.agent.claude_code:ClaudeCodeAgent",
                kwargs={"model": "claude-sonnet-4-6", "max_turns": 5},
            ),
            trial_name="claude_code_single_turn",
            trial_dir=tmp_path / "trial",
        )
        trial = Trial(config)
        result = await trial.run()

        print(f"Task: {result.task_info.name}")
        print(f"Score: {result.checker_result.score}")
        print(f"Checks: {result.checker_result.checks}")
        print(f"Trajectory messages: {len(result.trajectory.messages)}")
        print(f"Metrics: {result.trajectory.metrics}")
        if result.exception_info:
            print(f"Exception: {result.exception_info.exception_type}: {result.exception_info.exception_message}")

        assert result.task_info.name == "sample_task"
        assert result.exception_info is None
        assert result.checker_result.score == 1.0
        assert len(result.trajectory.messages) > 0
