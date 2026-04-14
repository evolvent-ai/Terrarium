import io
from loguru import logger
from terrarium.environment.logging import log_capability_call


class FakeCapability:

    @log_capability_call
    def do_something(self, x: int, y: str = "default") -> str:
        return f"{x}-{y}"

    @log_capability_call
    def do_fail(self):
        raise ValueError("boom")


def test_log_capability_call_returns_result():
    cap = FakeCapability()
    result = cap.do_something(42, y="hello")
    assert result == "42-hello"


def test_log_capability_call_logs_success_with_args():
    sink = io.StringIO()
    handler_id = logger.add(sink, format="{message}", level="INFO")
    try:
        cap = FakeCapability()
        cap.do_something(1, y="hello")
        output = sink.getvalue()
        assert "FakeCapability.do_something" in output
        assert "status=ok" in output
        assert "1" in output
        assert "hello" in output
    finally:
        logger.remove(handler_id)


def test_log_capability_call_logs_error():
    sink = io.StringIO()
    handler_id = logger.add(sink, format="{message}", level="INFO")
    try:
        cap = FakeCapability()
        try:
            cap.do_fail()
        except ValueError:
            pass
        output = sink.getvalue()
        assert "FakeCapability.do_fail" in output
        assert "status=error" in output
    finally:
        logger.remove(handler_id)


def test_log_capability_call_reraises():
    import pytest
    cap = FakeCapability()
    with pytest.raises(ValueError, match="boom"):
        cap.do_fail()
