"""
Client management — registered clients who persist across sessions.
Guides add clients once; they're available for assignment in any future session.

All endpoints require an authenticated OTS session (these expose PII and can
mint enrollment credentials).
"""
from __future__ import annotations

import random
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from flask import Blueprint, jsonify, request
from flask_security import auth_required
from opentakserver.extensions import db
from sqlalchemy import text
from sqlalchemy.orm import Session

from .common import parse_uuid, serialise
from .enrollment import CALLSIGN_RE, TOKEN_TTL_HOURS, create_invite_token
from .groups import deactivate_device_user

bp = Blueprint("skitak_clients", __name__, url_prefix="/api/skitak/clients")


# ── CRUD ──────────────────────────────────────────────────────────────────

@bp.get("")
@auth_required()
def list_clients():
    rows = db.session.execute(text("""
        SELECT
            c.id, c.display_name, c.callsign, c.email, c.phone, c.notes,
            c.created_at, c.last_seen_at, c.enrolled_at, c.cert_expires_at,
            c.total_sessions, c.total_distance_km,
            c.tak_uid IS NOT NULL AS has_enrolled
        FROM skitak_clients c
        ORDER BY c.display_name ASC
    """)).mappings().all()
    return jsonify({"clients": [serialise(r) for r in rows]})


@bp.post("")
@auth_required()
def create_client():
    body = request.get_json(force=True)
    if not body.get("display_name"):
        return jsonify({"error": "display_name is required"}), 400

    callsign = body.get("callsign") or _generate_callsign(body["display_name"])
    if not CALLSIGN_RE.match(callsign):
        return jsonify({
            "error": "callsign must be 2-64 characters: letters, digits, '.' or '_'"
        }), 400

    # Ensure callsign is unique — append a number if taken
    base = callsign
    suffix = 1
    while db.session.execute(
        text("SELECT 1 FROM skitak_clients WHERE callsign = :cs"),
        {"cs": callsign}
    ).first():
        callsign = f"{base}{suffix}"
        suffix += 1

    row = db.session.execute(text("""
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
    db.session.commit()
    return jsonify(serialise(row)), 201


@bp.get("/<client_id>")
@auth_required()
def get_client(client_id: str):
    cid = parse_uuid(client_id)
    if not cid:
        return jsonify({"error": "Client not found"}), 404
    client = _fetch_client(db.session, cid)
    if not client:
        return jsonify({"error": "Client not found"}), 404

    # Session history. Distances are computed from per-point deltas in a CTE,
    # partitioned by session — LAG can't live inside SUM, and without the
    # partition the last point of one session would chain into the next.
    sessions = db.session.execute(text("""
        WITH pts AS (
            SELECT
                tp.session_id,
                tp.speed_ms,
                ST_Distance(
                    tp.location,
                    LAG(tp.location) OVER (
                        PARTITION BY tp.session_id ORDER BY tp.recorded_at
                    )
                ) AS dist_m
            FROM skitak_track_points tp
            WHERE tp.tak_uid = (SELECT tak_uid FROM skitak_clients WHERE id = :client_id)
        )
        SELECT
            s.id, s.name, s.activity_type, s.started_at, s.ended_at,
            t.name AS team_name, t.color AS team_color,
            ROUND((COALESCE(SUM(p.dist_m), 0) / 1000.0)::numeric, 2) AS distance_km,
            MAX(p.speed_ms) * 3.6 AS max_speed_kph
        FROM skitak_session_clients sc
        JOIN skitak_sessions s  ON s.id = sc.session_id
        JOIN skitak_teams t     ON t.id = sc.team_id
        LEFT JOIN pts p         ON p.session_id = sc.session_id
        WHERE sc.client_id = :client_id
          AND s.ended_at IS NOT NULL
        GROUP BY s.id, s.name, s.activity_type, s.started_at, s.ended_at,
                 t.name, t.color
        ORDER BY s.started_at DESC
        LIMIT 20
    """), {"client_id": cid}).mappings().all()

    return jsonify({
        **serialise(client),
        "sessions": [serialise(r) for r in sessions],
    })


@bp.patch("/<client_id>")
@auth_required()
def update_client(client_id: str):
    cid = parse_uuid(client_id)
    if not cid:
        return jsonify({"error": "Client not found"}), 404
    body = request.get_json(force=True)
    db.session.execute(text("""
        UPDATE skitak_clients
        SET display_name = COALESCE(:display_name, display_name),
            email        = COALESCE(:email, email),
            phone        = COALESCE(:phone, phone),
            notes        = COALESCE(:notes, notes)
        WHERE id = :id
    """), {
        "id":           cid,
        "display_name": body.get("display_name"),
        "email":        body.get("email"),
        "phone":        body.get("phone"),
        "notes":        body.get("notes"),
    })
    db.session.commit()
    return jsonify({"status": "updated"})


@bp.delete("/<client_id>")
@auth_required()
def delete_client(client_id: str):
    """Delete a client and revoke their device access (deactivates the OTS
    user their certificate authenticates as)."""
    cid = parse_uuid(client_id)
    if not cid:
        return jsonify({"error": "Client not found"}), 404
    client = _fetch_client(db.session, cid)
    if not client:
        return jsonify({"error": "Client not found"}), 404
    revoked = deactivate_device_user(client["callsign"])
    db.session.execute(text("DELETE FROM skitak_clients WHERE id = :id"), {"id": cid})
    db.session.commit()
    return jsonify({"status": "deleted", "device_access_revoked": revoked})


# ── Enrollment ────────────────────────────────────────────────────────────

@bp.post("/<client_id>/enroll")
@auth_required()
def generate_enrollment(client_id: str):
    """Generate an enrollment invite for a known client."""
    cid = parse_uuid(client_id)
    if not cid:
        return jsonify({"error": "Client not found"}), 404
    body = request.get_json(force=True)
    session_id = parse_uuid(body.get("session_id", ""))
    team_id    = parse_uuid(body.get("team_id", ""))
    team_name  = body.get("team_name", "Group")
    team_color = body.get("team_color", "Cyan")

    client = _fetch_client(db.session, cid)
    if not client:
        return jsonify({"error": "Client not found"}), 404

    token = create_invite_token(
        db.session,
        session_id=session_id,
        team_id=team_id,
        team_name=team_name,
        team_color=team_color,
        callsign=client["callsign"],
    )

    # Link client to session if session provided
    if session_id and team_id:
        db.session.execute(text("""
            INSERT INTO skitak_session_clients (session_id, team_id, client_id, invite_token)
            VALUES (:session_id, :team_id, :client_id, :token)
            ON CONFLICT (session_id, client_id) DO UPDATE
            SET team_id = :team_id, invite_token = :token
        """), {
            "session_id": session_id,
            "team_id":    team_id,
            "client_id":  cid,
            "token":      token,
        })
        db.session.commit()

    return jsonify({
        "token":    token,
        "join_url": f"{request.host_url.rstrip('/')}/join/{token}",
        "callsign": client["callsign"],
        "expires_at": (
            datetime.now(timezone.utc) + timedelta(hours=TOKEN_TTL_HOURS)
        ).isoformat(),
    })


# ── Assign clients to a session team ─────────────────────────────────────

@bp.post("/assign")
@auth_required()
def assign_clients():
    """
    Assign one or more known clients to a session team.
    Returns invite URLs for each — guide sends them via WhatsApp/SMS.
    """
    body       = request.get_json(force=True)
    session_id = parse_uuid(body.get("session_id", ""))
    team_id    = parse_uuid(body.get("team_id", ""))
    if not session_id or not team_id:
        return jsonify({"error": "session_id and team_id are required"}), 400
    client_ids = body.get("client_ids", [])
    team_name  = body.get("team_name", "Group")
    team_color = body.get("team_color", "Cyan")

    base_url = request.host_url.rstrip("/")
    results = []

    for client_id in client_ids:
        cid = parse_uuid(client_id)
        client = _fetch_client(db.session, cid) if cid else None
        if not client:
            continue
        token = create_invite_token(
            db.session, session_id, team_id, team_name, team_color,
            callsign=client["callsign"],
        )
        db.session.execute(text("""
            INSERT INTO skitak_session_clients (session_id, team_id, client_id, invite_token)
            VALUES (:session_id, :team_id, :client_id, :token)
            ON CONFLICT (session_id, client_id) DO UPDATE
            SET team_id = :team_id, invite_token = :token
        """), {"session_id": session_id, "team_id": team_id,
               "client_id": cid, "token": token})
        results.append({
            "client_id":    str(cid),
            "display_name": client["display_name"],
            "callsign":     client["callsign"],
            "join_url":     f"{base_url}/join/{token}",
        })

    db.session.commit()
    return jsonify({"assigned": results})


# ── Helpers ───────────────────────────────────────────────────────────────

def _fetch_client(db_session: Session, client_id: uuid.UUID) -> dict[str, Any] | None:
    row = db_session.execute(
        text("SELECT * FROM skitak_clients WHERE id = :id"),
        {"id": client_id}
    ).mappings().first()
    return dict(row) if row else None


def _generate_callsign(display_name: str) -> str:
    """Derive a callsign from the client's name — e.g. 'Alice Smith' → 'AliceS'.
    Restricted to characters valid in OTS usernames and CA file paths."""
    parts = display_name.strip().split()
    if len(parts) >= 2:
        raw = f"{parts[0].capitalize()}{parts[1][0].upper()}"
    elif parts:
        raw = parts[0].capitalize()
    else:
        raw = ""
    cleaned = re.sub(r"[^A-Za-z0-9._]", "", raw)
    return cleaned if len(cleaned) >= 2 else f"Client{random.randint(10, 99)}"
