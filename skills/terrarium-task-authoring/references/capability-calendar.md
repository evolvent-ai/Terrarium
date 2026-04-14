# Calendar Capability API

Backed by Radicale CalDAV server. Auth is disabled — any username/password works.

## connection_info

```python
info = env.calendar.connection_info
# {
#     "caldav_host": "<sandbox_hostname>",
#     "caldav_port": 5232,
#     "caldav_url": "http://<sandbox_hostname>:5232",
#     "username": "admin",
# }
```

## Methods

### create_calendar()

```python
env.calendar.create_calendar(name: str, cal_id: str | None = None) -> str
```

Create a new calendar.

**Parameters:**
- `name` — display name for the calendar
- `cal_id` — optional custom ID. If omitted, a random 12-char hex string is generated.

**Returns:** the calendar ID (string). Use this ID in all subsequent calendar operations.

```python
cal_id = env.calendar.create_calendar("Work")
# cal_id = "a1b2c3d4e5f6"
```

### list_calendars()

```python
env.calendar.list_calendars() -> list[dict]
```

List all calendars.

**Returns:** list of dicts, each with:

```python
{
    "id": "a1b2c3d4e5f6",    # calendar ID, used in other methods
    "name": "Work",           # display name
    "url": "http://...",      # full CalDAV URL
}
```

### add_event()

```python
env.calendar.add_event(
    calendar_id: str,
    summary: str,
    dtstart: datetime,
    dtend: datetime,
    description: str | None = None,
) -> str
```

Add an event to a calendar.

**Parameters:**
- `calendar_id` — the ID returned by `create_calendar()` or from `list_calendars()`
- `summary` — event title (e.g. "RL Final Exam")
- `dtstart` — start time as a `datetime` object
- `dtend` — end time as a `datetime` object
- `description` — optional event description / notes

**Returns:** the event UID (string). Use this to get, update, or delete the event.

```python
from datetime import datetime

uid = env.calendar.add_event(
    cal_id,
    summary="RL Final Exam",
    dtstart=datetime(2025, 6, 20, 14, 0),
    dtend=datetime(2025, 6, 20, 16, 0),
    description="Room 301, CS Building",
)
```

### list_events()

```python
env.calendar.list_events(calendar_id: str, start: datetime, end: datetime) -> list[dict]
```

List events in a calendar within a date range.

**Parameters:**
- `calendar_id` — the calendar to query
- `start` — range start (inclusive) as a `datetime` object
- `end` — range end (exclusive) as a `datetime` object

**Returns:** list of event dicts:

```python
{
    "uid": "abc123",                           # event UID
    "summary": "RL Final Exam",                # event title
    "dtstart": datetime(2025, 6, 20, 14, 0),   # datetime object
    "dtend": datetime(2025, 6, 20, 16, 0),     # datetime object
    "description": "Room 301, CS Building",    # may be empty string
}
```

```python
from datetime import datetime

events = env.calendar.list_events(
    cal_id,
    start=datetime(2025, 6, 1),
    end=datetime(2025, 7, 1),
)
```

### get_event()

```python
env.calendar.get_event(calendar_id: str, uid: str) -> dict
```

Get a single event by UID.

**Parameters:**
- `calendar_id` — the calendar containing the event
- `uid` — the event UID returned by `add_event()` or from `list_events()`

**Returns:** event dict with the same structure as `list_events()`.

### delete_event()

```python
env.calendar.delete_event(calendar_id: str, uid: str) -> None
```

Delete an event.

**Parameters:**
- `calendar_id` — the calendar containing the event
- `uid` — the event UID to delete

### delete_calendar()

```python
env.calendar.delete_calendar(calendar_id: str) -> None
```

Delete an entire calendar and all its events.

**Parameters:**
- `calendar_id` — the calendar ID to delete
