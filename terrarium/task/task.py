"""Task object — wraps a task directory."""
from __future__ import annotations
import importlib.util
import tomllib
from pathlib import Path
from typing import Callable

from terrarium.models.spec import TaskMetadata, TaskSpec


class Task:
    """Wraps a task directory. Loads task.py, extracts @entry, parses task.toml."""

    def __init__(self, task_dir: str | Path):
        self._dir = Path(task_dir)
        if not self._dir.exists():
            raise FileNotFoundError(f"Task directory not found: {self._dir}")
        self._spec = self._load_spec()
        self._entry_fn: Callable | None = None
        self._capabilities: list[str] = []
        self._load_entry()

    def _load_spec(self) -> TaskSpec:
        toml_file = self._dir / "task.toml"
        if not toml_file.exists():
            return TaskSpec()
        with open(toml_file, "rb") as f:
            return TaskSpec.model_validate(tomllib.load(f))

    def _load_entry(self) -> None:
        task_file = self._dir / "task.py"
        if not task_file.exists():
            raise FileNotFoundError(f"task.py not found in {self._dir}")

        spec = importlib.util.spec_from_file_location("_", task_file)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        for attr in vars(module).values():
            if callable(attr) and getattr(attr, "_terrarium_entry", False):
                self._entry_fn = attr
                self._capabilities = getattr(attr, "_terrarium_capabilities", [])
                break

        if self._entry_fn is None:
            raise ValueError(f"No @entry decorated function found in {task_file}")

    @property
    def name(self) -> str:
        return self._spec.metadata.name or self._dir.name

    @property
    def dir(self) -> Path:
        return self._dir

    @property
    def capabilities(self) -> list[str]:
        return self._capabilities

    @property
    def metadata(self) -> TaskMetadata:
        return self._spec.metadata

    @property
    def entry_fn(self) -> Callable:
        return self._entry_fn

    def __repr__(self) -> str:
        return f"Task(name={self.name!r}, capabilities={self.capabilities})"
