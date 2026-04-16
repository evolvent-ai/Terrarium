"""Tests for parameterized task loading."""
from __future__ import annotations
from pathlib import Path

from terrarium.task.task import Task
from terrarium.dataset.dataset import Dataset

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
PARAM_TASK_DIR = FIXTURES_DIR / "parameterized_task"
PARAM_CAPS_TASK_DIR = FIXTURES_DIR / "parameterized_caps_task"


def test_load_non_parameterized():
    """Task.resolve() returns a single-element list for normal tasks."""
    tasks = Task.resolve(FIXTURES_DIR / "sample_task")
    assert len(tasks) == 1
    assert tasks[0].name == "sample_task"


def test_load_parameterized_count():
    """Task.resolve() expands parameterized task into correct number of instances."""
    tasks = Task.resolve(PARAM_TASK_DIR)
    assert len(tasks) == 3


def test_load_parameterized_names():
    """Each parameterized instance has the correct name."""
    tasks = Task.resolve(PARAM_TASK_DIR)
    names = [t.name for t in tasks]
    assert names == ["param_task_0", "param_task_1", "param_task_2"]


def test_load_parameterized_capabilities_default():
    """Parameterized instances use @entry capabilities when not overridden."""
    tasks = Task.resolve(PARAM_TASK_DIR)
    for t in tasks:
        assert t.capabilities == ["workspace"]


def test_load_parameterized_capabilities_override():
    """Parameterized instances can override capabilities per-instance."""
    tasks = Task.resolve(PARAM_CAPS_TASK_DIR)
    basic = next(t for t in tasks if t.name == "basic")
    with_db = next(t for t in tasks if t.name == "with_db")

    assert basic.capabilities == ["workspace"]
    assert with_db.capabilities == ["workspace", "postgres"]


def test_load_parameterized_entry_fn():
    """Parameterized entry_fn is callable with (env, agent) and injects params."""
    tasks = Task.resolve(PARAM_TASK_DIR)
    result = tasks[1].entry_fn(None, None)
    assert result.score == 1.0
    assert result.checks[0].name == "check_item_1"


def test_load_parameterized_dir():
    """All parameterized instances share the same dir."""
    tasks = Task.resolve(PARAM_TASK_DIR)
    for t in tasks:
        assert t.dir == PARAM_TASK_DIR


def test_load_parameterized_metadata():
    """Parameterized instances share the same metadata from task.toml."""
    tasks = Task.resolve(PARAM_TASK_DIR)
    for t in tasks:
        assert t.metadata.author == "test"


def test_dataset_discovers_parameterized(tmp_path):
    """Dataset._discover_tasks expands parameterized tasks."""
    task_dir = tmp_path / "ptask"
    task_dir.mkdir()
    (task_dir / "task.toml").write_text('[metadata]\nname = "ptask"\n')
    (task_dir / "task.py").write_text(
        "from terrarium.task.decorator import entry\n"
        "from terrarium.task.checking import run_checkers\n"
        "\n"
        "@entry(capabilities=[])\n"
        "def task(env, agent, *, idx: int):\n"
        "    return run_checkers({'ok': lambda: True})\n"
        "\n"
        "@task.parameterize\n"
        "def params():\n"
        "    for i in range(5):\n"
        "        yield {'name': f'task_{i}', 'params': {'idx': i}}\n"
    )

    ds = Dataset(tmp_path)
    assert len(ds.tasks) == 5
    assert [t.name for t in ds.tasks] == [f"task_{i}" for i in range(5)]


def test_dataset_mixed_tasks(tmp_path):
    """Dataset with both normal and parameterized tasks works correctly."""
    normal_dir = tmp_path / "normal"
    normal_dir.mkdir()
    (normal_dir / "task.py").write_text(
        "from terrarium.task.decorator import entry\n"
        "@entry(capabilities=[])\n"
        "def task(env, agent): pass\n"
    )
    (normal_dir / "task.toml").write_text('[metadata]\nname = "normal_task"\n')

    param_dir = tmp_path / "param"
    param_dir.mkdir()
    (param_dir / "task.py").write_text(
        "from terrarium.task.decorator import entry\n"
        "from terrarium.task.checking import run_checkers\n"
        "\n"
        "@entry(capabilities=[])\n"
        "def task(env, agent, *, idx: int):\n"
        "    return run_checkers({'ok': lambda: True})\n"
        "\n"
        "@task.parameterize\n"
        "def params():\n"
        "    yield {'name': 'p_0', 'params': {'idx': 0}}\n"
        "    yield {'name': 'p_1', 'params': {'idx': 1}}\n"
    )

    ds = Dataset(tmp_path)
    assert len(ds.tasks) == 3
    names = [t.name for t in ds.tasks]
    assert "normal_task" in names
    assert "p_0" in names
    assert "p_1" in names
