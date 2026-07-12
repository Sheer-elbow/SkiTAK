"""Geofence creation, containment, and transition-based alerting."""
from __future__ import annotations

import uuid

import pytest

from skitak.geofence import (
    GeofenceError,
    GeofenceMonitor,
    create_geofence,
    delete_geofence,
    list_geofences,
    recent_events,
)
from skitak.sessions import create_session

# A ~2 km square around 46.0, 7.0
SQUARE = [
    {"lat": 45.99, "lon": 6.99},
    {"lat": 45.99, "lon": 7.01},
    {"lat": 46.01, "lon": 7.01},
    {"lat": 46.01, "lon": 6.99},
]

INSIDE = (46.0, 7.0)
OUTSIDE = (46.05, 7.05)


def _session(session):
    return uuid.UUID(create_session(session, "S", "skiing", "GUIDE-1"))


def test_create_polygon_fence_and_list(session):
    sid = _session(session)
    create_geofence(session, sid, "Piste boundary", "keep_in", polygon=SQUARE)
    fences = list_geofences(session, sid)
    assert len(fences) == 1
    assert fences[0]["name"] == "Piste boundary"
    assert fences[0]["fence_type"] == "keep_in"
    # Ring is closed server-side
    assert fences[0]["points"][0] == fences[0]["points"][-1]


def test_create_circle_fence(session):
    sid = _session(session)
    create_geofence(session, sid, "Avalanche zone", "keep_out",
                    circle={"lat": 46.0, "lon": 7.0, "radius_m": 500})
    fences = list_geofences(session, sid)
    assert len(fences) == 1
    assert len(fences[0]["points"]) > 10  # buffered circle approximation


def test_validation(session):
    sid = _session(session)
    with pytest.raises(GeofenceError):
        create_geofence(session, sid, "", "keep_in", polygon=SQUARE)
    with pytest.raises(GeofenceError):
        create_geofence(session, sid, "x", "banana", polygon=SQUARE)
    with pytest.raises(GeofenceError):
        create_geofence(session, sid, "x", "keep_in", polygon=SQUARE[:2])
    with pytest.raises(GeofenceError):
        create_geofence(session, sid, "x", "keep_in",
                        circle={"lat": 200, "lon": 7, "radius_m": 100})
    with pytest.raises(GeofenceError):
        create_geofence(session, sid, "x", "keep_in", polygon=None, circle=None)


def test_keep_in_transitions(session):
    """One alert on exit, one 'cleared' on return — never one per fix."""
    sid = _session(session)
    create_geofence(session, sid, "Boundary", "keep_in", polygon=SQUARE)

    emitted = []
    monitor = GeofenceMonitor(emit=emitted.append)

    # Inside: safe, no event
    assert monitor.check(session, sid, "DEV-1", "AliceS", *INSIDE) == []
    # Leaves: one violation
    events = monitor.check(session, sid, "DEV-1", "AliceS", *OUTSIDE)
    assert [e["event_type"] for e in events] == ["violation"]
    assert events[0]["geofence_name"] == "Boundary"
    # Still outside: no repeat alert
    assert monitor.check(session, sid, "DEV-1", "AliceS", 46.06, 7.06) == []
    # Returns: cleared
    events = monitor.check(session, sid, "DEV-1", "AliceS", *INSIDE)
    assert [e["event_type"] for e in events] == ["cleared"]

    # Both transitions persisted, newest first
    log = recent_events(session, sid)
    assert [e["event_type"] for e in log] == ["cleared", "violation"]
    assert log[0]["callsign"] == "AliceS"
    assert emitted[0]["event_type"] == "violation"
    assert len(emitted) == 2


def test_keep_out_transitions(session):
    sid = _session(session)
    create_geofence(session, sid, "Closed couloir", "keep_out", polygon=SQUARE)
    monitor = GeofenceMonitor()

    # Outside a keep_out zone: safe
    assert monitor.check(session, sid, "DEV-2", "BobT", *OUTSIDE) == []
    # Enters: violation
    events = monitor.check(session, sid, "DEV-2", "BobT", *INSIDE)
    assert [e["event_type"] for e in events] == ["violation"]


def test_devices_tracked_independently(session):
    sid = _session(session)
    create_geofence(session, sid, "Boundary", "keep_in", polygon=SQUARE)
    monitor = GeofenceMonitor()

    monitor.check(session, sid, "DEV-A", "A", *INSIDE)
    monitor.check(session, sid, "DEV-B", "B", *INSIDE)
    events = monitor.check(session, sid, "DEV-A", "A", *OUTSIDE)
    assert len(events) == 1
    # DEV-B is still inside — no event for it
    assert monitor.check(session, sid, "DEV-B", "B", *INSIDE) == []


def test_sessions_without_fences_skip_cheaply(session):
    sid = _session(session)
    monitor = GeofenceMonitor()
    assert monitor.check(session, sid, "DEV-1", "A", *INSIDE) == []


def test_delete_fence(session):
    sid = _session(session)
    fid = uuid.UUID(create_geofence(session, sid, "Zone", "keep_in", polygon=SQUARE))
    assert delete_geofence(session, sid, fid) is True
    assert list_geofences(session, sid) == []
    assert delete_geofence(session, sid, uuid.uuid4()) is False


def test_ingest_triggers_geofence(session):
    """The full ingest path: a stored position outside the fence raises."""
    from skitak.enrollment import _consume_token, create_invite_token
    from skitak.ingest import ingest_position
    from skitak.sessions import create_team, start_session

    sid = _session(session)
    tid = uuid.UUID(create_team(session, sid, "Team", "Cyan"))
    token = create_invite_token(session, sid, tid, "Team", "Cyan")
    _consume_token(session, token, "SwiftFox42")
    start_session(session, sid)
    create_geofence(session, sid, "Boundary", "keep_in", polygon=SQUARE)

    emitted = []
    monitor = GeofenceMonitor(emit=emitted.append)

    from datetime import datetime, timezone

    def pos(lat, lon):
        return {
            "uid": "DEV-9", "callsign": "SwiftFox42", "time": datetime.now(timezone.utc),
            "point": {"lat": lat, "lon": lon, "hae": None, "ce": None},
            "detail": {"track": {"speed": None, "course": None}, "status": {"battery": None}},
        }

    inside = pos(*INSIDE)
    outside = pos(*OUTSIDE)

    assert ingest_position(session, inside, geofence_monitor=monitor) is True
    assert ingest_position(session, outside, geofence_monitor=monitor) is True
    assert [e["event_type"] for e in emitted] == ["violation"]
    assert emitted[0]["callsign"] == "SwiftFox42"
