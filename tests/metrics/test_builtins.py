"""Tests for built-in metrics."""
import pytest
from terrarium.metrics.builtins import Mean, Max, Min, Sum, PassAtK
from terrarium.models.checker import CheckerResults
from terrarium.models.common import ExceptionInfo
from terrarium.models.result import AgentInfo, TaskInfo, TrialResult
from terrarium.models.trajectory import Trajectory


def _trial(score: float, task_name: str = "task_a", exception: bool = False) -> TrialResult:
    return TrialResult(
        trial_name="t",
        task_info=TaskInfo(path="/tmp/t", name=task_name),
        agent_info=AgentInfo(name="agent"),
        checker_result=CheckerResults(checks=[], score=score),
        trajectory=Trajectory(messages=[]),
        exception_info=ExceptionInfo(
            exception_type="RuntimeError", exception_message="err", exception_traceback=""
        ) if exception else None,
    )


# --- Mean ---

def test_mean_basic():
    results = [_trial(0.5), _trial(1.0), _trial(0.0)]
    assert Mean().name == "mean"
    assert Mean().compute(results) == pytest.approx(0.5)


def test_mean_empty():
    assert Mean().compute([]) == 0.0


def test_mean_with_exception():
    results = [_trial(1.0), _trial(0.0, exception=True), _trial(0.5)]
    assert Mean().compute(results) == pytest.approx(0.5)


# --- Max ---

def test_max_basic():
    results = [_trial(0.2), _trial(0.9), _trial(0.4)]
    assert Max().name == "max"
    assert Max().compute(results) == pytest.approx(0.9)


def test_max_empty():
    assert Max().compute([]) == 0.0


# --- Min ---

def test_min_basic():
    results = [_trial(0.2), _trial(0.9), _trial(0.4)]
    assert Min().name == "min"
    assert Min().compute(results) == pytest.approx(0.2)


def test_min_empty():
    assert Min().compute([]) == 0.0


# --- Sum ---

def test_sum_basic():
    results = [_trial(0.3), _trial(0.7), _trial(1.0)]
    assert Sum().name == "sum"
    assert Sum().compute(results) == pytest.approx(2.0)


# --- PassAtK ---

class TestPassAtK:
    def test_name(self):
        assert PassAtK(k=1).name == "pass@1"
        assert PassAtK(k=5).name == "pass@5"

    def test_all_pass(self):
        results = [_trial(1.0) for _ in range(3)]
        assert PassAtK(k=1).compute(results) == pytest.approx(1.0)

    def test_none_pass(self):
        results = [_trial(0.0) for _ in range(3)]
        assert PassAtK(k=1).compute(results) == pytest.approx(0.0)

    def test_partial_pass(self):
        # n=3, c=1, k=1: pass@1 = 1 - C(2,1)/C(3,1) = 1 - 2/3 = 1/3
        results = [_trial(1.0), _trial(0.0), _trial(0.0)]
        assert PassAtK(k=1).compute(results) == pytest.approx(1 / 3)

    def test_k_equals_n(self):
        # n=3, c=1, k=3: pick all 3 -> always includes the 1 correct
        results = [_trial(1.0), _trial(0.0), _trial(0.0)]
        assert PassAtK(k=3).compute(results) == pytest.approx(1.0)

    def test_multi_task_average(self):
        # Task A: n=2, c=2 -> pass@1 = 1.0
        # Task B: n=2, c=0 -> pass@1 = 0.0
        results = [
            _trial(1.0, "task_a"), _trial(1.0, "task_a"),
            _trial(0.0, "task_b"), _trial(0.0, "task_b"),
        ]
        assert PassAtK(k=1).compute(results) == pytest.approx(0.5)

    def test_k_capped_at_n(self):
        # k=10 but only n=2: cap to k=2, c=1 -> pass@2 = 1.0
        results = [_trial(1.0), _trial(0.0)]
        assert PassAtK(k=10).compute(results) == pytest.approx(1.0)

    def test_empty(self):
        assert PassAtK(k=1).compute([]) == pytest.approx(0.0)

    def test_exception_counts_as_failure(self):
        results = [_trial(1.0, exception=True), _trial(0.0)]
        # n=2, c=0 -> pass@1 = 0.0
        assert PassAtK(k=1).compute(results) == pytest.approx(0.0)

    def test_partial_score_not_pass(self):
        # score=0.8 is NOT a pass (threshold is 1.0)
        results = [_trial(0.8), _trial(0.8)]
        assert PassAtK(k=1).compute(results) == pytest.approx(0.0)
