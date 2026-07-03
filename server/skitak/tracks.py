"""
Track storage — writes CoT position events to PostGIS.

store_track_point() is the persistence primitive; hooking it into OTS's CoT
pipeline (RabbitMQ firehose exchange) is Phase 1 work — see PLAN.md.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any
from xml.sax.saxutils import escape

from sqlalchemy import text
from sqlalchemy.orm import Session


def store_track_point(db: Session, cot_event: dict[str, Any]) -> None:
    """Persist a single CoT position event as a track point."""
    point = cot_event.get("point", {})
    detail = cot_event.get("detail", {})
    track = detail.get("track", {})
    status = detail.get("status", {})

    lat = point.get("lat")
    lon = point.get("lon")
    if lat is None or lon is None:
        return

    db.execute(
        text("""
            INSERT INTO skitak_track_points
                (session_id, tak_uid, recorded_at, location,
                 altitude_m, speed_ms, course_deg, accuracy_m,
                 battery_pct, extra)
            VALUES
                (:session_id, :tak_uid, :recorded_at,
                 ST_SetSRID(ST_MakePoint(:lon, :lat), 4326),
                 :altitude_m, :speed_ms, :course_deg, :accuracy_m,
                 :battery_pct, :extra)
        """),
        {
            "session_id": cot_event.get("session_id"),
            "tak_uid": cot_event.get("uid"),
            "recorded_at": cot_event.get("time", datetime.now(timezone.utc)),
            "lat": lat,
            "lon": lon,
            "altitude_m": point.get("hae"),
            "speed_ms": track.get("speed"),
            "course_deg": track.get("course"),
            "accuracy_m": point.get("ce"),
            "battery_pct": status.get("battery"),
            "extra": json.dumps({}),
        },
    )
    db.commit()


def get_session_track(
    db: Session,
    session_id: uuid.UUID,
    tak_uid: str,
) -> list[dict[str, Any]]:
    """Return ordered track points for a single device in a session."""
    rows = db.execute(
        text("""
            SELECT
                recorded_at,
                ST_Y(location::geometry) AS lat,
                ST_X(location::geometry) AS lon,
                altitude_m,
                speed_ms,
                course_deg,
                heart_rate_bpm,
                battery_pct
            FROM skitak_track_points
            WHERE session_id = :session_id
              AND tak_uid    = :tak_uid
            ORDER BY recorded_at ASC
        """),
        {"session_id": session_id, "tak_uid": tak_uid},
    ).mappings().all()

    return [dict(r) for r in rows]


def export_gpx(
    db: Session,
    session_id: uuid.UUID,
    tak_uid: str,
    callsign: str,
) -> str:
    """Generate a GPX 1.1 string for a device's track in a session."""
    points = get_session_track(db, session_id, tak_uid)
    if not points:
        return ""

    trkpts = "\n".join(
        f'    <trkpt lat="{p["lat"]}" lon="{p["lon"]}">'
        f'<ele>{p["altitude_m"] or 0:.1f}</ele>'
        f'<time>{_iso(p["recorded_at"])}</time>'
        f'</trkpt>'
        for p in points
    )

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="SkiTAK"
     xmlns="http://www.topografix.com/GPX/1/1">
  <trk>
    <name>{escape(callsign)}</name>
    <trkseg>
{trkpts}
    </trkseg>
  </trk>
</gpx>"""


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)
