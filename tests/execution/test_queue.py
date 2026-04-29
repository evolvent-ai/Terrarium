"""Tests for TrialQueue."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from terrarium.execution.events import EventBus, TrialEvent, TrialEventPayload
from terrarium.execution.queue import TrialQueue
from terrarium.models.config import AgentConfig, RetryConfig, TaskConfig, TrialConfig

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
SAMPLE_TASK_DIR = FIXTURES_DIR / "sample_task"
MOCK_AGENT_IMPORT = "tests.agent.mock:MockAgent"


def _make_config(tmp_path: Path, trial_name: str = "trial") -> TrialConfig:
    return TrialConfig(
        task=TaskConfig(path=str(SAMPLE_TASK_DIR)),
        agent=AgentConfig(name="mock", import_path=MOCK_AGENT_IMPORT),
        trial_name=trial_name,
        trial_dir=tmp_path / trial_name,
    )


def _make_mock_rt():
    """Sync MagicMock mimicking ComposableEnvironment."""
    mock_cap = MagicMock()
    mock_cap.connection_info = {"hostname": "localhost"}
    mock_rt = MagicMock()
    mock_rt.workspace = mock_cap
    return mock_rt


async def test_run_single(tmp_path):
    """One config produces exactly one result."""
    mock_rt = _make_mock_rt()
    with patch("terrarium.execution.trial.ComposableEnvironment", return_value=mock_rt):
        results = await TrialQueue(EventBus(), n_concurrent=1).run([_make_config(tmp_path, "t1")])

    assert len(results) == 1
    assert results[0].exception_info is None
    assert results[0].checker_result.score == 1.0


async def test_run_concurrent(tmp_path):
    """Four configs with n_concurrent=2 all complete and return 4 results."""
    mock_rt = _make_mock_rt()
    configs = [_make_config(tmp_path, f"trial_{i}") for i in range(4)]
    with patch("terrarium.execution.trial.ComposableEnvironment", return_value=mock_rt):
        results = await TrialQueue(EventBus(), n_concurrent=2).run(configs)

    assert len(results) == 4
    assert all(r.exception_info is None for r in results)


async def test_retry_succeeds_on_second_attempt(tmp_path):
    """A trial that fails once is retried and returns the successful result."""
    call_count = 0

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
        results = await TrialQueue(EventBus(), n_concurrent=1, retry_config=retry).run([_make_config(tmp_path)])

    assert len(results) == 1
    assert results[0].exception_info is None
    assert call_count == 2


async def test_no_retry_on_max_retries_zero(tmp_path):
    """With max_retries=0, a failing trial is returned as-is (with exception_info)."""
    mock_rt = MagicMock()
    mock_rt.start = MagicMock(side_effect=RuntimeError("boom"))
    mock_rt.stop = MagicMock()

    retry = RetryConfig(max_retries=0)
    with patch("terrarium.execution.trial.ComposableEnvironment", return_value=mock_rt):
        results = await TrialQueue(EventBus(), n_concurrent=1, retry_config=retry).run([_make_config(tmp_path)])

    assert len(results) == 1
    assert results[0].exception_info is not None
    assert results[0].exception_info.exception_type == "RuntimeError"


async def test_success_event_sequence(tmp_path):
    """Successful trial emits QUEUED -> STARTED -> SUCCEEDED."""
    bus = EventBus()
    events: list[tuple[TrialEvent, str]] = []
    for evt in TrialEvent:
        bus.subscribe(evt, lambda p, e=evt: events.append((e, p.trial_name)))

    mock_rt = _make_mock_rt()
    with patch("terrarium.execution.trial.ComposableEnvironment", return_value=mock_rt):
        await TrialQueue(bus, n_concurrent=1).run([_make_config(tmp_path, "t1")])

    assert events == [
        (TrialEvent.QUEUED, "t1"),
        (TrialEvent.STARTED, "t1"),
        (TrialEvent.SUCCEEDED, "t1"),
    ]


async def test_retry_emits_extra_queued_started_pair(tmp_path):
    """A retried trial emits an additional QUEUED -> STARTED between attempts."""
    bus = EventBus()
    sequence: list[TrialEvent] = []
    for evt in TrialEvent:
        bus.subscribe(evt, lambda p, e=evt: sequence.append(e))

    call_count = 0

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
        await TrialQueue(bus, n_concurrent=1, retry_config=retry).run([_make_config(tmp_path, "t1")])

    assert sequence == [
        TrialEvent.QUEUED,
        TrialEvent.STARTED,
        TrialEvent.QUEUED,
        TrialEvent.STARTED,
        TrialEvent.SUCCEEDED,
    ]


async def test_terminal_failure_emits_failed_with_exception(tmp_path):
    """When all retries are exhausted, FAILED payload carries the exception."""
    bus = EventBus()
    failed_payloads: list[TrialEventPayload] = []
    bus.subscribe(TrialEvent.FAILED, failed_payloads.append)

    mock_rt = MagicMock()
    mock_rt.start = MagicMock(side_effect=RuntimeError("boom"))
    mock_rt.stop = MagicMock()

    retry = RetryConfig(max_retries=0)
    with patch("terrarium.execution.trial.ComposableEnvironment", return_value=mock_rt):
        await TrialQueue(bus, n_concurrent=1, retry_config=retry).run([_make_config(tmp_path, "t1")])

    assert len(failed_payloads) == 1
    assert failed_payloads[0].payload.exception.exception_type == "RuntimeError"
    assert failed_payloads[0].payload.result.exception_info is not None


async def test_succeeded_payload_carries_result(tmp_path):
    """SUCCEEDED payload includes the final TrialResult."""
    bus = EventBus()
    payloads: list[TrialEventPayload] = []
    bus.subscribe(TrialEvent.SUCCEEDED, payloads.append)

    mock_rt = _make_mock_rt()
    with patch("terrarium.execution.trial.ComposableEnvironment", return_value=mock_rt):
        await TrialQueue(bus, n_concurrent=1).run([_make_config(tmp_path, "t1")])

    assert len(payloads) == 1
    assert payloads[0].trial_name == "t1"
    assert payloads[0].payload.result.trial_name == "t1"
    assert payloads[0].payload.result.exception_info is None
