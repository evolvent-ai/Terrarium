"""Tests for TrialQueue."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from terrarium.execution.queue import TrialQueue
from terrarium.models.config import AgentConfig, RetryConfig, TaskConfig, TrialConfig

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
SAMPLE_TASK_DIR = FIXTURES_DIR / "sample_task"
MOCK_AGENT_IMPORT = "tests.agent.mock:MockAgent"


def _make_config(trial_name: str = "") -> TrialConfig:
    return TrialConfig(
        task=TaskConfig(path=str(SAMPLE_TASK_DIR)),
        agent=AgentConfig(name="mock", import_path=MOCK_AGENT_IMPORT),
        trial_name=trial_name,
    )


def _make_mock_rt():
    """Sync MagicMock mimicking ComposableEnvironment."""
    mock_cap = MagicMock()
    mock_cap.connection_info = {"hostname": "localhost"}
    mock_rt = MagicMock()
    mock_rt.workspace = mock_cap
    return mock_rt


@pytest.mark.asyncio
async def test_run_single():
    """One config produces exactly one result."""
    mock_rt = _make_mock_rt()
    with patch("terrarium.execution.trial.ComposableEnvironment", return_value=mock_rt):
        results = await TrialQueue(n_concurrent=1).run([_make_config("t1")])

    assert len(results) == 1
    assert results[0].exception_info is None
    assert results[0].checker_result.score == 1.0


@pytest.mark.asyncio
async def test_run_concurrent():
    """Four configs with n_concurrent=2 all complete and return 4 results."""
    mock_rt = _make_mock_rt()
    configs = [_make_config(f"trial_{i}") for i in range(4)]
    with patch("terrarium.execution.trial.ComposableEnvironment", return_value=mock_rt):
        results = await TrialQueue(n_concurrent=2).run(configs)

    assert len(results) == 4
    assert all(r.exception_info is None for r in results)


@pytest.mark.asyncio
async def test_retry_succeeds_on_second_attempt(monkeypatch):
    """A trial that fails once is retried and returns the successful result."""
    call_count = 0
    real_rt_factory = None

    def failing_then_ok(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            m = MagicMock()
            m.start = MagicMock(side_effect=RuntimeError("transient"))
            m.stop = MagicMock()
            return m
        return _make_mock_rt()

    retry = RetryConfig(max_retries=1, min_wait_sec=0.01, max_wait_sec=0.01)
    with patch("terrarium.execution.trial.ComposableEnvironment", side_effect=failing_then_ok):
        results = await TrialQueue(n_concurrent=1, retry_config=retry).run([_make_config()])

    assert len(results) == 1
    assert results[0].exception_info is None
    assert call_count == 2


@pytest.mark.asyncio
async def test_no_retry_on_max_retries_zero():
    """With max_retries=0, a failing trial is returned as-is (with exception_info)."""
    mock_rt = MagicMock()
    mock_rt.start = MagicMock(side_effect=RuntimeError("boom"))
    mock_rt.stop = MagicMock()

    retry = RetryConfig(max_retries=0)
    with patch("terrarium.execution.trial.ComposableEnvironment", return_value=mock_rt):
        results = await TrialQueue(n_concurrent=1, retry_config=retry).run([_make_config()])

    assert len(results) == 1
    assert results[0].exception_info is not None
    assert results[0].exception_info.exception_type == "RuntimeError"
