"""Tests for the Dataset object."""
from __future__ import annotations
from pathlib import Path
import pytest
from terrarium.dataset.dataset import Dataset
from terrarium.metrics.base import BaseMetric
from terrarium.task.task import Task

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
SAMPLE_DATASET_DIR = FIXTURES_DIR / "sample_dataset"


def test_load():
    """Dataset loads name from dataset.toml."""
    ds = Dataset(SAMPLE_DATASET_DIR)
    assert ds.name == "sample_dataset"


def test_metrics():
    """Dataset exposes metrics as BaseMetric instances."""
    ds = Dataset(SAMPLE_DATASET_DIR)
    assert len(ds.metrics) == 2
    assert all(isinstance(m, BaseMetric) for m in ds.metrics)


def test_tasks():
    """Dataset discovers exactly 2 tasks, cached as property."""
    ds = Dataset(SAMPLE_DATASET_DIR)
    tasks = ds.tasks
    assert len(tasks) == 2
    assert all(isinstance(t, Task) for t in tasks)
    names = [t.name for t in tasks]
    assert names == ["task_a", "task_b"]
    # Verify cached (same object)
    assert ds.tasks is tasks


def test_no_config(tmp_path):
    """Dataset without dataset.toml uses default metrics (mean) and dir name."""
    (tmp_path / "some_task").mkdir()
    (tmp_path / "some_task" / "task.py").write_text(
        "from terrarium.task.decorator import entry\n"
        "@entry(capabilities=[])\ndef fn(env, agent): pass\n"
    )
    ds = Dataset(tmp_path)
    assert ds.name == tmp_path.name
    assert len(ds.metrics) == 1  # default ["mean"]


def test_repr():
    ds = Dataset(SAMPLE_DATASET_DIR)
    assert "sample_dataset" in repr(ds)
    assert "tasks=2" in repr(ds)


def test_nonexistent():
    """Loading a non-existent directory raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError, match="Dataset directory not found"):
        Dataset(FIXTURES_DIR / "does_not_exist")


def test_duplicate_task_names(tmp_path):
    """Duplicate task names in a dataset raises ValueError."""
    task_code = (
        "from terrarium.task.decorator import entry\n"
        "@entry(capabilities=[])\ndef fn(env, agent): pass\n"
    )
    for d in ["dir_a", "dir_b"]:
        task_dir = tmp_path / d
        task_dir.mkdir()
        (task_dir / "task.py").write_text(task_code)
        (task_dir / "task.toml").write_text('[metadata]\nname = "same_name"\n')

    ds = Dataset(tmp_path)
    with pytest.raises(ValueError, match="Duplicate task names"):
        _ = ds.tasks
