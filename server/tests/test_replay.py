"""Session detail + all-tracks — the data behind history and replay."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from skitak.sessions import create_session, create_team, get_session_detail
from skitak.tracks import get_session_tracks, store_track_point


def _point(session_id, uid, when, lat, speed=2.0):
    return {
        "session_id": session_id,
        "uid": uid,
        "time": when,
        "point": {"lat": lat, "lon": 7.0, "hae": 1000.0 + lat, "ce": 5.0},
        "detail": {"track": {"speed": speed, "course": 0.0}, "status": {"battery": 50}},
    }


def _seed(session, uids=("DEV-A", "DEV-B"), n=6):
    sid = create_session(session, "Replay day", "skiing", "GUIDE-1")
    tid = uuid.UUID(create_team(session, uuid.UUID(sid), "Reds", "Red"))
    start = datetime.now(timezone.utc)
    for uid in uids:
        session.execute(
            text("""
                INSERT INTO skitak_team_members (team_id, tak_uid, callsign)
                VALUES (:t, :u, :c)
            """),
            {"t": tid, "u": uid, "c": f"CS-{uid}"},
        )
        for i in range(n):
            store_track_point(
                session, _point(sid, uid, start + timedelta(seconds=10 * i), 46.0 + 0.001 * i, speed=1.0 + i)
            )
    return uuid.UUID(sid), tid


def test_session_detail_participants(session):
    sid, tid = _seed(session)
    detail = get_session_detail(session, sid)
    assert detail is not None
    assert detail["name"] == "Replay day"
    assert [t["name"] for t in detail["teams"]] == ["Reds"]

    participants = detail["participants"]
    assert len(participants) == 2
    p = participants[0]
    assert p["callsign"] == "CS-DEV-A"
    assert p["team_id"] == str(tid)
    assert p["point_count"] == 6
    assert float(p["distance_km"]) > 0.5   # 5 × ~111 m
    assert float(p["max_speed_kph"]) == round(6.0 * 3.6, 1)
    assert float(p["max_altitude_m"]) - float(p["min_altitude_m"]) < 1.0


def test_session_detail_unknown(session):
    assert get_session_detail(session, uuid.uuid4()) is None


def test_all_tracks_grouped_and_ordered(session):
    sid, _ = _seed(session)
    tracks = get_session_tracks(session, sid)
    assert set(tracks.keys()) == {"DEV-A", "DEV-B"}
    pts = tracks["DEV-A"]
    assert len(pts) == 6
    assert [p["lat"] for p in pts] == sorted(p["lat"] for p in pts)
    assert pts[0]["speed_ms"] == 1.0 and pts[-1]["speed_ms"] == 6.0


def test_all_tracks_decimation(session):
    sid, _ = _seed(session, uids=("DEV-A",), n=10)
    tracks = get_session_tracks(session, sid, every=3)
    pts = tracks["DEV-A"]
    # rows 1,4,7,10 → 4 points, first point always kept
    assert len(pts) == 4
    assert pts[0]["lat"] == 46.0
