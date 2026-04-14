"""Calendar capability backed by Radicale CalDAV server."""

from __future__ import annotations

import time
import uuid
from datetime import datetime

import caldav
from loguru import logger

from terrarium.environment.capability import BaseCapability
from terrarium.environment.exceptions import CapabilityError
from terrarium.environment.logging import log_capability_call
from terrarium.environment.sandbox import SandboxSpec

DEFAULT_IMAGE = "tomsquest/docker-radicale:3.6.1.0"
DEFAULT_PORT = 5232
DEFAULT_USERNAME = "admin"


class CalendarCapability(BaseCapability):
    """Calendar capability backed by Radicale CalDAV server.

    Config options (all optional):
        image:    Docker image (default: "tomsquest/docker-radicale")
        port:     Container CalDAV port (default: 5232)
        username: CalDAV username (default: "admin")
    """

    def __init__(self, config=None, sandbox=None):
        super().__init__(config, sandbox)
        self._caldav_sandbox_port = self._config.get("port", DEFAULT_PORT)
        self._username = self._config.get("username", DEFAULT_USERNAME)
        self._caldav_host = None
        self._caldav_port = None
        self._client: caldav.DAVClient | None = None

    @classmethod
    def sandbox_spec(cls, config=None) -> SandboxSpec:
        config = config or {}
        port = config.get("port", DEFAULT_PORT)
        return SandboxSpec(
            image=config.get("image", DEFAULT_IMAGE),
            ports=[port],
            env={"RADICALE_CONFIG_AUTH_TYPE": "none"},
        )

    def wait_ready(self, timeout: float = 30.0) -> None:
        """Poll until Radicale responds to CalDAV requests."""
        self._caldav_host, self._caldav_port = self._sandbox.get_host(self._caldav_sandbox_port)
        url = f"http://{self._caldav_host}:{self._caldav_port}"

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                client = caldav.DAVClient(url=url, username=self._username, password="")
                client.principal()
                self._client = client
                logger.info("Calendar capability ready: CalDAV={}:{}", self._caldav_host, self._caldav_port)
                return
            except Exception:
                time.sleep(0.5)
        raise CapabilityError(f"Calendar (Radicale) not ready after {timeout}s")

    @property
    def connection_info(self) -> dict:
        """Connection details on the sandbox network."""
        host = self._sandbox.hostname()
        return {
            "caldav_host": host,
            "caldav_port": self._caldav_sandbox_port,
            "caldav_url": f"http://{host}:{self._caldav_sandbox_port}",
            "username": self._username,
        }

    def _get_client(self) -> caldav.DAVClient:
        if self._client is None:
            raise CapabilityError("Calendar not connected")
        return self._client

    def _find_calendar(self, calendar_id: str) -> caldav.Calendar:
        client = self._get_client()
        for cal in client.principal().calendars():
            if cal.url.path.rstrip("/").endswith(calendar_id):
                return cal
        raise CapabilityError(f"Calendar '{calendar_id}' not found")

    @log_capability_call
    def create_calendar(self, name: str, cal_id: str | None = None) -> str:
        """Create a new calendar. Returns the calendar ID."""
        try:
            client = self._get_client()
            if cal_id is None:
                cal_id = uuid.uuid4().hex[:12]
            client.principal().make_calendar(name=name, cal_id=cal_id)
            return cal_id
        except CapabilityError:
            raise
        except Exception as e:
            raise CapabilityError(f"Failed to create calendar: {e}") from e

    @log_capability_call
    def list_calendars(self) -> list[dict]:
        """List all calendars."""
        try:
            client = self._get_client()
            calendars = client.principal().calendars()
            result = []
            for cal in calendars:
                cal_id = cal.url.path.rstrip("/").split("/")[-1]
                result.append({
                    "id": cal_id,
                    "name": cal.get_display_name() or cal_id,
                    "url": str(cal.url),
                })
            return result
        except CapabilityError:
            raise
        except Exception as e:
            raise CapabilityError(f"Failed to list calendars: {e}") from e

    @log_capability_call
    def add_event(
        self,
        calendar_id: str,
        summary: str,
        dtstart: datetime,
        dtend: datetime,
        description: str | None = None,
    ) -> str:
        """Add an event to a calendar. Returns the event UID."""
        try:
            cal = self._find_calendar(calendar_id)
            kwargs = {"dtstart": dtstart, "dtend": dtend, "summary": summary}
            if description is not None:
                kwargs["description"] = description
            event = cal.save_event(**kwargs)
            return self._parse_event(event)["uid"]
        except CapabilityError:
            raise
        except Exception as e:
            raise CapabilityError(f"Failed to add event: {e}") from e

    @log_capability_call
    def list_events(self, calendar_id: str, start: datetime, end: datetime) -> list[dict]:
        """List events in a calendar within a date range."""
        try:
            cal = self._find_calendar(calendar_id)
            events = cal.search(event=True, start=start, end=end, expand=True)
            return [self._parse_event(e) for e in events]
        except CapabilityError:
            raise
        except Exception as e:
            raise CapabilityError(f"Failed to list events: {e}") from e

    @log_capability_call
    def get_event(self, calendar_id: str, uid: str) -> dict:
        """Get a single event by UID."""
        try:
            cal = self._find_calendar(calendar_id)
            event = cal.event_by_uid(uid)
            return self._parse_event(event)
        except CapabilityError:
            raise
        except Exception as e:
            raise CapabilityError(f"Failed to get event: {e}") from e

    @log_capability_call
    def delete_event(self, calendar_id: str, uid: str) -> None:
        """Delete an event by UID."""
        try:
            cal = self._find_calendar(calendar_id)
            event = cal.event_by_uid(uid)
            event.delete()
        except CapabilityError:
            raise
        except Exception as e:
            raise CapabilityError(f"Failed to delete event: {e}") from e

    @log_capability_call
    def delete_calendar(self, calendar_id: str) -> None:
        """Delete a calendar."""
        try:
            cal = self._find_calendar(calendar_id)
            cal.delete()
        except CapabilityError:
            raise
        except Exception as e:
            raise CapabilityError(f"Failed to delete calendar: {e}") from e

    @staticmethod
    def _parse_event(event) -> dict:
        """Parse a caldav event into a dict."""
        ical = event.icalendar_instance
        for component in ical.walk():
            if component.name == "VEVENT":
                dtstart = component.get("DTSTART")
                dtend = component.get("DTEND")
                return {
                    "uid": str(component.get("UID", "")),
                    "summary": str(component.get("SUMMARY", "")),
                    "dtstart": dtstart.dt if dtstart else None,
                    "dtend": dtend.dt if dtend else None,
                    "description": str(component.get("DESCRIPTION", "")),
                }
        return {"uid": "", "summary": "", "dtstart": None, "dtend": None, "description": ""}
