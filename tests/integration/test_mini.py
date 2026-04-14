"""Integration test: run a real Trial with MiniAgent.

Requires:
- OPENROUTER_API_KEY environment variable set
"""
from pathlib import Path

from terrarium.execution.trial import Trial
from terrarium.models.config import AgentConfig, TaskConfig, TrialConfig
from tests.conftest import skip_no_openrouter_key

pytestmark = [skip_no_openrouter_key]

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


class TestMiniTrial:
    async def test_tool_call(self):
        """Run tool_call_task with a real MiniAgent via OpenRouter."""
        config = TrialConfig(
            task=TaskConfig(path=str(FIXTURES_DIR / "tool_call_task")),
            agent=AgentConfig(
                name="mini",
                import_path="terrarium.agent.mini:MiniAgent",
                kwargs={"model": "openrouter/openai/gpt-4o-mini"},
            ),
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

        assert result.task_info.name == "tool_call_task"
        assert result.exception_info is None
        assert result.checker_result.score == 1.0
        assert len(result.trajectory.messages) > 0
        assert result.trajectory.metrics.total_input_tokens > 0
        assert result.trajectory.metrics.total_output_tokens > 0
        assert result.trajectory.metrics.total_tool_calls >= 1
