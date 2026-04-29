"""Tests for configuration models."""
from pathlib import Path
import pytest
from pydantic import ValidationError

from terrarium.models.config import (
    AgentConfig,
    JobConfig,
    RetryConfig,
    TaskConfig,
    TrialConfig,
)


class TestAgentConfig:
    def test_defaults(self):
        cfg = AgentConfig(name="my_agent")
        assert cfg.name == "my_agent"
        assert cfg.import_path is None
        assert cfg.model_name is None
        assert cfg.kwargs == {}

    def test_full(self):
        cfg = AgentConfig(
            name="gpt_agent",
            import_path="mypackage.agents.GptAgent",
            model_name="gpt-4o",
            kwargs={"temperature": 0.7, "max_tokens": 1024},
        )
        assert cfg.import_path == "mypackage.agents.GptAgent"
        assert cfg.model_name == "gpt-4o"
        assert cfg.kwargs["temperature"] == 0.7


class TestTaskConfig:
    def test_defaults(self):
        cfg = TaskConfig(path="tasks/my_task.py")
        assert cfg.path == "tasks/my_task.py"
        assert cfg.source == "adhoc"

    def test_with_source(self):
        cfg = TaskConfig(path="datasets/gsm8k/task_01", source="gsm8k")
        assert cfg.source == "gsm8k"


class TestRetryConfig:
    def test_defaults(self):
        cfg = RetryConfig()
        assert cfg.max_retries == 0
        assert cfg.min_wait_sec == 1.0
        assert cfg.max_wait_sec == 60.0
        assert cfg.wait_multiplier == 2.0

    def test_custom(self):
        cfg = RetryConfig(max_retries=3, min_wait_sec=2.0, max_wait_sec=30.0)
        assert cfg.max_retries == 3
        assert cfg.min_wait_sec == 2.0


class TestTrialConfig:
    def test_required_fields(self):
        with pytest.raises(ValidationError):
            TrialConfig(
                task=TaskConfig(path="t.py"),
                agent=AgentConfig(name="a"),
            )

    def test_with_trial_dir(self):
        cfg = TrialConfig(
            task=TaskConfig(path="t.py"),
            agent=AgentConfig(name="a"),
            trial_name="run_01",
            trial_dir=Path("/tmp/trials/run_01"),
        )
        assert cfg.trial_name == "run_01"
        assert cfg.trial_dir == Path("/tmp/trials/run_01")
        assert cfg.agent_setup_timeout_sec is None
        assert cfg.agent_exec_timeout_sec is None


class TestJobConfig:
    def test_defaults(self):
        cfg = JobConfig(agents=[AgentConfig(name="agent_a")])
        assert len(cfg.agents) == 1
        assert cfg.datasets == []
        assert cfg.tasks == []
        assert cfg.n_attempts == 1
        assert cfg.n_concurrent_trials == 4
        assert isinstance(cfg.retry, RetryConfig)
        assert cfg.retry.max_retries == 0
        # job_name auto-generated from timestamp; job_dir derived from it
        assert cfg.job_name
        assert cfg.job_dir == Path("outputs") / cfg.job_name
        assert cfg.agent_setup_timeout_sec is None
        assert cfg.agent_exec_timeout_sec is None

    def test_serialization(self):
        cfg = JobConfig(
            agents=[AgentConfig(name="a", model_name="gpt-4o")],
            datasets=["gsm8k"],
            n_attempts=3,
        )
        data = cfg.model_dump()
        assert data["n_attempts"] == 3
        assert data["agents"][0]["model_name"] == "gpt-4o"
        assert data["datasets"] == ["gsm8k"]

    def test_round_trip(self):
        cfg = JobConfig(
            agents=[AgentConfig(name="a")],
        )
        json_str = cfg.model_dump_json()
        cfg2 = JobConfig.model_validate_json(json_str)
        assert cfg2.agents[0].name == "a"
