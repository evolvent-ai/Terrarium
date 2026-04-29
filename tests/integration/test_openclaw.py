"""Integration test: run a real Trial with OpenClawAgent.

Requires:
- Docker daemon running
- OPENROUTER_API_KEY environment variable set
"""
import json
import os
from pathlib import Path

import pytest

from terrarium.execution.trial import Trial
from terrarium.models.config import AgentConfig, TaskConfig, TrialConfig
from tests.conftest import skip_no_docker, skip_no_openrouter_key

pytestmark = [skip_no_docker, skip_no_openrouter_key]

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def models_config(tmp_path):
    """Create models config with API key from environment."""
    config = {
        "providers": {
            "terrarium": {
                "baseUrl": "https://openrouter.ai/api/v1",
                "apiKey": os.environ["OPENROUTER_API_KEY"],
                "api": "anthropic-messages",
                "models": [{"id": "anthropic/claude-sonnet-4.6", "name": "Claude Sonnet 4.6", "reasoning": True}],
            }
        }
    }
    p = tmp_path / "models.json"
    p.write_text(json.dumps(config))
    return str(p)


class TestOpenClawTrial:
    async def test_single_turn(self, models_config, tmp_path):
        """Run sample_task with a real OpenClaw agent."""
        config = TrialConfig(
            task=TaskConfig(path=str(FIXTURES_DIR / "sample_task")),
            agent=AgentConfig(
                name="openclaw",
                import_path="terrarium.agent.openclaw:OpenClawAgent",
                kwargs={
                    "model": "terrarium/anthropic/claude-sonnet-4.6",
                    "models_config_path": models_config,
                },
            ),
            trial_name="openclaw_single_turn",
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
