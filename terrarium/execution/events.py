"""Event bus for trial and job lifecycle events."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from loguru import logger
from pydantic import BaseModel, Field

from terrarium.models.common import ExceptionInfo
from terrarium.models.result import TrialResult


class TrialEvent(str, Enum):
    """Lifecycle events for a single trial."""
    QUEUED = "queued"
    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class JobEvent(str, Enum):
    """Lifecycle events for a job run."""
    STARTED = "started"
    FINISHED = "finished"


class TrialQueuedPayload(BaseModel):
    pass


class TrialStartedPayload(BaseModel):
    pass


class TrialSucceededPayload(BaseModel):
    result: TrialResult


class TrialFailedPayload(BaseModel):
    result: TrialResult
    exception: ExceptionInfo


class TrialEventPayload(BaseModel):
    event: TrialEvent
    trial_name: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    payload: TrialQueuedPayload | TrialStartedPayload | TrialSucceededPayload | TrialFailedPayload


class JobEventPayload(BaseModel):
    event: JobEvent
    job_name: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class EventBus:
    """Synchronous publish/subscribe."""

    def __init__(self) -> None:
        self._handlers: dict[TrialEvent | JobEvent, list[Callable[[Any], None]]] = defaultdict(list)

    def subscribe(
        self,
        event: TrialEvent | JobEvent,
        handler: Callable[[Any], None],
    ) -> Callable[[], None]:
        self._handlers[event].append(handler)

        def unsubscribe() -> None:
            try:
                self._handlers[event].remove(handler)
            except ValueError as e:
                logger.warning("Failed to unsubscribe handler for {}: {}", event, e)

        return unsubscribe

    def emit(self, payload: TrialEventPayload | JobEventPayload) -> None:
        for handler in list(self._handlers[payload.event]):
            try:
                handler(payload)
            except Exception as e:
                logger.warning("Event handler for {} failed: {}", payload.event, e)
