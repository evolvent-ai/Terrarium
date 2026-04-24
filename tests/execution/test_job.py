"""Tests for Job execution engine."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from terrarium.execution.events import JobEvent, JobEventPayload, TrialEvent, TrialEventPayload
from terrarium.execution.job import Job
from terrarium.models.config import AgentConfig, JobConfig

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
SAMPLE_TASK_DIR = FIXTURES_DIR / "sample_task"
SAMPLE_DATASET_DIR = FIXTURES_DIR / "sample_dataset"
MOCK_AGENT_IMPORT = "tests.agent.mock:MockAgent"


def _mock_agent_cfg() -> AgentConfig:
    return AgentConfig(name="mock", import_path=MOCK_AGENT_IMPORT)


def _make_mock_rt():
    """Sync MagicMock mimicking ComposableEnvironment."""
    mock_cap = MagicMock()
    mock_cap.connection_info = {"hostname": "localhost"}
    mock_rt = MagicMock()
    mock_rt.workspace = mock_cap
    return mock_rt


async def test_single_task(tmp_path):
    """1 agent x 1 task -> 1 trial result."""
    cfg = JobConfig(
        agents=[_mock_agent_cfg()],
        tasks=[str(SAMPLE_TASK_DIR)],
        job_dir=tmp_path,
    )
    mock_rt = _make_mock_rt()
    with patch("terrarium.execution.trial.ComposableEnvironment", return_value=mock_rt):
        result = await Job(cfg).run()

    assert len(result.trial_results) == 1
    assert result.stats.n_trials == 1


async def test_dataset(tmp_path):
    """1 agent x sample_dataset (2 tasks) -> 2 trials, stats key includes agent and dataset."""
    cfg = JobConfig(
        agents=[_mock_agent_cfg()],
        datasets=[str(SAMPLE_DATASET_DIR)],
        job_dir=tmp_path,
    )
    mock_rt = _make_mock_rt()
    with patch("terrarium.execution.trial.ComposableEnvironment", return_value=mock_rt):
        result = await Job(cfg).run()

    assert len(result.trial_results) == 2
    assert result.stats.n_trials == 2

    # Stats key format: "{agent}__{model}__{dataset}"
    keys = list(result.stats.agent_dataset_stats.keys())
    assert len(keys) == 1
    key = keys[0]
    assert "mock" in key
    assert "sample_dataset" in key


async def test_n_attempts(tmp_path):
    """n_attempts=3 produces 3 trials for one task."""
    cfg = JobConfig(
        agents=[_mock_agent_cfg()],
        tasks=[str(SAMPLE_TASK_DIR)],
        n_attempts=3,
        job_dir=tmp_path,
    )
    mock_rt = _make_mock_rt()
    with patch("terrarium.execution.trial.ComposableEnvironment", return_value=mock_rt):
        result = await Job(cfg).run()

    assert len(result.trial_results) == 3
    assert result.stats.n_trials == 3


async def test_dataset_metrics(tmp_path):
    """Dataset-level metrics (mean, max from dataset.toml) are used in stats."""
    cfg = JobConfig(
        agents=[_mock_agent_cfg()],
        datasets=[str(SAMPLE_DATASET_DIR)],
        job_dir=tmp_path,
    )
    mock_rt = _make_mock_rt()
    with patch("terrarium.execution.trial.ComposableEnvironment", return_value=mock_rt):
        result = await Job(cfg).run()

    for group_stats in result.stats.agent_dataset_stats.values():
        # dataset.toml defines mean + max
        assert "mean" in group_stats.metrics
        assert "max" in group_stats.metrics


async def test_adhoc_default_metrics(tmp_path):
    """Adhoc tasks (no dataset) get default Mean metric."""
    cfg = JobConfig(
        agents=[_mock_agent_cfg()],
        tasks=[str(SAMPLE_TASK_DIR)],
        job_dir=tmp_path,
    )
    mock_rt = _make_mock_rt()
    with patch("terrarium.execution.trial.ComposableEnvironment", return_value=mock_rt):
        result = await Job(cfg).run()

    for group_stats in result.stats.agent_dataset_stats.values():
        assert "mean" in group_stats.metrics


async def test_persistence(tmp_path):
    """job_dir contains config.json and result.json."""
    job_dir = tmp_path / "my_job"
    cfg = JobConfig(
        agents=[_mock_agent_cfg()],
        tasks=[str(SAMPLE_TASK_DIR)],
        job_dir=job_dir,
    )
    mock_rt = _make_mock_rt()
    with patch("terrarium.execution.trial.ComposableEnvironment", return_value=mock_rt):
        await Job(cfg).run()

    assert job_dir.is_dir()
    assert (job_dir / "config.json").exists()
    assert (job_dir / "result.json").exists()

    config_data = json.loads((job_dir / "config.json").read_text())
    result_data = json.loads((job_dir / "result.json").read_text())
    assert "agents" in config_data
    assert "trial_results" in result_data


async def test_on_registers_trial_event_handler(tmp_path):
    """job.on(TrialEvent.SUCCEEDED, handler) fires when a trial succeeds."""
    cfg = JobConfig(
        agents=[_mock_agent_cfg()],
        tasks=[str(SAMPLE_TASK_DIR)],
        job_dir=tmp_path,
    )
    job = Job(cfg)
    received: list[TrialEventPayload] = []
    job.on(TrialEvent.SUCCEEDED, received.append)

    mock_rt = _make_mock_rt()
    with patch("terrarium.execution.trial.ComposableEnvironment", return_value=mock_rt):
        await job.run()

    assert len(received) == 1
    assert received[0].payload.result.checker_result.score == 1.0


async def test_on_returns_self_for_chaining(tmp_path):
    """job.on(...) returns the job so subscribers can chain."""
    cfg = JobConfig(
        agents=[_mock_agent_cfg()],
        tasks=[str(SAMPLE_TASK_DIR)],
        job_dir=tmp_path,
    )
    job = Job(cfg)
    assert job.on(TrialEvent.SUCCEEDED, lambda p: None) is job


async def test_job_started_event_carries_n_trials(tmp_path):
    """JobStartedPayload exposes the total trial count for UI sizing."""
    cfg = JobConfig(
        agents=[_mock_agent_cfg()],
        tasks=[str(SAMPLE_TASK_DIR)],
        n_attempts=3,
        job_dir=tmp_path,
    )
    job = Job(cfg)
    received: list[JobEventPayload] = []
    job.on(JobEvent.STARTED, received.append)

    mock_rt = _make_mock_rt()
    with patch("terrarium.execution.trial.ComposableEnvironment", return_value=mock_rt):
        await job.run()

    assert len(received) == 1
    assert received[0].payload.n_trials == 3


async def test_job_events_bookend_trial_events(tmp_path):
    """JobEvent.STARTED fires before any trial event; FINISHED fires last."""
    cfg = JobConfig(
        agents=[_mock_agent_cfg()],
        tasks=[str(SAMPLE_TASK_DIR)],
        job_dir=tmp_path,
    )
    job = Job(cfg)
    sequence: list[str] = []
    for evt in (JobEvent.STARTED, JobEvent.FINISHED):
        job.on(evt, lambda p, e=evt: sequence.append(f"job_{e.value}"))
    for evt in TrialEvent:
        job.on(evt, lambda p, e=evt: sequence.append(f"trial_{e.value}"))

    mock_rt = _make_mock_rt()
    with patch("terrarium.execution.trial.ComposableEnvironment", return_value=mock_rt):
        await job.run()

    assert sequence[0] == "job_started"
    assert sequence[-1] == "job_finished"
    assert sequence[1:-1] == ["trial_queued", "trial_started", "trial_succeeded"]
