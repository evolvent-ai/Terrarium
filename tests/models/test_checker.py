"""Tests for checker models."""
from terrarium.models.checker import Check, CheckerResults


class TestCheck:
    def test_create_passed(self):
        check = Check(name="length_ok", passed=True)
        assert check.name == "length_ok"
        assert check.passed is True

    def test_create_failed(self):
        check = Check(name="format_valid", passed=False)
        assert check.name == "format_valid"
        assert check.passed is False


class TestCheckerResults:
    def test_create(self):
        checks = [Check(name="a", passed=True), Check(name="b", passed=False)]
        result = CheckerResults(checks=checks, score=0.5)
        assert len(result.checks) == 2
        assert result.score == 0.5

    def test_serialization(self):
        checks = [Check(name="c", passed=True)]
        result = CheckerResults(checks=checks, score=1.0)
        data = result.model_dump()
        assert data["score"] == 1.0
        assert data["checks"][0]["name"] == "c"
        assert data["checks"][0]["passed"] is True

    def test_round_trip(self):
        checks = [Check(name="x", passed=False)]
        result = CheckerResults(checks=checks, score=0.0)
        restored = CheckerResults.model_validate(result.model_dump())
        assert restored.score == 0.0
        assert restored.checks[0].name == "x"
