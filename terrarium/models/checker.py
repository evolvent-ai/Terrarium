"""Checker result models."""
from __future__ import annotations
from pydantic import BaseModel
from terrarium.models.common import ExceptionInfo


class Check(BaseModel):
    """A single check result."""
    name: str
    passed: bool
    exception: ExceptionInfo | None = None
    tags: list[str] = []


class CheckerResults(BaseModel):
    """Batch checker result with aggregated score."""
    checks: list[Check]
    score: float

    def by_tag(self, tag: str) -> CheckerResults:
        """Filter checks by tag and recompute score."""
        filtered = [c for c in self.checks if tag in c.tags]
        n_passed = sum(1 for c in filtered if c.passed)
        score = n_passed / len(filtered) if filtered else 0.0
        return CheckerResults(checks=filtered, score=score)

    def all_tags(self) -> set[str]:
        """Return all unique tags across checks."""
        return {t for c in self.checks for t in c.tags}
