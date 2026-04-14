"""Checker execution utilities."""
from __future__ import annotations
from loguru import logger
from terrarium.models.checker import Check, CheckerResults
from terrarium.models.common import ExceptionInfo


def run_checkers(checkers: dict[str, callable], tags: list[str] | None = None) -> CheckerResults:
    """Run a batch of checkers and return a CheckerResults."""
    check_tags = tags or []
    checks = []
    for name, predicate in checkers.items():
        try:
            passed = bool(predicate())
            checks.append(Check(name=name, passed=passed, tags=check_tags))
        except Exception as e:
            logger.warning("Checker '{}' raised exception: {}", name, e)
            checks.append(Check(name=name, passed=False, exception=ExceptionInfo.from_exception(e), tags=check_tags))
    n_passed = sum(1 for c in checks if c.passed)
    score = n_passed / len(checks) if checks else 0.0
    return CheckerResults(checks=checks, score=score)


def aggregate_results(*results: CheckerResults) -> CheckerResults:
    """Merge multiple CheckerResultss. score = passed / total."""
    all_checks = []
    for r in results:
        all_checks.extend(r.checks)
    n_passed = sum(1 for c in all_checks if c.passed)
    score = n_passed / len(all_checks) if all_checks else 0.0
    return CheckerResults(checks=all_checks, score=score)
