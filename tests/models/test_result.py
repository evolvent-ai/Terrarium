"""Tests for result layer models."""
from datetime import datetime, timezone
from uuid import UUID

import pytest

from terrarium.models.checker import Check, CheckerResults
from terrarium.models.result import TaskInfo
from terrarium.models.trajectory import Message, Trajectory
from terrarium.models.result import (
    ActResult,
    AgentDatasetStats,
    AgentInfo,
    ExceptionInfo,
    JobResult,
    JobStats,
    TimingInfo,
    TrialResult,
)


def _now():
    return datetime.now(tz=timezone.utc)


def _make_trajectory():
    return Trajectory(messages=[Message(role="user", content="hi")])


def _make_checker_result():
    return CheckerResults(checks=[Check(name="ok", passed=True)], score=1.0)


def _make_trial_result(**kwargs):
    defaults = dict(
        trial_name="t1",
        task_info=TaskInfo(path="/tmp/task_a", name="task_a"),
        agent_info=AgentInfo(name="agent_x"),
        checker_result=_make_checker_result(),
        trajectory=_make_trajectory(),
        started_at=_now(),
        finished_at=_now(),
    )
    defaults.update(kwargs)
    return TrialResult(**defaults)


class TestAgentInfo:
    def test_create_minimal(self):
        info = AgentInfo(name="my_agent")
        assert info.name == "my_agent"
        assert info.version is None
        assert info.model_name is None

    def test_create_full(self):
        info = AgentInfo(name="gpt_agent", version="1.2.3", model_name="gpt-4o")
        assert info.version == "1.2.3"
        assert info.model_name == "gpt-4o"


class TestExceptionInfo:
    def test_from_exception(self):
        try:
            raise ValueError("something went wrong")
        except ValueError as e:
            info = ExceptionInfo.from_exception(e)

        assert info.exception_type == "ValueError"
        assert info.exception_message == "something went wrong"
        assert "ValueError" in info.exception_traceback

    def test_from_base_exception(self):
        try:
            raise RuntimeError("oops")
        except RuntimeError as e:
            info = ExceptionInfo.from_exception(e)
        assert info.exception_type == "RuntimeError"


class TestActResult:
    def test_defaults(self):
        r = ActResult()
        assert r.messages == []
        assert r.input_tokens == 0
        assert r.output_tokens == 0
        assert r.cache_read_tokens == 0
        assert r.cache_creation_tokens == 0

    def test_with_data(self):
        msgs = [Message(role="assistant", content="hello")]
        r = ActResult(
            messages=msgs,
            input_tokens=100,
            output_tokens=50,
            cache_read_tokens=10,
            cache_creation_tokens=5,
        )
        assert len(r.messages) == 1
        assert r.input_tokens == 100
        assert r.output_tokens == 50


class TestTimingInfo:
    def test_defaults(self):
        t = TimingInfo()
        assert t.started_at is None
        assert t.finished_at is None

    def test_with_times(self):
        now = _now()
        t = TimingInfo(started_at=now, finished_at=now)
        assert t.started_at == now


class TestTrialResult:
    def test_create_with_auto_uuid(self):
        tr = _make_trial_result()
        assert isinstance(tr.id, UUID)
        assert tr.trial_name == "t1"
        assert tr.task_info.name == "task_a"
        assert tr.exception_info is None
        assert tr.setup_timing.started_at is None
        assert tr.execution_timing.started_at is None

    def test_unique_uuids(self):
        tr1 = _make_trial_result()
        tr2 = _make_trial_result()
        assert tr1.id != tr2.id

    def test_with_exception_info(self):
        try:
            raise KeyError("missing")
        except KeyError as e:
            exc = ExceptionInfo.from_exception(e)
        tr = _make_trial_result(exception_info=exc)
        assert tr.exception_info.exception_type == "KeyError"

    def test_serialization(self):
        tr = _make_trial_result()
        data = tr.model_dump()
        assert "id" in data
        assert data["trial_name"] == "t1"
        assert data["checker_result"]["score"] == 1.0
        assert isinstance(data["id"], UUID)

    def test_json_round_trip(self):
        tr = _make_trial_result()
        json_str = tr.model_dump_json()
        tr2 = TrialResult.model_validate_json(json_str)
        assert tr2.id == tr.id
        assert tr2.trial_name == tr.trial_name


class TestJobResult:
    def test_create(self):
        tr = _make_trial_result()
        stats = JobStats(n_trials=1)
        jr = JobResult(
            trial_results=[tr],
            stats=stats,
        )
        assert isinstance(jr.id, UUID)
        assert jr.stats.n_trials == 1
        assert len(jr.trial_results) == 1

    def test_serialization(self):
        jr = JobResult(
            trial_results=[_make_trial_result()],
            stats=JobStats(),
        )
        data = jr.model_dump()
        assert "id" in data
        assert "trial_results" not in data


class TestAgentDatasetStats:
    def test_defaults(self):
        s = AgentDatasetStats()
        assert s.n_trials == 0
        assert s.n_errors == 0
        assert s.metrics == {}
        assert s.score_stats == {}
        assert s.exception_stats == {}
