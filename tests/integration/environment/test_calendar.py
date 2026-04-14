"""Calendar integration tests — require running Docker daemon."""

from datetime import datetime, timedelta

import pytest
from tests.conftest import skip_no_docker
from terrarium.environment.environment import ComposableEnvironment


@skip_no_docker
@pytest.mark.timeout(120)
class TestCalendarIntegration:
    def test_create_and_list_calendars(self):
        with ComposableEnvironment(["calendar"]) as env:
            cal_id = env.calendar.create_calendar("Test Cal", cal_id="integ-cal")
            assert cal_id == "integ-cal"
            calendars = env.calendar.list_calendars()
            ids = [c["id"] for c in calendars]
            assert "integ-cal" in ids

    def test_add_and_list_events(self):
        with ComposableEnvironment(["calendar"]) as env:
            env.calendar.create_calendar("Events Cal", cal_id="evt-cal")
            env.calendar.add_event(
                "evt-cal", "Meeting",
                datetime(2026, 4, 1, 10, 0),
                datetime(2026, 4, 1, 11, 0),
            )
            events = env.calendar.list_events(
                "evt-cal",
                datetime(2026, 4, 1),
                datetime(2026, 4, 2),
            )
            assert len(events) == 1
            assert events[0]["summary"] == "Meeting"

    def test_add_and_get_event(self):
        with ComposableEnvironment(["calendar"]) as env:
            env.calendar.create_calendar("Get Cal", cal_id="get-cal")
            uid = env.calendar.add_event(
                "get-cal", "Lunch",
                datetime(2026, 4, 2, 12, 0),
                datetime(2026, 4, 2, 13, 0),
                description="Team lunch",
            )
            event = env.calendar.get_event("get-cal", uid)
            assert event["summary"] == "Lunch"
            assert event["description"] == "Team lunch"
            assert event["uid"] == uid

    def test_delete_event(self):
        with ComposableEnvironment(["calendar"]) as env:
            env.calendar.create_calendar("Del Cal", cal_id="del-cal")
            uid = env.calendar.add_event(
                "del-cal", "To Delete",
                datetime(2026, 4, 3, 9, 0),
                datetime(2026, 4, 3, 10, 0),
            )
            env.calendar.delete_event("del-cal", uid)
            events = env.calendar.list_events(
                "del-cal",
                datetime(2026, 4, 3),
                datetime(2026, 4, 4),
            )
            assert len(events) == 0

    def test_delete_calendar(self):
        with ComposableEnvironment(["calendar"]) as env:
            env.calendar.create_calendar("Temp Cal", cal_id="temp-cal")
            env.calendar.delete_calendar("temp-cal")
            calendars = env.calendar.list_calendars()
            ids = [c["id"] for c in calendars]
            assert "temp-cal" not in ids

    def test_multiple_events(self):
        with ComposableEnvironment(["calendar"]) as env:
            env.calendar.create_calendar("Multi Cal", cal_id="multi-cal")
            env.calendar.add_event("multi-cal", "Event 1",
                                  datetime(2026, 4, 1, 10, 0),
                                  datetime(2026, 4, 1, 11, 0))
            env.calendar.add_event("multi-cal", "Event 2",
                                  datetime(2026, 4, 1, 14, 0),
                                  datetime(2026, 4, 1, 15, 0))
            env.calendar.add_event("multi-cal", "Event 3",
                                  datetime(2026, 4, 2, 10, 0),
                                  datetime(2026, 4, 2, 11, 0))
            events = env.calendar.list_events(
                "multi-cal",
                datetime(2026, 4, 1),
                datetime(2026, 4, 3),
            )
            assert len(events) == 3

    def test_event_search_date_range(self):
        with ComposableEnvironment(["calendar"]) as env:
            env.calendar.create_calendar("Range Cal", cal_id="range-cal")
            env.calendar.add_event("range-cal", "April 1",
                                  datetime(2026, 4, 1, 10, 0),
                                  datetime(2026, 4, 1, 11, 0))
            env.calendar.add_event("range-cal", "April 10",
                                  datetime(2026, 4, 10, 10, 0),
                                  datetime(2026, 4, 10, 11, 0))
            # Search only first week
            events = env.calendar.list_events(
                "range-cal",
                datetime(2026, 4, 1),
                datetime(2026, 4, 5),
            )
            assert len(events) == 1
            assert events[0]["summary"] == "April 1"

    def test_connection_info(self):
        with ComposableEnvironment(["calendar"]) as env:
            info = env.calendar.connection_info
            assert "caldav_host" in info
            assert "caldav_url" in info
            assert info["caldav_port"] == 5232
            assert info["username"] == "admin"
