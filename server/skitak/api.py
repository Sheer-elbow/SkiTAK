"""
SkiTAK REST API blueprint — mounted at /api/skitak/
Extends OTS with session management, track export, and guide tools.

All guide-facing endpoints require an authenticated OTS session/token
(flask_security.auth_required) — enrollment endpoints live in enrollment.py
and are token-gated instead.
"""
from __future__ import annotations

from flask import Blueprint, Response, jsonify, request
from flask_security import auth_required
from opentakserver.extensions import db

from .common import parse_uuid, safe_filename, serialise
from .enrollment import TOKEN_TTL_HOURS, create_invite_token
from .sessions import (
    create_session,
    create_team,
    end_session,
    get_session_summary,
    get_team,
    list_sessions,
    start_session,
)
from .tracks import export_gpx, get_session_track

bp = Blueprint("skitak", __name__, url_prefix="/api/skitak")


# ── Sessions ──────────────────────────────────────────────────────────────

@bp.get("/sessions")
@auth_required()
def list_sessions_endpoint():
    return jsonify({"sessions": [serialise(s) for s in list_sessions(db.session)]})


@bp.post("/sessions")
@auth_required()
def create_session_endpoint():
    body = request.get_json(force=True)
    if not body.get("name") or not body.get("guide_uid"):
        return jsonify({"error": "name and guide_uid are required"}), 400
    session_id = create_session(
        db.session,
        name=body["name"],
        activity_type=body.get("activity_type", "general"),
        guide_uid=body["guide_uid"],
        metadata=body.get("metadata"),
    )
    return jsonify({"session_id": session_id}), 201


@bp.post("/sessions/<session_id>/start")
@auth_required()
def start_session_endpoint(session_id: str):
    sid = parse_uuid(session_id)
    if not sid:
        return jsonify({"error": "Session not found"}), 404
    start_session(db.session, sid)
    return jsonify({"status": "started"}), 200


@bp.post("/sessions/<session_id>/end")
@auth_required()
def end_session_endpoint(session_id: str):
    sid = parse_uuid(session_id)
    if not sid:
        return jsonify({"error": "Session not found"}), 404
    end_session(db.session, sid)
    return jsonify({"status": "ended"}), 200


@bp.get("/sessions/<session_id>/summary")
@auth_required()
def session_summary(session_id: str):
    sid = parse_uuid(session_id)
    if not sid:
        return jsonify({"error": "Session not found"}), 404
    summary = get_session_summary(db.session, sid)
    if not summary:
        return jsonify({"error": "Session not found"}), 404
    return jsonify(serialise(summary))


# ── Teams ─────────────────────────────────────────────────────────────────

@bp.post("/sessions/<session_id>/teams")
@auth_required()
def create_team_endpoint(session_id: str):
    sid = parse_uuid(session_id)
    if not sid:
        return jsonify({"error": "Session not found"}), 404
    body = request.get_json(force=True)
    if not body.get("name"):
        return jsonify({"error": "name is required"}), 400
    team_id = create_team(
        db.session,
        session_id=sid,
        name=body["name"],
        color=body.get("color", "Cyan"),
    )
    return jsonify({"team_id": team_id}), 201


@bp.get("/sessions/<session_id>/teams/<team_id>/invite")
@auth_required()
def get_invite_link(session_id: str, team_id: str):
    sid, tid = parse_uuid(session_id), parse_uuid(team_id)
    if not sid or not tid:
        return jsonify({"error": "Team not found"}), 404
    team = get_team(db.session, sid, tid)
    if not team:
        return jsonify({"error": "Team not found"}), 404

    token = create_invite_token(
        db.session,
        session_id=sid,
        team_id=tid,
        team_name=team["name"],
        team_color=team["color"],
    )
    base_url = request.host_url.rstrip("/")
    return jsonify({
        "invite_url": f"{base_url}/join/{token}",
        "expires_in_hours": TOKEN_TTL_HOURS,
    })


# ── Tracks ────────────────────────────────────────────────────────────────

@bp.get("/sessions/<session_id>/tracks/<tak_uid>")
@auth_required()
def get_track(session_id: str, tak_uid: str):
    sid = parse_uuid(session_id)
    if not sid:
        return jsonify({"error": "Session not found"}), 404
    points = get_session_track(db.session, sid, tak_uid)
    return jsonify([serialise(p) for p in points])


@bp.get("/sessions/<session_id>/tracks/<tak_uid>/gpx")
@auth_required()
def download_gpx(session_id: str, tak_uid: str):
    sid = parse_uuid(session_id)
    if not sid:
        return jsonify({"error": "Session not found"}), 404
    callsign = request.args.get("callsign", tak_uid)
    gpx = export_gpx(db.session, sid, tak_uid, callsign)
    if not gpx:
        return jsonify({"error": "No track points for this device in this session"}), 404
    filename = safe_filename(callsign)
    return Response(
        gpx,
        mimetype="application/gpx+xml",
        headers={"Content-Disposition": f'attachment; filename="{filename}.gpx"'},
    )


# ── Health ────────────────────────────────────────────────────────────────

@bp.get("/health")
def health():
    return jsonify({"status": "ok"})
