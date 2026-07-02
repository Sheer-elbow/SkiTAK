"""Session, team, and track behaviour — exercises the PostGIS SQL for real."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from skitak.sessions import (
    create_session,
    create_team,
    end_session,
    get_session_summary,
    get_team,
    list_sessions,
    start_session,
)
from skitak.tracks import export_gpx, get_session_track, store_track_point


def _track_point(session_id: str, uid: str, when: datetime, lat: float, lon: float, speed: float = 3.0):
    return {
        "session_id": session_id,
        "uid": uid,
        "time": when,
        "point": {"lat": lat, "lon": lon, "hae": 1200.0, "ce": 5.0},
        "detail": {"track": {"speed": speed, "course": 90.0}, "status": {"battery": 80}},
    }


def test_session_lifecycle(session):
    sid = create_session(session, "Morning run", "trail_run", "GUIDE-1")
    start_session(session, uuid.UUID(sid))
    end_session(session, uuid.UUID(sid))

    sessions = list_sessions(session)
    assert len(sessions) == 1
    assert sessions[0]["name"] == "Morning run"
    assert sessions[0]["started_at"] is not None
    assert sessions[0]["ended_at"] is not None


def test_teams(session):
    sid = uuid.UUID(create_session(session, "Ride", "equestrian", "GUIDE-1"))
    tid = uuid.UUID(create_team(session, sid, "Group A", "Blue"))

    team = get_team(session, sid, tid)
    assert team is not None
    assert team["name"] == "Group A"
    assert team["color"] == "Blue"
    assert get_team(session, sid, uuid.uuid4()) is None

    listed = list_sessions(session)
    assert listed[0]["teams"][0]["name"] == "Group A"


def test_session_summary_computes_distance(session):
    """The summary SQL must aggregate LAG deltas via a CTE (regression:
    window functions are not allowed inside aggregates)."""
    sid = create_session(session, "Ski day", "skiing", "GUIDE-1")
    start = datetime.now(timezone.utc)

    # ~111m between successive points (0.001° latitude)
    for i in range(5):
        store_track_point(
            session,
            _track_point(sid, "DEV-1", start + timedelta(seconds=10 * i), 46.0 + 0.001 * i, 7.0, speed=2.0 + i),
        )

    summary = get_session_summary(session, uuid.UUID(sid))
    assert summary["participant_count"] == 1
    assert float(summary["total_km"]) > 0.4
    assert round(summary["max_speed_kph"], 1) == round(6.0 * 3.6, 1)


def test_session_summary_empty_session(session):
    sid = create_session(session, "No tracks yet", "hiking", "GUIDE-1")
    summary = get_session_summary(session, uuid.UUID(sid))
    assert summary["participant_count"] == 0
    assert float(summary["total_km"]) == 0.0


def test_track_and_gpx_export(session):
    sid = create_session(session, "Hike", "hiking", "GUIDE-1")
    start = datetime.now(timezone.utc)
    for i in range(3):
        store_track_point(
            session,
            _track_point(sid, "DEV-2", start + timedelta(seconds=30 * i), 51.5 + 0.001 * i, -0.1),
        )

    points = get_session_track(session, uuid.UUID(sid), "DEV-2")
    assert len(points) == 3
    assert points[0]["lat"] == 51.5

    gpx = export_gpx(session, uuid.UUID(sid), "DEV-2", 'Alice "<&>" S')
    assert gpx.count("<trkpt") == 3
    # XML-unsafe callsigns must be escaped
    assert 'Alice "&lt;&amp;&gt;" S' in gpx

    assert export_gpx(session, uuid.UUID(sid), "NOBODY", "x") == ""
