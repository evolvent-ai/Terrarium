import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from datetime import datetime
from terrarium.environment.capabilities.calendar import CalendarCapability
from terrarium.environment.exceptions import CapabilityError
from terrarium.environment.sandbox import ExecResult


def _make_mock_event(uid="test-uid", summary="Test Event",
                     dtstart=None, dtend=None, description=""):
    """Build a mock caldav event with icalendar_instance."""
    mock_event = MagicMock()
    mock_component = MagicMock()
    mock_component.name = "VEVENT"

    mock_dtstart = MagicMock()
    mock_dtstart.dt = dtstart or datetime(2026, 4, 1, 10, 0)
    mock_dtend = MagicMock()
    mock_dtend.dt = dtend or datetime(2026, 4, 1, 11, 0)

    def get_side_effect(key, default=""):
        return {
            "UID": uid,
            "SUMMARY": summary,
            "DTSTART": mock_dtstart,
            "DTEND": mock_dtend,
            "DESCRIPTION": description,
        }.get(key, default)

    mock_component.get = get_side_effect

    vcalendar = MagicMock()
    vcalendar.name = "VCALENDAR"
    mock_event.icalendar_instance.walk.return_value = [vcalendar, mock_component]
    return mock_event


class TestCalendarCapabilityUnit:
    def _make_sandbox(self):
        sandbox = MagicMock()
        sandbox.get_host.return_value = ("localhost", 15232)
        sandbox.hostname.return_value = "calendar-container"
        sandbox.exec.return_value = ExecResult(exit_code=0, stdout="", stderr="")
        return sandbox

    def _make_cap(self):
        """Create a capability with a mock client already injected."""
        sandbox = self._make_sandbox()
        cap = CalendarCapability(sandbox=sandbox)
        cap._caldav_host = "localhost"
        cap._caldav_port = 15232
        cap._client = MagicMock()
        return cap, cap._client

    def _make_mock_calendar(self, cal_id="test-cal", name="Test Calendar"):
        """Build a mock caldav Calendar object."""
        mock_cal = MagicMock()
        mock_url = MagicMock()
        mock_url.path = f"/admin/{cal_id}/"
        mock_url.__str__ = lambda self: f"http://localhost:5232/admin/{cal_id}/"
        mock_cal.url = mock_url
        mock_cal.get_display_name.return_value = name
        return mock_cal

    # -------------------------------------------------------------------
    # sandbox_spec + config
    # -------------------------------------------------------------------

    def test_sandbox_spec_defaults(self):
        spec = CalendarCapability.sandbox_spec()
        assert spec.image.name == "tomsquest/docker-radicale:3.6.1.0"
        assert 5232 in spec.ports
        assert spec.env["RADICALE_CONFIG_AUTH_TYPE"] == "none"

    def test_sandbox_spec_custom_config(self):
        spec = CalendarCapability.sandbox_spec({
            "image": {"name": "custom/radicale:latest"},
            "port": 9232,
        })
        assert spec.image.name == "custom/radicale:latest"
        assert 9232 in spec.ports

    def test_init_defaults(self):
        sandbox = self._make_sandbox()
        cap = CalendarCapability(sandbox=sandbox)
        assert cap._caldav_sandbox_port == 5232
        assert cap._username == "admin"

    def test_init_custom_config(self):
        sandbox = self._make_sandbox()
        cap = CalendarCapability(
            config={"port": 9232, "username": "testuser"},
            sandbox=sandbox,
        )
        assert cap._caldav_sandbox_port == 9232
        assert cap._username == "testuser"

    # -------------------------------------------------------------------
    # connection_info
    # -------------------------------------------------------------------

    def test_connection_info(self):
        sandbox = self._make_sandbox()
        cap = CalendarCapability(sandbox=sandbox)
        info = cap.connection_info
        assert info["caldav_host"] == "calendar-container"
        assert info["caldav_port"] == 5232
        assert info["caldav_url"] == "http://calendar-container:5232"
        assert info["username"] == "admin"

    # -------------------------------------------------------------------
    # wait_ready
    # -------------------------------------------------------------------

    @patch("terrarium.environment.capabilities.calendar.caldav.DAVClient")
    def test_wait_ready_connects(self, mock_dav_class):
        sandbox = self._make_sandbox()
        cap = CalendarCapability(sandbox=sandbox)
        cap.wait_ready(timeout=5.0)
        mock_dav_class.assert_called_once()
        assert cap._client is not None

    @patch("terrarium.environment.capabilities.calendar.caldav.DAVClient")
    @patch("terrarium.environment.capabilities.calendar.time")
    def test_wait_ready_timeout(self, mock_time, mock_dav_class):
        sandbox = self._make_sandbox()
        mock_dav_class.return_value.principal.side_effect = Exception("not ready")
        mock_time.monotonic.side_effect = [0, 0, 100]
        mock_time.sleep = MagicMock()
        cap = CalendarCapability(sandbox=sandbox)
        with pytest.raises(CapabilityError, match="not ready"):
            cap.wait_ready(timeout=5.0)

    @patch("terrarium.environment.capabilities.calendar.caldav.DAVClient")
    def test_wait_ready_retries(self, mock_dav_class):
        sandbox = self._make_sandbox()
        mock_client = MagicMock()
        mock_client.principal.side_effect = [Exception("not yet"), Exception("not yet"), MagicMock()]
        mock_dav_class.return_value = mock_client
        cap = CalendarCapability(sandbox=sandbox)
        cap.wait_ready(timeout=10.0)
        assert mock_client.principal.call_count == 3

    # -------------------------------------------------------------------
    # _get_client
    # -------------------------------------------------------------------

    def test_get_client_not_connected(self):
        sandbox = self._make_sandbox()
        cap = CalendarCapability(sandbox=sandbox)
        with pytest.raises(CapabilityError, match="not connected"):
            cap._get_client()

    # -------------------------------------------------------------------
    # create_calendar
    # -------------------------------------------------------------------

    def test_create_calendar(self):
        cap, client = self._make_cap()
        cal_id = cap.create_calendar("My Calendar", cal_id="my-cal")
        assert cal_id == "my-cal"
        client.principal().make_calendar.assert_called_once_with(name="My Calendar", cal_id="my-cal")

    def test_create_calendar_auto_id(self):
        cap, client = self._make_cap()
        cal_id = cap.create_calendar("Auto Calendar")
        assert len(cal_id) == 12
        client.principal().make_calendar.assert_called_once()

    def test_create_calendar_error(self):
        cap, client = self._make_cap()
        client.principal().make_calendar.side_effect = Exception("server error")
        with pytest.raises(CapabilityError, match="Failed to create calendar"):
            cap.create_calendar("Bad Calendar")

    # -------------------------------------------------------------------
    # list_calendars
    # -------------------------------------------------------------------

    def test_list_calendars(self):
        cap, client = self._make_cap()
        mock_cal1 = self._make_mock_calendar("cal1", "Calendar One")
        mock_cal2 = self._make_mock_calendar("cal2", "Calendar Two")
        client.principal().calendars.return_value = [mock_cal1, mock_cal2]

        result = cap.list_calendars()
        assert len(result) == 2
        assert result[0]["id"] == "cal1"
        assert result[0]["name"] == "Calendar One"
        assert result[1]["id"] == "cal2"

    def test_list_calendars_empty(self):
        cap, client = self._make_cap()
        client.principal().calendars.return_value = []
        assert cap.list_calendars() == []

    def test_list_calendars_error(self):
        cap, client = self._make_cap()
        client.principal().calendars.side_effect = Exception("fail")
        with pytest.raises(CapabilityError, match="Failed to list"):
            cap.list_calendars()

    # -------------------------------------------------------------------
    # _find_calendar
    # -------------------------------------------------------------------

    def test_find_calendar(self):
        cap, client = self._make_cap()
        mock_cal = self._make_mock_calendar("my-cal")
        client.principal().calendars.return_value = [mock_cal]
        found = cap._find_calendar("my-cal")
        assert found is mock_cal

    def test_find_calendar_not_found(self):
        cap, client = self._make_cap()
        client.principal().calendars.return_value = []
        with pytest.raises(CapabilityError, match="not found"):
            cap._find_calendar("missing")

    # -------------------------------------------------------------------
    # add_event
    # -------------------------------------------------------------------

    def test_add_event(self):
        cap, client = self._make_cap()
        mock_cal = self._make_mock_calendar("my-cal")
        client.principal().calendars.return_value = [mock_cal]
        mock_cal.save_event.return_value = _make_mock_event(uid="evt-123")

        uid = cap.add_event("my-cal", "Meeting",
                            datetime(2026, 4, 1, 10, 0),
                            datetime(2026, 4, 1, 11, 0))
        assert uid == "evt-123"
        mock_cal.save_event.assert_called_once()

    def test_add_event_with_description(self):
        cap, client = self._make_cap()
        mock_cal = self._make_mock_calendar("my-cal")
        client.principal().calendars.return_value = [mock_cal]
        mock_cal.save_event.return_value = _make_mock_event(uid="evt-456")

        cap.add_event("my-cal", "Meeting",
                      datetime(2026, 4, 1, 10, 0),
                      datetime(2026, 4, 1, 11, 0),
                      description="Important meeting")
        kwargs = mock_cal.save_event.call_args[1]
        assert kwargs["description"] == "Important meeting"

    def test_add_event_calendar_not_found(self):
        cap, client = self._make_cap()
        client.principal().calendars.return_value = []
        with pytest.raises(CapabilityError, match="not found"):
            cap.add_event("missing", "Event",
                          datetime(2026, 4, 1, 10, 0),
                          datetime(2026, 4, 1, 11, 0))

    def test_add_event_error(self):
        cap, client = self._make_cap()
        mock_cal = self._make_mock_calendar("my-cal")
        client.principal().calendars.return_value = [mock_cal]
        mock_cal.save_event.side_effect = Exception("save failed")
        with pytest.raises(CapabilityError, match="Failed to add event"):
            cap.add_event("my-cal", "Event",
                          datetime(2026, 4, 1, 10, 0),
                          datetime(2026, 4, 1, 11, 0))

    # -------------------------------------------------------------------
    # list_events
    # -------------------------------------------------------------------

    def test_list_events(self):
        cap, client = self._make_cap()
        mock_cal = self._make_mock_calendar("my-cal")
        client.principal().calendars.return_value = [mock_cal]
        mock_cal.search.return_value = [
            _make_mock_event("e1", "Event 1"),
            _make_mock_event("e2", "Event 2"),
        ]

        events = cap.list_events("my-cal",
                                 datetime(2026, 4, 1),
                                 datetime(2026, 4, 30))
        assert len(events) == 2
        assert events[0]["uid"] == "e1"
        assert events[1]["summary"] == "Event 2"

    def test_list_events_empty(self):
        cap, client = self._make_cap()
        mock_cal = self._make_mock_calendar("my-cal")
        client.principal().calendars.return_value = [mock_cal]
        mock_cal.search.return_value = []

        assert cap.list_events("my-cal", datetime(2026, 4, 1), datetime(2026, 4, 30)) == []

    def test_list_events_error(self):
        cap, client = self._make_cap()
        mock_cal = self._make_mock_calendar("my-cal")
        client.principal().calendars.return_value = [mock_cal]
        mock_cal.search.side_effect = Exception("search failed")
        with pytest.raises(CapabilityError, match="Failed to list events"):
            cap.list_events("my-cal", datetime(2026, 4, 1), datetime(2026, 4, 30))

    # -------------------------------------------------------------------
    # get_event
    # -------------------------------------------------------------------

    def test_get_event(self):
        cap, client = self._make_cap()
        mock_cal = self._make_mock_calendar("my-cal")
        client.principal().calendars.return_value = [mock_cal]
        mock_cal.event_by_uid.return_value = _make_mock_event(
            uid="evt-1", summary="Found Event", description="Details")

        event = cap.get_event("my-cal", "evt-1")
        assert event["uid"] == "evt-1"
        assert event["summary"] == "Found Event"
        assert event["description"] == "Details"

    def test_get_event_not_found(self):
        cap, client = self._make_cap()
        mock_cal = self._make_mock_calendar("my-cal")
        client.principal().calendars.return_value = [mock_cal]
        mock_cal.event_by_uid.side_effect = Exception("not found")
        with pytest.raises(CapabilityError, match="Failed to get event"):
            cap.get_event("my-cal", "missing-uid")

    # -------------------------------------------------------------------
    # delete_event
    # -------------------------------------------------------------------

    def test_delete_event(self):
        cap, client = self._make_cap()
        mock_cal = self._make_mock_calendar("my-cal")
        client.principal().calendars.return_value = [mock_cal]
        mock_event = MagicMock()
        mock_cal.event_by_uid.return_value = mock_event

        cap.delete_event("my-cal", "evt-1")
        mock_event.delete.assert_called_once()

    def test_delete_event_not_found(self):
        cap, client = self._make_cap()
        mock_cal = self._make_mock_calendar("my-cal")
        client.principal().calendars.return_value = [mock_cal]
        mock_cal.event_by_uid.side_effect = Exception("not found")
        with pytest.raises(CapabilityError, match="Failed to delete event"):
            cap.delete_event("my-cal", "missing-uid")

    # -------------------------------------------------------------------
    # delete_calendar
    # -------------------------------------------------------------------

    def test_delete_calendar(self):
        cap, client = self._make_cap()
        mock_cal = self._make_mock_calendar("my-cal")
        client.principal().calendars.return_value = [mock_cal]

        cap.delete_calendar("my-cal")
        mock_cal.delete.assert_called_once()

    def test_delete_calendar_not_found(self):
        cap, client = self._make_cap()
        client.principal().calendars.return_value = []
        with pytest.raises(CapabilityError, match="not found"):
            cap.delete_calendar("missing")

    def test_delete_calendar_error(self):
        cap, client = self._make_cap()
        mock_cal = self._make_mock_calendar("my-cal")
        client.principal().calendars.return_value = [mock_cal]
        mock_cal.delete.side_effect = Exception("delete failed")
        with pytest.raises(CapabilityError, match="Failed to delete calendar"):
            cap.delete_calendar("my-cal")

    # -------------------------------------------------------------------
    # _parse_event
    # -------------------------------------------------------------------

    def test_parse_event_full(self):
        event = _make_mock_event(
            uid="u1", summary="Full Event",
            dtstart=datetime(2026, 4, 1, 10, 0),
            dtend=datetime(2026, 4, 1, 11, 0),
            description="Desc",
        )
        result = CalendarCapability._parse_event(event)
        assert result["uid"] == "u1"
        assert result["summary"] == "Full Event"
        assert result["dtstart"] == datetime(2026, 4, 1, 10, 0)
        assert result["dtend"] == datetime(2026, 4, 1, 11, 0)
        assert result["description"] == "Desc"

    def test_parse_event_no_description(self):
        event = _make_mock_event(uid="u2", summary="No Desc")
        result = CalendarCapability._parse_event(event)
        assert result["description"] == ""

    def test_parse_event_no_vevent(self):
        mock_event = MagicMock()
        vcalendar = MagicMock()
        vcalendar.name = "VCALENDAR"
        mock_event.icalendar_instance.walk.return_value = [vcalendar]
        result = CalendarCapability._parse_event(mock_event)
        assert result["uid"] == ""
        assert result["dtstart"] is None
