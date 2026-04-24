"""Capability implementations and registry."""

from __future__ import annotations

import importlib

from terrarium.environment.capability import BaseCapability

from terrarium.environment.capabilities.postgres import PostgresCapability
from terrarium.environment.capabilities.email import EmailCapability
from terrarium.environment.capabilities.calendar import CalendarCapability
from terrarium.environment.capabilities.notion import NotionCapability
from terrarium.environment.capabilities.google_sheets import GoogleSheetsCapability
from terrarium.environment.capabilities.workspace import WorkspaceCapability

_REGISTRY: dict[str, type[BaseCapability]] = {
    "postgres": PostgresCapability,
    "email": EmailCapability,
    "calendar": CalendarCapability,
    "notion": NotionCapability,
    "google_sheets": GoogleSheetsCapability,
    "workspace": WorkspaceCapability,
}


def resolve_capability_class(
    name: str, config: dict | None = None,
) -> type[BaseCapability]:
    """Resolve class; `import_path` in config overrides the built-in registry."""
    import_path = (config or {}).get("import_path", None)

    if import_path:
        module_path, class_name = import_path.rsplit(":", 1)
        module = importlib.import_module(module_path)
        capability_cls = getattr(module, class_name)
    elif name in _REGISTRY:
        capability_cls = _REGISTRY[name]
    else:
        raise ValueError(
            f"Capability '{name}' not found. "
            f"Set import_path or use a built-in: {list(_REGISTRY.keys())}"
        )

    if not issubclass(capability_cls, BaseCapability):
        raise TypeError(f"{capability_cls!r} is not a BaseCapability subclass")
    return capability_cls