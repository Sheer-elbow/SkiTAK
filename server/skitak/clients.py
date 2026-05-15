"""
Client management — registered clients who persist across sessions.
Guides add clients once; they're available for assignment in any future session.
"""
from __future__ import annotations

import random
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from flask import Blueprint, jsonify, request
from sqlalchemy import text
from sqlalchemy.orm import Session

from .enrollment import create_invite_token, TOKEN_TTL_HOURS

bp = Blueprint("clients", __name__, url_prefix="/api/skitak/clients")


# ── CRUD ──────────────────────────────────────────────────────────────────

@bp.get("")
def list_clients():
    db = _get_db()
    rows = db.execute(text("""
        SELECT
            c.id, c.display_name, c.callsign, c.email, c.phone, c.notes,
            c.created_at, c.last_seen_at, c.enrolled_at, c.cert_expires_at,
            c.total_sessions, c.total_distance_km,
            c.tak_uid IS NOT NULL AS has_enrolled
        FROM skitak_clients c
        ORDER BY c.display_name ASC
    """)).mappings().all()
    return jsonify({"clients": [_serialise(r) for r in rows]})


@bp.post("")
def create_client():
    body = request.get_json(force=True)
    if not body.get("display_name"):
        return jsonify({"error": "display_name is required"}), 400

    callsign = body.get("callsign") or _generate_callsign(body["display_name"])
    db = _get_db()

    # Ensure callsign is unique — append a number if taken
    base = callsign
    suffix = 1
    while db.execute(
        text("SELECT 1 FROM skitak_clients WHERE callsign = :cs"),
        {"cs": callsign}
    ).first():
        callsign = f"{base}{suffix}"
        suffix += 1

    row = db.execute(text("""
        INSERT INTO skitak_clients (display_name, callsign, email, phone, notes)
        VALUES (:display_name, :callsign, :email, :phone, :notes)
        RETURNING id, display_name, callsign, email, phone, notes,
                  created_at, total_sessions, total_distance_km
    """), {
        "display_name": body["display_name"],
        "callsign":     callsign,
        "email":        body.get("email"),
        "phone":        body.get("phone"),
        "notes":        body.get("notes"),
    }).mappings().first()
    db.commit()
    return jsonify(_serialise(row)), 201


@bp.get("/<client_id>")
def get_client(client_id: str):
    db = _get_db()
    client = _fetch_client(db, client_id)
    if not client:
        return jsonify({"error": "Client not found"}), 404

    # Session history
    sessions = db.execute(text("""
        SELECT
            s.id, s.name, s.activity_type, s.started_at, s.ended_at,
            t.name AS team_name, t.color AS team_color,
            ROUND(SUM(
                ST_Distance(
                    LAG(tp.location) OVER (ORDER BY tp.recorded_at),
                    tp.location
                )
            ) / 1000.0, 2) AS distance_km,
            MAX(tp.speed_ms) * 3.6 AS max_speed_kph
        FROM skitak_session_clients sc
        JOIN skitak_sessions s  ON s.id = sc.session_id
        JOIN skitak_teams t     ON t.id = sc.team_id
        LEFT JOIN skitak_track_points tp
               ON tp.session_id = sc.session_id
              AND tp.tak_uid    = (
                  SELECT tak_uid FROM skitak_clients WHERE id = :client_id
              )
        WHERE sc.client_id = :client_id
          AND s.ended_at IS NOT NULL
        GROUP BY s.id, s.name, s.activity_type, s.started_at, s.ended_at,
                 t.name, t.color
        ORDER BY s.started_at DESC
        LIMIT 20
    """), {"client_id": client_id}).mappings().all()

    return jsonify({
        **_serialise(client),
        "sessions": [dict(r) for r in sessions],
    })


@bp.patch("/<client_id>")
def update_client(client_id: str):
    body = request.get_json(force=True)
    db = _get_db()
    db.execute(text("""
        UPDATE skitak_clients
        SET display_name = COALESCE(:display_name, display_name),
            email        = COALESCE(:email, email),
            phone        = COALESCE(:phone, phone),
            notes        = COALESCE(:notes, notes)
        WHERE id = :id
    """), {
        "id":           client_id,
        "display_name": body.get("display_name"),
        "email":        body.get("email"),
        "phone":        body.get("phone"),
        "notes":        body.get("notes"),
    })
    db.commit()
    return jsonify({"status": "updated"})


@bp.delete("/<client_id>")
def delete_client(client_id: str):
    db = _get_db()
    db.execute(text("DELETE FROM skitak_clients WHERE id = :id"), {"id": client_id})
    db.commit()
    return jsonify({"status": "deleted"})


# ── Enrollment ────────────────────────────────────────────────────────────

@bp.post("/<client_id>/enroll")
def generate_enrollment(client_id: str):
    """
    Generate an enrollment invite for a known client.
    If the client is already enrolled and their cert is still valid, returns
    a renewal link instead (preserving their callsign and history).
    """
    body = request.get_json(force=True)
    session_id = body.get("session_id")
    team_id    = body.get("team_id")
    team_name  = body.get("team_name", "Group")
    team_color = body.get("team_color", "Cyan")

    db = _get_db()
    client = _fetch_client(db, client_id)
    if not client:
        return jsonify({"error": "Client not found"}), 404

    token = create_invite_token(
        db,
        session_id=session_id or "standalone",
        team_id=team_id or "standalone",
        team_name=team_name,
        team_color=team_color,
    )

    # Link client to session if session provided
    if session_id and team_id:
        db.execute(text("""
            INSERT INTO skitak_session_clients (session_id, team_id, client_id, invite_token)
            VALUES (:session_id, :team_id, :client_id, :token)
            ON CONFLICT (session_id, client_id) DO UPDATE
            SET team_id = :team_id, invite_token = :token
        """), {
            "session_id": session_id,
            "team_id":    team_id,
            "client_id":  client_id,
            "token":      token,
        })
        db.commit()

    server_host = request.host.split(":")[0]
    join_url    = f"https://{server_host}/join/{token}"

    return jsonify({
        "token":    token,
        "join_url": join_url,
        "callsign": client["callsign"],
        "expires_at": (
            datetime.now(timezone.utc) + timedelta(hours=TOKEN_TTL_HOURS)
        ).isoformat(),
    })


# ── Assign clients to a session team ─────────────────────────────────────

@bp.post("/assign")
def assign_clients():
    """
    Assign one or more known clients to a session team.
    Returns invite URLs for each — guide sends them via WhatsApp/SMS.
    """
    body       = request.get_json(force=True)
    client_ids = body.get("client_ids", [])
    session_id = body["session_id"]
    team_id    = body["team_id"]
    team_name  = body.get("team_name", "Group")
    team_color = body.get("team_color", "Cyan")

    db = _get_db()
    server_host = request.host.split(":")[0]
    results = []

    for client_id in client_ids:
        client = _fetch_client(db, client_id)
        if not client:
            continue
        token = create_invite_token(db, session_id, team_id, team_name, team_color)
        db.execute(text("""
            INSERT INTO skitak_session_clients (session_id, team_id, client_id, invite_token)
            VALUES (:session_id, :team_id, :client_id, :token)
            ON CONFLICT (session_id, client_id) DO UPDATE
            SET team_id = :team_id, invite_token = :token
        """), {"session_id": session_id, "team_id": team_id,
               "client_id": client_id, "token": token})
        results.append({
            "client_id":    client_id,
            "display_name": client["display_name"],
            "callsign":     client["callsign"],
            "join_url":     f"https://{server_host}/join/{token}",
        })

    db.commit()
    return jsonify({"assigned": results})


# ── Helpers ───────────────────────────────────────────────────────────────

def _fetch_client(db: Session, client_id: str) -> dict[str, Any] | None:
    row = db.execute(
        text("SELECT * FROM skitak_clients WHERE id = :id"),
        {"id": client_id}
    ).mappings().first()
    return dict(row) if row else None


def _serialise(row: Any) -> dict[str, Any]:
    d = dict(row)
    for k, v in d.items():
        if isinstance(v, datetime):
            d[k] = v.isoformat()
    return d


def _generate_callsign(display_name: str) -> str:
    """Derive a callsign from the client's name — e.g. 'Alice Smith' → 'AliceS'."""
    parts = display_name.strip().split()
    if len(parts) >= 2:
        return f"{parts[0].capitalize()}{parts[1][0].upper()}"
    return parts[0].capitalize() if parts else f"Client{random.randint(10, 99)}"


def _get_db():
    from flask import g, current_app
    if "db" not in g:
        from sqlalchemy.orm import Session as SASession
        g.db = SASession(current_app.extensions["sqlalchemy"].engine)
    return g.db
