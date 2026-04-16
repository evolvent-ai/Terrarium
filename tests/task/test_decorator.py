"""Tests for the @entry decorator."""
from __future__ import annotations
from terrarium.task.decorator import entry


def test_marks_function():
    """Decorated function has _terrarium_entry and _terrarium_capabilities attributes."""
    @entry(capabilities=["workspace", "browser"])
    def my_task(env, agent):
        pass

    assert my_task._terrarium_entry is True
    assert my_task._terrarium_capabilities == ["workspace", "browser"]


def test_preserves_callable():
    """Decorated function is still callable and returns correctly."""
    @entry(capabilities=[])
    def my_task(env, agent):
        return 42

    assert callable(my_task)
    assert my_task(None, None) == 42


def test_preserves_name():
    """Decorated function preserves __name__ and __doc__."""
    @entry(capabilities=["workspace"])
    def my_task(env, agent):
        """My task docstring."""
        pass

    assert my_task.__name__ == "my_task"
    assert my_task.__doc__ == "My task docstring."


def test_parameterize_default():
    """Decorated function has _terrarium_parameterize set to None by default."""
    @entry(capabilities=[])
    def my_task(env, agent):
        pass

    assert my_task._terrarium_parameterize is None


def test_parameterize_registers_generator():
    """task.parameterize registers the generator function."""
    @entry(capabilities=[])
    def my_task(env, agent, *, x: int):
        pass

    @my_task.parameterize
    def gen():
        yield {"name": "a", "params": {"x": 1}}

    assert my_task._terrarium_parameterize is gen
