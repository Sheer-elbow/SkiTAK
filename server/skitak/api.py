"""
SkiTAK REST API blueprint — mounted at /api/skitak/
Extends OTS with session management, track export, and guide tools.
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request, Response

from .sessions import (
    create_session,
    start_session,
    end_session,
    create_team,
    generate_invite_token,
    get_session_summary,
)
from .tracks import get_session_track, export_gpx

bp = Blueprint("skitak", __name__, url_prefix="/api/skitak")


# ── Sessions ──────────────────────────────────────────────────────────────

@bp.post("/sessions")
def create_session_endpoint():
    body = request.get_json(force=True)
    db = _get_db()
    session_id = create_session(
        db,
        name=body["name"],
        activity_type=body.get("activity_type", "general"),
        guide_uid=body["guide_uid"],
        metadata=body.get("metadata"),
    )
    return jsonify({"session_id": session_id}), 201


@bp.post("/sessions/<session_id>/start")
def start_session_endpoint(session_id: str):
    start_session(_get_db(), session_id)
    return jsonify({"status": "started"}), 200


@bp.post("/sessions/<session_id>/end")
def end_session_endpoint(session_id: str):
    end_session(_get_db(), session_id)
    return jsonify({"status": "ended"}), 200


@bp.get("/sessions/<session_id>/summary")
def session_summary(session_id: str):
    summary = get_session_summary(_get_db(), session_id)
    return jsonify(summary)


# ── Teams ─────────────────────────────────────────────────────────────────

@bp.post("/sessions/<session_id>/teams")
def create_team_endpoint(session_id: str):
    body = request.get_json(force=True)
    team_id = create_team(
        _get_db(),
        session_id=session_id,
        name=body["name"],
        color=body.get("color", "Cyan"),
    )
    return jsonify({"team_id": team_id}), 201


@bp.get("/sessions/<session_id>/teams/<team_id>/invite")
def get_invite_link(session_id: str, team_id: str):
    token = generate_invite_token(session_id, team_id)
    base_url = request.host_url.rstrip("/")
    return jsonify({
        "invite_url": f"{base_url}/join/{token}",
        "qr_url": f"{base_url}/api/skitak/qr?token={token}",
    })


# ── Tracks ────────────────────────────────────────────────────────────────

@bp.get("/sessions/<session_id>/tracks/<tak_uid>")
def get_track(session_id: str, tak_uid: str):
    points = get_session_track(_get_db(), session_id, tak_uid)
    return jsonify(points)


@bp.get("/sessions/<session_id>/tracks/<tak_uid>/gpx")
def download_gpx(session_id: str, tak_uid: str):
    callsign = request.args.get("callsign", tak_uid)
    gpx = export_gpx(_get_db(), session_id, tak_uid, callsign)
    return Response(
        gpx,
        mimetype="application/gpx+xml",
        headers={"Content-Disposition": f"attachment; filename={callsign}.gpx"},
    )


# ── Health ────────────────────────────────────────────────────────────────

@bp.get("/health")
def health():
    return jsonify({"status": "ok"})


# ── Helpers ───────────────────────────────────────────────────────────────

def _get_db():
    from flask import g, current_app
    if "db" not in g:
        from sqlalchemy.orm import Session as SASession
        g.db = SASession(current_app.extensions["sqlalchemy"].engine)
    return g.db
