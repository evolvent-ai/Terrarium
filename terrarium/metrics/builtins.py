"""Built-in aggregation metrics."""
from __future__ import annotations

from collections import defaultdict
from math import comb

from terrarium.metrics.base import BaseMetric
from terrarium.models.result import TrialResult


def _extract_scores(results: list[TrialResult]) -> list[float]:
    return [r.checker_result.score if r.exception_info is None else 0.0 for r in results]


class Mean(BaseMetric):
    @property
    def name(self) -> str:
        return "mean"

    def compute(self, results: list[TrialResult]) -> float:
        s = _extract_scores(results)
        return sum(s) / len(s) if s else 0.0


class Max(BaseMetric):
    @property
    def name(self) -> str:
        return "max"

    def compute(self, results: list[TrialResult]) -> float:
        s = _extract_scores(results)
        return max(s) if s else 0.0


class Min(BaseMetric):
    @property
    def name(self) -> str:
        return "min"

    def compute(self, results: list[TrialResult]) -> float:
        s = _extract_scores(results)
        return min(s) if s else 0.0


class Sum(BaseMetric):
    @property
    def name(self) -> str:
        return "sum"

    def compute(self, results: list[TrialResult]) -> float:
        s = _extract_scores(results)
        return sum(s)


class PassAtK(BaseMetric):
    """pass@k: probability that at least one of k random picks passes.

    Groups results by task, computes per-task pass@k, then averages.
    Formula: pass@k = 1 - C(n-c, k) / C(n, k)
    """

    def __init__(self, k: int | None = None) -> None:
        if k is None:
            raise ValueError("pass@k requires k, e.g. 'pass@1', 'pass@5'")
        self._k = k

    @property
    def name(self) -> str:
        return f"pass@{self._k}"

    def compute(self, results: list[TrialResult]) -> float:
        if not results:
            return 0.0

        by_task: dict[str, list[TrialResult]] = defaultdict(list)
        for r in results:
            by_task[r.task_info.name].append(r)

        task_scores: list[float] = []
        for task_results in by_task.values():
            n = len(task_results)
            k = min(self._k, n)
            c = sum(
                1 for r in task_results
                if r.exception_info is None and r.checker_result.score >= 1.0
            )
            task_scores.append(1.0 - comb(n - c, k) / comb(n, k))

        return sum(task_scores) / len(task_scores)
