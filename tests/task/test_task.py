"""Tests for the Task object."""
from __future__ import annotations
from pathlib import Path
import pytest
from terrarium.task.task import Task

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
SAMPLE_TASK_DIR = FIXTURES_DIR / "sample_task"


def test_load():
    """Task loads name, capabilities, and a callable entry_fn."""
    task = Task(SAMPLE_TASK_DIR)
    assert task.name == "sample_task"
    assert task.capabilities == []
    assert task.capabilities_config == {}
    assert callable(task.entry_fn)


def test_capabilities_config_from_entry(tmp_path):
    """Task.capabilities_config reflects the value passed to @entry."""
    (tmp_path / "task.py").write_text(
        "from terrarium.task.decorator import entry\n"
        "from terrarium.task.checking import run_checkers\n"
        "\n"
        "@entry(capabilities=['postgres'],\n"
        "       capabilities_config={'postgres': {'db_name': 'x'}})\n"
        "def task(env, agent):\n"
        "    return run_checkers({'ok': lambda: True})\n"
    )
    task = Task(tmp_path)
    assert task.capabilities_config == {"postgres": {"db_name": "x"}}


def test_metadata():
    """Task exposes parsed metadata from task.toml."""
    task = Task(SAMPLE_TASK_DIR)
    assert task.metadata.author == "test"
    assert task.metadata.difficulty == "easy"
    assert task.metadata.category == "test"
    assert task.metadata.description == "A sample task for testing"


def test_nonexistent_dir():
    """Loading a non-existent directory raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError, match="Task directory not found"):
        Task(FIXTURES_DIR / "does_not_exist")


def test_no_entry(tmp_path):
    """A task.py with no @entry function raises ValueError."""
    task_py = tmp_path / "task.py"
    task_py.write_text("# no entry here\ndef plain_function(): pass\n")
    with pytest.raises(ValueError, match="No @entry decorated function found"):
        Task(tmp_path)
