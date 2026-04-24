"""Tests for the execution event bus and payloads."""
from __future__ import annotations

from terrarium.execution.events import (
    EventBus,
    JobEvent,
    JobEventPayload,
    JobFinishedPayload,
    JobStartedPayload,
    TrialEvent,
    TrialEventPayload,
    TrialQueuedPayload,
    TrialStartedPayload,
)


def _trial_payload(event: TrialEvent = TrialEvent.QUEUED, name: str = "t1") -> TrialEventPayload:
    return TrialEventPayload(event=event, trial_name=name, payload=TrialQueuedPayload())


def test_trial_event_values():
    """TrialEvent enum covers the four lifecycle events."""
    assert TrialEvent.QUEUED.value == "queued"
    assert TrialEvent.STARTED.value == "started"
    assert TrialEvent.SUCCEEDED.value == "succeeded"
    assert TrialEvent.FAILED.value == "failed"


def test_job_event_values():
    """JobEvent enum covers start and finish."""
    assert JobEvent.STARTED.value == "started"
    assert JobEvent.FINISHED.value == "finished"


def test_trial_queued_and_started_inner_payloads_are_empty():
    """QUEUED and STARTED inner payloads carry no fields."""
    assert TrialQueuedPayload().model_dump() == {}
    assert TrialStartedPayload().model_dump() == {}


def test_job_started_payload_carries_n_trials():
    """JobStartedPayload exposes n_trials for subscribers that need to size UI."""
    assert JobStartedPayload(n_trials=5).n_trials == 5


def test_job_finished_payload_is_empty():
    """JobFinishedPayload has no fields today but is reserved for future data."""
    assert JobFinishedPayload().model_dump() == {}


def test_trial_event_payload_envelope():
    """Envelope carries event, trial_name, a timezone-aware timestamp, and inner payload."""
    p = TrialEventPayload(
        event=TrialEvent.QUEUED,
        trial_name="t1",
        payload=TrialQueuedPayload(),
    )
    assert p.event == TrialEvent.QUEUED
    assert p.trial_name == "t1"
    assert isinstance(p.payload, TrialQueuedPayload)
    assert p.timestamp.tzinfo is not None


def test_job_event_payload_envelope():
    """JobEventPayload nests the event-specific payload."""
    p = JobEventPayload(
        event=JobEvent.STARTED,
        job_name="j1",
        payload=JobStartedPayload(n_trials=3),
    )
    assert p.event == JobEvent.STARTED
    assert p.job_name == "j1"
    assert p.payload.n_trials == 3


def test_trial_event_payload_is_json_serializable():
    """Envelope round-trips to JSON — supports future on-disk event logs."""
    p = TrialEventPayload(
        event=TrialEvent.STARTED,
        trial_name="t1",
        payload=TrialStartedPayload(),
    )
    s = p.model_dump_json()
    assert '"event":"started"' in s
    assert '"trial_name":"t1"' in s


def test_bus_emit_calls_subscribed_handler():
    """A subscribed handler fires when its event is emitted."""
    bus = EventBus()
    received: list[TrialEventPayload] = []
    bus.subscribe(TrialEvent.QUEUED, received.append)

    bus.emit(_trial_payload())

    assert len(received) == 1
    assert received[0].trial_name == "t1"


def test_bus_emit_keys_by_payload_event():
    """emit() reads payload.event to find handlers — no explicit key argument."""
    bus = EventBus()
    queued: list[TrialEventPayload] = []
    started: list[TrialEventPayload] = []
    bus.subscribe(TrialEvent.QUEUED, queued.append)
    bus.subscribe(TrialEvent.STARTED, started.append)

    bus.emit(_trial_payload(event=TrialEvent.QUEUED))

    assert len(queued) == 1
    assert len(started) == 0


def test_bus_handlers_called_in_subscription_order():
    """Multiple handlers for the same event run in subscribe-order."""
    bus = EventBus()
    order: list[str] = []
    bus.subscribe(TrialEvent.QUEUED, lambda _p: order.append("first"))
    bus.subscribe(TrialEvent.QUEUED, lambda _p: order.append("second"))

    bus.emit(_trial_payload())

    assert order == ["first", "second"]


def test_bus_emit_with_no_subscribers_is_noop():
    """Emitting without subscribers does not raise."""
    EventBus().emit(_trial_payload())


def test_bus_unsubscribe_via_returned_token():
    """The callable returned by subscribe() removes the handler."""
    bus = EventBus()
    received: list[TrialEventPayload] = []
    unsubscribe = bus.subscribe(TrialEvent.QUEUED, received.append)

    bus.emit(_trial_payload())
    unsubscribe()
    bus.emit(_trial_payload())

    assert len(received) == 1


def test_bus_handler_exception_is_isolated():
    """A failing handler does not prevent later handlers from running."""
    bus = EventBus()
    received: list[TrialEventPayload] = []

    def bad(_p: TrialEventPayload) -> None:
        raise RuntimeError("boom")

    bus.subscribe(TrialEvent.QUEUED, bad)
    bus.subscribe(TrialEvent.QUEUED, received.append)

    bus.emit(_trial_payload())

    assert len(received) == 1


def test_bus_supports_job_events():
    """The same bus instance routes JobEvent payloads correctly."""
    bus = EventBus()
    received: list[JobEventPayload] = []
    bus.subscribe(JobEvent.STARTED, received.append)

    bus.emit(JobEventPayload(
        event=JobEvent.STARTED,
        job_name="j1",
        payload=JobStartedPayload(n_trials=2),
    ))

    assert len(received) == 1
    assert received[0].payload.n_trials == 2
