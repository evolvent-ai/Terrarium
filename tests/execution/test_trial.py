"""Tests for Trial execution engine."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from terrarium.execution.trial import Trial
from terrarium.models.config import AgentConfig, TaskConfig, TrialConfig

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
SAMPLE_TASK_DIR = FIXTURES_DIR / "sample_task"
MOCK_AGENT_IMPORT = "tests.agent.mock:MockAgent"


def _make_config(**kwargs) -> TrialConfig:
    return TrialConfig(
        task=TaskConfig(path=str(SAMPLE_TASK_DIR)),
        agent=AgentConfig(name="mock", import_path=MOCK_AGENT_IMPORT),
        **kwargs,
    )


def _make_mock_rt():
    """Build a sync MagicMock that mimics ComposableEnvironment."""
    mock_cap = MagicMock()
    mock_cap.connection_info = {"hostname": "localhost"}
    mock_rt = MagicMock()
    mock_rt.workspace = mock_cap
    return mock_rt


@pytest.mark.asyncio
async def test_run_sample_task():
    """A successful trial has score=1.0, non-empty trajectory, no exception."""
    mock_rt = _make_mock_rt()
    with patch("terrarium.execution.trial.ComposableEnvironment", return_value=mock_rt):
        result = await Trial(_make_config()).run()

    assert result.exception_info is None
    assert result.checker_result.score == 1.0
    # trajectory should have messages from act()
    assert len(result.trajectory.messages) > 0


@pytest.mark.asyncio
async def test_trial_name_auto():
    """Auto-generated trial_name includes the task name."""
    mock_rt = _make_mock_rt()
    with patch("terrarium.execution.trial.ComposableEnvironment", return_value=mock_rt):
        result = await Trial(_make_config()).run()

    assert "sample_task" in result.trial_name


@pytest.mark.asyncio
async def test_trial_name_explicit():
    """An explicit trial_name is preserved."""
    mock_rt = _make_mock_rt()
    with patch("terrarium.execution.trial.ComposableEnvironment", return_value=mock_rt):
        result = await Trial(_make_config(trial_name="my_custom_trial")).run()

    assert result.trial_name == "my_custom_trial"


@pytest.mark.asyncio
async def test_exception_captured():
    """When ComposableEnvironment raises, exception_info is set and score remains 0."""
    mock_rt = MagicMock()
    mock_rt.start = MagicMock(side_effect=RuntimeError("boom"))
    mock_rt.stop = MagicMock()

    with patch("terrarium.execution.trial.ComposableEnvironment", return_value=mock_rt):
        result = await Trial(_make_config()).run()

    assert result.exception_info is not None
    assert result.exception_info.exception_type == "RuntimeError"
    assert result.checker_result.score == 0.0


@pytest.mark.asyncio
async def test_persistence(tmp_path):
    """When trial_dir is set, config.json and result.json are written."""
    trial_dir = tmp_path / "my_trial"
    mock_rt = _make_mock_rt()
    with patch("terrarium.execution.trial.ComposableEnvironment", return_value=mock_rt):
        await Trial(_make_config(trial_dir=trial_dir)).run()

    assert (trial_dir / "config.json").exists()
    assert (trial_dir / "result.json").exists()

    # Quick sanity check on JSON content
    config_data = json.loads((trial_dir / "config.json").read_text())
    result_data = json.loads((trial_dir / "result.json").read_text())
    assert "task" in config_data
    assert "trial_name" in result_data


@pytest.mark.asyncio
async def test_timing_info_recorded():
    """setup_timing and execution_timing are populated."""
    mock_rt = _make_mock_rt()
    with patch("terrarium.execution.trial.ComposableEnvironment", return_value=mock_rt):
        result = await Trial(_make_config()).run()

    assert result.setup_timing is not None
    assert result.setup_timing.started_at is not None
    assert result.setup_timing.finished_at is not None
    assert result.execution_timing is not None
    assert result.execution_timing.started_at is not None
    assert result.execution_timing.finished_at is not None
