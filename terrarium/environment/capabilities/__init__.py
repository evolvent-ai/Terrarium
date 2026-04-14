"""Capability implementations and registry."""

from __future__ import annotations

from typing import TYPE_CHECKING

from terrarium.environment.exceptions import CapabilityNotFoundError

if TYPE_CHECKING:
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


def get_capability_class(name: str) -> type[BaseCapability]:
    """Get capability class by name. Raises CapabilityNotFoundError if not found."""
    if name not in _REGISTRY:
        raise CapabilityNotFoundError(name, list(_REGISTRY.keys()))
    return _REGISTRY[name]


def list_capabilities() -> list[str]:
    """Return all registered capability names."""
    return list(_REGISTRY.keys())
