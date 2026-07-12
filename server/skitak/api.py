"""
SkiTAK REST API blueprint — mounted at /api/skitak/
Extends OTS with session management, track export, and guide tools.

All guide-facing endpoints require an authenticated OTS session/token
(flask_security.auth_required) — enrollment endpoints live in enrollment.py
and are token-gated instead.
"""
from __future__ import annotations

from flask import Blueprint, Response, current_app, jsonify, request
from flask_security import auth_required, current_user
from opentakserver.extensions import db
from sqlalchemy import text

from .common import parse_uuid, safe_filename, serialise
from .enrollment import TOKEN_TTL_HOURS, create_invite_token
from .geofence import (
    GeofenceError,
    create_geofence,
    delete_geofence,
    list_geofences,
    recent_events,
)
from .groups import ensure_team_group, group_name_for_team, revoke_session_devices
from .routes import (
    GpxError,
    broadcast_route_to_teams,
    delete_route,
    get_route,
    parse_gpx,
    route_cot_xml,
    store_route,
)
from .sessions import (
    create_session,
    create_team,
    end_session,
    get_session_detail,
    get_session_summary,
    get_team,
    list_sessions,
    start_session,
)
from .tracks import export_gpx, get_session_track, get_session_tracks

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
    """
    End a session. By default this also deactivates the device accounts that
    were enrolled through this session's invites, so ex-clients stop having
    live access — pass {"revoke_devices": false} to keep them connected.
    """
    sid = parse_uuid(session_id)
    if not sid:
        return jsonify({"error": "Session not found"}), 404
    body = request.get_json(silent=True) or {}
    end_session(db.session, sid)
    revoked: list[str] = []
    if body.get("revoke_devices", True):
        revoked = revoke_session_devices(sid)
    return jsonify({"status": "ended", "revoked_devices": revoked}), 200


@bp.get("/sessions/<session_id>")
@auth_required()
def session_detail(session_id: str):
    """Session history/replay view: teams + per-participant track stats."""
    sid = parse_uuid(session_id)
    if not sid:
        return jsonify({"error": "Session not found"}), 404
    detail = get_session_detail(db.session, sid)
    if detail is None:
        return jsonify({"error": "Session not found"}), 404
    detail["teams"] = [serialise(t) for t in detail["teams"]]
    detail["participants"] = [serialise(p) for p in detail["participants"]]
    return jsonify(serialise(detail))


@bp.get("/sessions/<session_id>/tracks")
@auth_required()
def all_session_tracks(session_id: str):
    """All participants' tracks, keyed by device UID — feeds track replay.
    ?every=N keeps every Nth point per device (decimation)."""
    sid = parse_uuid(session_id)
    if not sid:
        return jsonify({"error": "Session not found"}), 404
    try:
        every = max(1, min(int(request.args.get("every", 1)), 100))
    except ValueError:
        every = 1
    tracks = get_session_tracks(db.session, sid, every=every)
    return jsonify({
        "tracks": {uid: [serialise(p) for p in pts] for uid, pts in tracks.items()}
    })


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
    # Back the team with an OTS group and put the creating guide in it, so
    # enrolled devices and the guide share CoT visibility.
    ensure_team_group(parse_uuid(team_id), guide_user=current_user)
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


# ── Geofences ─────────────────────────────────────────────────────────────

@bp.post("/sessions/<session_id>/geofences")
@auth_required()
def create_geofence_endpoint(session_id: str):
    """
    Create a fence. Body: {name, fence_type: keep_in|keep_out,
    polygon: [{lat, lon}, ...]} or {..., circle: {lat, lon, radius_m}}.
    """
    sid = parse_uuid(session_id)
    if not sid:
        return jsonify({"error": "Session not found"}), 404
    body = request.get_json(force=True)
    try:
        fence_id = create_geofence(
            db.session,
            sid,
            name=body.get("name", ""),
            fence_type=body.get("fence_type", "keep_in"),
            polygon=body.get("polygon"),
            circle=body.get("circle"),
            created_by=getattr(current_user, "username", None),
        )
    except GeofenceError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"geofence_id": fence_id}), 201


@bp.get("/sessions/<session_id>/geofences")
@auth_required()
def list_geofences_endpoint(session_id: str):
    sid = parse_uuid(session_id)
    if not sid:
        return jsonify({"error": "Session not found"}), 404
    return jsonify({"geofences": [serialise(f) for f in list_geofences(db.session, sid)]})


@bp.delete("/sessions/<session_id>/geofences/<fence_id>")
@auth_required()
def delete_geofence_endpoint(session_id: str, fence_id: str):
    sid, fid = parse_uuid(session_id), parse_uuid(fence_id)
    if not sid or not fid:
        return jsonify({"error": "Geofence not found"}), 404
    if not delete_geofence(db.session, sid, fid):
        return jsonify({"error": "Geofence not found"}), 404
    return jsonify({"status": "deleted"})


@bp.get("/sessions/<session_id>/geofence-events")
@auth_required()
def geofence_events_endpoint(session_id: str):
    sid = parse_uuid(session_id)
    if not sid:
        return jsonify({"error": "Session not found"}), 404
    return jsonify({"events": [serialise(e) for e in recent_events(db.session, sid)]})


# ── Planned route ─────────────────────────────────────────────────────────

@bp.post("/sessions/<session_id>/route")
@auth_required()
def upload_route(session_id: str):
    """
    Upload a planned route as GPX (multipart field `gpx` or the raw request
    body). Stored for the dashboard and broadcast to the session's team
    devices as a TAK route CoT.
    """
    sid = parse_uuid(session_id)
    if not sid:
        return jsonify({"error": "Session not found"}), 404

    if "gpx" in request.files:
        data = request.files["gpx"].read()
    else:
        data = request.get_data()
    if not data:
        return jsonify({"error": "No GPX data supplied"}), 400

    try:
        name, points = parse_gpx(data)
    except GpxError as e:
        return jsonify({"error": str(e)}), 400

    route_id = store_route(
        db.session, sid, name, points,
        uploaded_by=getattr(current_user, "username", None),
    )

    # Broadcast to connected team devices (best-effort — the stored route
    # still reaches devices enrolling later via the dashboard/map).
    teams = db.session.execute(
        text("SELECT id FROM skitak_teams WHERE session_id = :sid"), {"sid": sid}
    ).scalars().all()
    broadcast_count = 0
    try:
        broadcast_count = broadcast_route_to_teams(
            rabbit_host=current_app.config.get("OTS_RABBITMQ_SERVER_ADDRESS", "127.0.0.1"),
            rabbit_user=current_app.config.get("OTS_RABBITMQ_USERNAME", "guest"),
            rabbit_password=current_app.config.get("OTS_RABBITMQ_PASSWORD", "guest"),
            group_names=[group_name_for_team(t) for t in teams],
            cot_xml=route_cot_xml(name, points, route_uid=f"skitak-route-{route_id}"),
        )
    except Exception as e:
        current_app.logger.error(f"SkiTAK: route broadcast failed: {e}")

    return jsonify({
        "route_id": route_id,
        "name": name,
        "point_count": len(points),
        "broadcast_teams": broadcast_count,
    }), 201


@bp.get("/sessions/<session_id>/route")
@auth_required()
def get_route_endpoint(session_id: str):
    sid = parse_uuid(session_id)
    if not sid:
        return jsonify({"error": "Session not found"}), 404
    route = get_route(db.session, sid)
    if route is None:
        return jsonify({"route": None})
    return jsonify({"route": serialise(route)})


@bp.delete("/sessions/<session_id>/route")
@auth_required()
def delete_route_endpoint(session_id: str):
    sid = parse_uuid(session_id)
    if not sid:
        return jsonify({"error": "Session not found"}), 404
    deleted = delete_route(db.session, sid)
    return jsonify({"status": "deleted" if deleted else "no route"})


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
