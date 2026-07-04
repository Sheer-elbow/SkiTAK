"""
Session management — create, start, end, and query SkiTAK sessions.
A session groups a guide with one or more client teams for a single activity.
"""
from __future__ import annotations

import json
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
    session_id = uuid.uuid4()
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
            "metadata": json.dumps(metadata or {}),
        },
    )
    db.commit()
    return str(session_id)


def list_sessions(db: Session, limit: int = 50) -> list[dict[str, Any]]:
    """Most recent sessions with their teams."""
    rows = db.execute(
        text("""
            SELECT s.id, s.name, s.activity_type, s.guide_uid,
                   s.created_at, s.started_at, s.ended_at
            FROM skitak_sessions s
            ORDER BY s.created_at DESC
            LIMIT :limit
        """),
        {"limit": limit},
    ).mappings().all()
    sessions = [dict(r) for r in rows]

    if sessions:
        session_ids = [s["id"] for s in sessions]
        teams = db.execute(
            text("""
                SELECT id, session_id, name, color
                FROM skitak_teams
                WHERE session_id = ANY(:session_ids)
            """),
            {"session_ids": session_ids},
        ).mappings().all()
        members = db.execute(
            text("""
                SELECT tm.team_id, tm.tak_uid, tm.callsign
                FROM skitak_team_members tm
                JOIN skitak_teams t ON t.id = tm.team_id
                WHERE t.session_id = ANY(:session_ids)
            """),
            {"session_ids": session_ids},
        ).mappings().all()
        members_by_team: dict[Any, list[dict[str, Any]]] = {}
        for m in members:
            members_by_team.setdefault(m["team_id"], []).append(
                {"tak_uid": m["tak_uid"], "callsign": m["callsign"]}
            )
        by_session: dict[Any, list[dict[str, Any]]] = {}
        for t in teams:
            team = dict(t)
            team["members"] = members_by_team.get(t["id"], [])
            by_session.setdefault(t["session_id"], []).append(team)
        for s in sessions:
            s["teams"] = by_session.get(s["id"], [])

    return sessions


def start_session(db: Session, session_id: uuid.UUID) -> None:
    db.execute(
        text("UPDATE skitak_sessions SET started_at = :now WHERE id = :id"),
        {"now": datetime.now(timezone.utc), "id": session_id},
    )
    db.commit()


def end_session(db: Session, session_id: uuid.UUID) -> None:
    db.execute(
        text("UPDATE skitak_sessions SET ended_at = :now WHERE id = :id"),
        {"now": datetime.now(timezone.utc), "id": session_id},
    )
    db.commit()


def create_team(
    db: Session,
    session_id: uuid.UUID,
    name: str,
    color: str = "Cyan",
) -> str:
    """Create a team within a session and return its ID."""
    team_id = uuid.uuid4()
    db.execute(
        text("""
            INSERT INTO skitak_teams (id, session_id, name, color)
            VALUES (:id, :session_id, :name, :color)
        """),
        {"id": team_id, "session_id": session_id, "name": name, "color": color},
    )
    db.commit()
    return str(team_id)


def get_team(db: Session, session_id: uuid.UUID, team_id: uuid.UUID) -> dict[str, Any] | None:
    row = db.execute(
        text("""
            SELECT id, session_id, name, color, role
            FROM skitak_teams
            WHERE id = :team_id AND session_id = :session_id
        """),
        {"team_id": team_id, "session_id": session_id},
    ).mappings().first()
    return dict(row) if row else None


def get_session_detail(db: Session, session_id: uuid.UUID) -> dict[str, Any] | None:
    """
    Full session view for history/replay: teams, and per-participant
    statistics computed from the recorded track points.
    """
    session_row = db.execute(
        text("""
            SELECT id, name, activity_type, guide_uid, created_at, started_at, ended_at
            FROM skitak_sessions WHERE id = :session_id
        """),
        {"session_id": session_id},
    ).mappings().first()
    if not session_row:
        return None

    teams = db.execute(
        text("""
            SELECT t.id, t.name, t.color
            FROM skitak_teams t WHERE t.session_id = :session_id
        """),
        {"session_id": session_id},
    ).mappings().all()

    # Per-participant stats. LAG deltas live in a CTE (window functions are
    # not allowed inside aggregates), partitioned per device.
    participants = db.execute(
        text("""
            WITH deltas AS (
                SELECT
                    tp.tak_uid,
                    tp.recorded_at,
                    tp.altitude_m,
                    tp.speed_ms,
                    ST_Distance(
                        tp.location,
                        LAG(tp.location) OVER (
                            PARTITION BY tp.tak_uid ORDER BY tp.recorded_at
                        )
                    ) AS dist_m
                FROM skitak_track_points tp
                WHERE tp.session_id = :session_id
            )
            SELECT
                d.tak_uid,
                COALESCE(MAX(tm.callsign), d.tak_uid)           AS callsign,
                MAX(tm.team_id::text)                           AS team_id,
                COUNT(*)                                        AS point_count,
                MIN(d.recorded_at)                              AS first_at,
                MAX(d.recorded_at)                              AS last_at,
                ROUND((COALESCE(SUM(d.dist_m), 0) / 1000.0)::numeric, 2) AS distance_km,
                ROUND((MAX(d.speed_ms) * 3.6)::numeric, 1)      AS max_speed_kph,
                ROUND(MAX(d.altitude_m)::numeric, 0)            AS max_altitude_m,
                ROUND(MIN(d.altitude_m)::numeric, 0)            AS min_altitude_m
            FROM deltas d
            LEFT JOIN skitak_team_members tm
                   ON tm.tak_uid = d.tak_uid
                  AND tm.team_id IN (SELECT id FROM skitak_teams WHERE session_id = :session_id)
            GROUP BY d.tak_uid
            ORDER BY callsign
        """),
        {"session_id": session_id},
    ).mappings().all()

    return {
        **dict(session_row),
        "teams": [dict(t) for t in teams],
        "participants": [dict(p) for p in participants],
    }


def get_session_summary(db: Session, session_id: uuid.UUID) -> dict[str, Any]:
    """
    Return summary stats for a session.

    Distance is computed from per-point deltas in a CTE first — PostgreSQL
    does not allow window functions (LAG) inside aggregates (SUM).
    """
    row = db.execute(
        text("""
            WITH deltas AS (
                SELECT
                    tp.tak_uid,
                    tp.altitude_m,
                    tp.speed_ms,
                    ST_Distance(
                        tp.location,
                        LAG(tp.location) OVER (
                            PARTITION BY tp.tak_uid ORDER BY tp.recorded_at
                        )
                    ) AS dist_m
                FROM skitak_track_points tp
                WHERE tp.session_id = :session_id
            )
            SELECT
                s.name,
                s.activity_type,
                s.started_at,
                s.ended_at,
                (SELECT COUNT(DISTINCT d.tak_uid) FROM deltas d)          AS participant_count,
                ROUND((COALESCE((SELECT SUM(d.dist_m) FROM deltas d), 0)
                       / 1000.0)::numeric, 2)                             AS total_km,
                (SELECT MAX(d.altitude_m) - MIN(d.altitude_m) FROM deltas d) AS elevation_range_m,
                (SELECT MAX(d.speed_ms) * 3.6 FROM deltas d)              AS max_speed_kph
            FROM skitak_sessions s
            WHERE s.id = :session_id
        """),
        {"session_id": session_id},
    ).mappings().first()

    return dict(row) if row else {}
