"""Tests for run_checkers and aggregate_results."""
from __future__ import annotations
import pytest
from terrarium.task.checking import run_checkers, aggregate_results
from terrarium.models.checker import Check, CheckerResults


def test_all_pass():
    """All checkers pass -> score == 1.0."""
    result = run_checkers({
        "check_a": lambda: True,
        "check_b": lambda: True,
    })
    assert result.score == 1.0
    assert all(c.passed for c in result.checks)
    assert len(result.checks) == 2


def test_some_fail():
    """Half checkers pass -> score == 0.5."""
    result = run_checkers({
        "check_pass": lambda: True,
        "check_fail": lambda: False,
    })
    assert result.score == 0.5
    passed = {c.name: c.passed for c in result.checks}
    assert passed["check_pass"] is True
    assert passed["check_fail"] is False


def test_exception_counts_as_fail():
    """Checker that raises an exception is treated as failed."""
    result = run_checkers({
        "check_ok": lambda: True,
        "check_boom": lambda: 1 / 0,
    })
    passed = {c.name: c.passed for c in result.checks}
    assert passed["check_ok"] is True
    assert passed["check_boom"] is False
    assert result.score == 0.5


def test_empty():
    """Empty checkers dict returns score 0.0 and empty checks."""
    result = run_checkers({})
    assert result.score == 0.0
    assert result.checks == []


def test_aggregate_merge():
    """aggregate_results merges checks and recomputes score."""
    r1 = CheckerResults(
        checks=[Check(name="a", passed=True), Check(name="b", passed=False)],
        score=0.5,
    )
    r2 = CheckerResults(
        checks=[Check(name="c", passed=True), Check(name="d", passed=True)],
        score=1.0,
    )
    merged = aggregate_results(r1, r2)
    assert len(merged.checks) == 4
    assert merged.score == pytest.approx(0.75)


def test_aggregate_empty():
    """aggregate_results with no arguments returns score 0.0."""
    merged = aggregate_results()
    assert merged.score == 0.0
    assert merged.checks == []


# ── Tags ────────────────────────────────────────────────────


def test_run_checkers_with_tags():
    """Tags passed to run_checkers are attached to every check."""
    result = run_checkers({"a": lambda: True, "b": lambda: False}, tags=["stage1", "db"])
    assert all(c.tags == ["stage1", "db"] for c in result.checks)


def test_run_checkers_without_tags():
    """Without tags, checks have empty tags list."""
    result = run_checkers({"a": lambda: True})
    assert result.checks[0].tags == []


def test_by_tag():
    """by_tag filters checks and recomputes score."""
    r1 = run_checkers({"a": lambda: True}, tags=["stage1"])
    r2 = run_checkers({"b": lambda: True, "c": lambda: False}, tags=["stage2"])
    merged = aggregate_results(r1, r2)

    s1 = merged.by_tag("stage1")
    assert len(s1.checks) == 1
    assert s1.score == 1.0

    s2 = merged.by_tag("stage2")
    assert len(s2.checks) == 2
    assert s2.score == 0.5


def test_by_tag_no_match():
    """by_tag with non-existent tag returns empty results with score 0."""
    result = run_checkers({"a": lambda: True}, tags=["stage1"])
    empty = result.by_tag("nonexistent")
    assert empty.checks == []
    assert empty.score == 0.0


def test_all_tags():
    """all_tags returns the union of all tags."""
    r1 = run_checkers({"a": lambda: True}, tags=["stage1", "db"])
    r2 = run_checkers({"b": lambda: True}, tags=["stage2", "db"])
    merged = aggregate_results(r1, r2)
    assert merged.all_tags() == {"stage1", "stage2", "db"}


def test_all_tags_empty():
    """all_tags returns empty set when no tags."""
    result = run_checkers({"a": lambda: True})
    assert result.all_tags() == set()


def test_aggregate_preserves_tags():
    """aggregate_results preserves tags from original checks."""
    r1 = run_checkers({"a": lambda: True}, tags=["s1"])
    r2 = run_checkers({"b": lambda: False}, tags=["s2"])
    merged = aggregate_results(r1, r2)
    assert merged.checks[0].tags == ["s1"]
    assert merged.checks[1].tags == ["s2"]
