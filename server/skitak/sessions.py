"""
Session management — create, start, end, and query SkiTAK sessions.
A session groups a guide with one or more client teams for a single activity.
"""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


def create_session(
    db: Session,
    name: str,
    activity_type: str,
    guide_uid: str,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Create a new session and return its ID."""
    session_id = str(uuid.uuid4())
    db.execute(
        text("""
            INSERT INTO skitak_sessions (id, name, activity_type, guide_uid, metadata)
            VALUES (:id, :name, :activity_type, :guide_uid, :metadata)
        """),
        {
            "id": session_id,
            "name": name,
            "activity_type": activity_type,
            "guide_uid": guide_uid,
            "metadata": metadata or {},
        },
    )
    db.commit()
    return session_id


def start_session(db: Session, session_id: str) -> None:
    db.execute(
        text("UPDATE skitak_sessions SET started_at = :now WHERE id = :id"),
        {"now": datetime.now(timezone.utc), "id": session_id},
    )
    db.commit()


def end_session(db: Session, session_id: str) -> None:
    db.execute(
        text("UPDATE skitak_sessions SET ended_at = :now WHERE id = :id"),
        {"now": datetime.now(timezone.utc), "id": session_id},
    )
    db.commit()


def create_team(
    db: Session,
    session_id: str,
    name: str,
    color: str = "Cyan",
) -> str:
    """Create a team within a session and return its ID."""
    team_id = str(uuid.uuid4())
    db.execute(
        text("""
            INSERT INTO skitak_teams (id, session_id, name, color)
            VALUES (:id, :session_id, :name, :color)
        """),
        {"id": team_id, "session_id": session_id, "name": name, "color": color},
    )
    db.commit()
    return team_id


def generate_invite_token(session_id: str, team_id: str) -> str:
    """
    Generate a one-time-use invite token for the join deep link.
    Format: https://server/join/<token>
    Token encodes session+team; server validates and issues cert.
    """
    # In production, store token→(session_id, team_id) in Redis/DB with TTL
    raw = f"{session_id}:{team_id}:{secrets.token_urlsafe(16)}"
    return raw


def get_session_summary(db: Session, session_id: str) -> dict[str, Any]:
    """Return summary stats for a completed session."""
    row = db.execute(
        text("""
            SELECT
                s.name,
                s.activity_type,
                s.started_at,
                s.ended_at,
                COUNT(DISTINCT tp.tak_uid)                    AS participant_count,
                ROUND(SUM(
                    ST_Distance(
                        LAG(tp.location) OVER (
                            PARTITION BY tp.tak_uid ORDER BY tp.recorded_at
                        ),
                        tp.location
                    )
                ) / 1000.0, 2)                                AS total_km,
                MAX(tp.altitude_m) - MIN(tp.altitude_m)       AS elevation_range_m,
                MAX(tp.speed_ms) * 3.6                        AS max_speed_kph
            FROM skitak_sessions s
            LEFT JOIN skitak_track_points tp ON tp.session_id = s.id
            WHERE s.id = :session_id
            GROUP BY s.name, s.activity_type, s.started_at, s.ended_at
        """),
        {"session_id": session_id},
    ).mappings().first()

    return dict(row) if row else {}
