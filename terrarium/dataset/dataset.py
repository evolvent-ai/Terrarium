"""Dataset object — wraps a dataset directory."""
from __future__ import annotations

import tomllib
from pathlib import Path

from terrarium.metrics.base import BaseMetric
from terrarium.metrics.registry import create_metric
from terrarium.models.spec import DatasetSpec
from terrarium.task.task import Task


class Dataset:
    """Wraps a dataset directory. Loads dataset.toml, discovers tasks."""

    def __init__(self, dataset_dir: str | Path):
        self._dir = Path(dataset_dir)
        if not self._dir.exists():
            raise FileNotFoundError(f"Dataset directory not found: {self._dir}")
        self._spec = self._load_spec()
        self._tasks: list[Task] | None = None
        self._metrics: list[BaseMetric] | None = None

    def _load_spec(self) -> DatasetSpec:
        toml_file = self._dir / "dataset.toml"
        if not toml_file.exists():
            return DatasetSpec()
        with open(toml_file, "rb") as f:
            return DatasetSpec.model_validate(tomllib.load(f))

    @property
    def name(self) -> str:
        return self._spec.metadata.name or self._dir.name

    @property
    def dir(self) -> Path:
        return self._dir

    @property
    def tasks(self) -> list[Task]:
        if self._tasks is None:
            tasks = self._discover_tasks(self._dir)
            names = [t.name for t in tasks]
            if len(names) != len(set(names)):
                dupes = {n for n in names if names.count(n) > 1}
                raise ValueError(f"Duplicate task names in dataset '{self.name}': {dupes}")
            self._tasks = tasks
        return self._tasks

    def _discover_tasks(self, directory: Path) -> list[Task]:
        """Recursively discover tasks in subdirectories."""
        tasks = []
        for child in sorted(directory.iterdir()):
            if not child.is_dir():
                continue
            try:
                tasks.extend(Task.load(child))
            except Exception:
                tasks.extend(self._discover_tasks(child))
        return tasks

    @property
    def metrics(self) -> list[BaseMetric]:
        if self._metrics is None:
            self._metrics = [create_metric(n) for n in self._spec.metrics.types]
        return self._metrics

    def __repr__(self) -> str:
        return f"Dataset(name={self.name!r}, tasks={len(self.tasks)})"
