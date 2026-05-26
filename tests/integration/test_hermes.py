"""Integration test: run a real Trial with HermesAgent.

Requires:
- Docker daemon running
- ANTHROPIC_API_KEY and ANTHROPIC_BASE_URL environment variables set
  (hermes routes through `provider: custom` against the proxy base_url)
"""
import os
from pathlib import Path

import pytest

from terrarium.execution.trial import Trial
from terrarium.models.config import AgentConfig, TaskConfig, TrialConfig
from tests.conftest import skip_no_anthropic_base_url, skip_no_anthropic_key, skip_no_docker

pytestmark = [skip_no_docker, skip_no_anthropic_key, skip_no_anthropic_base_url]

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def model_config(tmp_path):
    """Create hermes model config YAML pointing at the proxy from env."""
    p = tmp_path / "hermes_model.yaml"
    p.write_text(
        "provider: custom\n"
        f"api_key: {os.environ['ANTHROPIC_API_KEY']}\n"
        f"base_url: {os.environ['ANTHROPIC_BASE_URL']}\n"
    )
    return str(p)


class TestHermesTrial:
    async def test_single_turn(self, model_config, tmp_path):
        """Run sample_task with a real Hermes agent."""
        config = TrialConfig(
            task=TaskConfig(path=str(FIXTURES_DIR / "sample_task")),
            agent=AgentConfig(
                name="hermes",
                import_path="terrarium.agent.hermes:HermesAgent",
                kwargs={
                    "model": "claude-sonnet-4-6",
                    "model_config_path": model_config,
                },
            ),
            trial_name="hermes_single_turn",
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
