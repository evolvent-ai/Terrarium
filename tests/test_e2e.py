"""End-to-end tests with MockAgent. No Docker needed."""
from pathlib import Path
from unittest.mock import MagicMock, patch

from terrarium import Job, JobConfig, AgentConfig, JobResult, Trial
from terrarium.models.config import TaskConfig, TrialConfig
from terrarium.models.result import TrialResult

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _mock_cr():
    mock_rt = MagicMock()
    mock_ws = MagicMock()
    mock_rt.workspace = mock_ws
    mock_ws.connection_info = {"hostname": "mock-ws"}
    return mock_rt


def _patch_cr():
    mock_rt = _mock_cr()
    mock_cr_cls = MagicMock()
    mock_cr_cls.return_value = mock_rt
    return patch("terrarium.execution.trial.ComposableEnvironment", mock_cr_cls)


class TestTrialEndToEnd:
    async def test_full_flow(self):
        config = TrialConfig(
            task=TaskConfig(path=str(FIXTURES_DIR / "sample_task"), name="sample_task"),
            agent=AgentConfig(name="mock", import_path="tests.agent.mock:MockAgent"),
        )
        with _patch_cr():
            result = await Trial(config).run()

        assert result.task_info.name == "sample_task"
        assert result.checker_result.score == 1.0
        assert len(result.trajectory.messages) == 2
        assert result.exception_info is None

    async def test_serialization(self):
        config = TrialConfig(
            task=TaskConfig(path=str(FIXTURES_DIR / "sample_task"), name="sample_task"),
            agent=AgentConfig(name="mock", import_path="tests.agent.mock:MockAgent"),
        )
        with _patch_cr():
            result = await Trial(config).run()

        json_str = result.model_dump_json()
        restored = TrialResult.model_validate_json(json_str)
        assert restored.task_info.name == result.task_info.name


class TestJobEndToEnd:
    async def test_full_flow(self, tmp_path):
        config = JobConfig(
            agents=[AgentConfig(name="mock", import_path="tests.agent.mock:MockAgent")],
            datasets=[str(FIXTURES_DIR / "sample_dataset")],
            job_dir=tmp_path,
        )
        with _patch_cr():
            result = await Job(config).run()

        assert isinstance(result, JobResult)
        assert len(result.trial_results) == 2
        task_names = sorted([r.task_info.name for r in result.trial_results])
        assert task_names == ["task_a", "task_b"]

        key = list(result.stats.agent_dataset_stats.keys())[0]
        metrics = result.stats.agent_dataset_stats[key].metrics
        assert "mean" in metrics
        assert "max" in metrics
