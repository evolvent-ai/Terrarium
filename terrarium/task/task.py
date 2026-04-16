"""Task object — wraps a task directory."""
from __future__ import annotations
import importlib.util
import tomllib
from pathlib import Path
from typing import Any, Callable

from terrarium.models.spec import TaskMetadata, TaskSpec


class Task:
    """Wraps a task directory. Loads task.py, extracts @entry, parses task.toml."""

    def __init__(
        self,
        task_dir: str | Path,
        *,
        _entry_fn: Callable | None = None,
        _capabilities: list[str] | None = None,
        _name: str | None = None,
    ):
        self._dir = Path(task_dir)
        if not self._dir.exists():
            raise FileNotFoundError(f"Task directory not found: {self._dir}")
        self._spec = self._load_spec()
        self._name_override = _name

        if _entry_fn is not None:
            self._entry_fn = _entry_fn
            self._capabilities = _capabilities or []
        else:
            self._entry_fn: Callable | None = None
            self._capabilities: list[str] = []
            self._load_entry()

    @classmethod
    def load(cls, task_dir: str | Path) -> list[Task]:
        """Load a task directory. Returns multiple Tasks if parameterized."""
        task_dir = Path(task_dir)
        raw_fn, default_caps = cls._load_entry_from_file(task_dir / "task.py")

        gen_fn = getattr(raw_fn, "_terrarium_parameterize", None)
        if gen_fn is None:
            return [cls(task_dir)]

        def _make_entry(fn: Callable, kw: dict[str, Any]) -> Callable:
            def entry_fn(env, agent):
                return fn(env, agent, **kw)
            return entry_fn

        tasks = []
        for p in gen_fn():
            params = p.get("params", {})
            caps = p.get("capabilities", default_caps)
            tasks.append(cls(
                task_dir,
                _entry_fn=_make_entry(raw_fn, params),
                _capabilities=caps,
                _name=p["name"],
            ))
        return tasks

    @staticmethod
    def _load_entry_from_file(task_file: Path) -> tuple[Callable, list[str]]:
        """Load a task.py and return (entry_fn, capabilities)."""
        if not task_file.exists():
            raise FileNotFoundError(f"task.py not found: {task_file}")
        spec = importlib.util.spec_from_file_location("_", task_file)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for attr in vars(module).values():
            if callable(attr) and getattr(attr, "_terrarium_entry", False):
                return attr, getattr(attr, "_terrarium_capabilities", [])
        raise ValueError(f"No @entry decorated function found in {task_file}")

    def _load_spec(self) -> TaskSpec:
        toml_file = self._dir / "task.toml"
        if not toml_file.exists():
            return TaskSpec()
        with open(toml_file, "rb") as f:
            return TaskSpec.model_validate(tomllib.load(f))

    def _load_entry(self) -> None:
        fn, caps = self._load_entry_from_file(self._dir / "task.py")
        self._entry_fn = fn
        self._capabilities = caps

    @property
    def name(self) -> str:
        if self._name_override:
            return self._name_override
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
