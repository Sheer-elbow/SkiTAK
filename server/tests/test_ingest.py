"""CoT parsing and firehose track ingestion."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import text

from skitak.enrollment import _consume_token, create_invite_token
from skitak.ingest import ingest_position, parse_cot_position, resolve_active_membership
from skitak.sessions import create_session, create_team, end_session, start_session
from skitak.tracks import get_session_track

SA_EVENT = """<event version="2.0" uid="SKITAK-IOS-ABC" type="a-f-G-U-C" how="m-g"
  time="2026-07-03T10:00:00.000Z" start="2026-07-03T10:00:00.000Z" stale="2026-07-03T10:05:00.000Z">
  <point lat="46.001" lon="7.002" hae="1234.5" ce="4.2" le="6.0"/>
  <detail>
    <contact callsign="SwiftFox42" endpoint="*:-1:stcp"/>
    <__group name="Blue" role="Team Member"/>
    <track speed="3.50" course="270.0"/>
    <status battery="76"/>
  </detail>
</event>"""


def test_parse_sa_event():
    pos = parse_cot_position(SA_EVENT)
    assert pos is not None
    assert pos["uid"] == "SKITAK-IOS-ABC"
    assert pos["callsign"] == "SwiftFox42"
    assert pos["point"]["lat"] == 46.001
    assert pos["point"]["hae"] == 1234.5
    assert pos["detail"]["track"]["speed"] == 3.5
    assert pos["detail"]["status"]["battery"] == 76
    assert pos["time"] == datetime(2026, 7, 3, 10, 0, tzinfo=timezone.utc)


def test_parse_rejects_non_positions():
    assert parse_cot_position("not xml at all") is None
    assert parse_cot_position("<event type='t-x-d-d'><point lat='0' lon='0'/></event>") is None
    # Chat event (b-*) is not a position
    assert parse_cot_position(
        "<event type='b-t-f'><point lat='1' lon='1'/></event>"
    ) is None
    # Placeholder 0,0 points are dropped
    assert parse_cot_position(
        "<event type='a-f-G-U-C'><point lat='0' lon='0'/></event>"
    ) is None


def _enrolled_running_session(session, callsign="SwiftFox42"):
    sid = uuid.UUID(create_session(session, "Run", "trail_run", "GUIDE-1"))
    tid = uuid.UUID(create_team(session, sid, "Blue team", "Blue"))
    token = create_invite_token(session, sid, tid, "Blue team", "Blue")
    _consume_token(session, token, callsign)
    start_session(session, sid)
    return sid, tid


def test_resolve_membership_only_when_running(session):
    sid, tid = _enrolled_running_session(session)
    assert resolve_active_membership(session, "SwiftFox42") == (sid, tid)
    assert resolve_active_membership(session, "Nobody99") is None

    end_session(session, sid)
    assert resolve_active_membership(session, "SwiftFox42") is None


def test_ingest_position_stores_point_and_membership(session):
    sid, tid = _enrolled_running_session(session)
    pos = parse_cot_position(SA_EVENT)

    assert ingest_position(session, pos) is True

    points = get_session_track(session, sid, "SKITAK-IOS-ABC")
    assert len(points) == 1
    assert points[0]["lat"] == 46.001
    assert points[0]["battery_pct"] == 76

    member = session.execute(
        text("SELECT callsign FROM skitak_team_members WHERE team_id = :t AND tak_uid = :u"),
        {"t": tid, "u": "SKITAK-IOS-ABC"},
    ).scalar_one()
    assert member == "SwiftFox42"

    # Unknown callsign is ignored
    stray = dict(pos, callsign="Nobody99")
    assert ingest_position(session, stray) is False
