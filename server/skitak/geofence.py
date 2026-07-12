"""
Geofences — spatial zones with live violation alerts.

Two kinds:
  keep_in   a boundary; a device OUTSIDE it is in violation
            ("client left the piste/paddock")
  keep_out  a hazard zone; a device INSIDE it is in violation
            ("client entered the closed couloir")

The track ingest worker feeds every stored position through
GeofenceMonitor.check(), which detects *transitions* (safe → violating and
back) so a guide gets one alert per crossing, not one per GPS fix. Events are
persisted to skitak_geofence_events and pushed to the dashboard over
Socket.IO.
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any, Callable

from opentakserver.extensions import logger
from sqlalchemy import text
from sqlalchemy.orm import Session

FENCE_TYPES = ("keep_in", "keep_out")
FENCE_CACHE_TTL_S = 30


class GeofenceError(ValueError):
    pass


# ── CRUD ──────────────────────────────────────────────────────────────────

def create_geofence(
    db: Session,
    session_id: uuid.UUID,
    name: str,
    fence_type: str,
    polygon: list[dict[str, float]] | None = None,
    circle: dict[str, float] | None = None,
    created_by: str | None = None,
) -> str:
    """
    Create a fence from either a polygon ([{lat, lon}, ...], ≥3 vertices) or
    a circle ({lat, lon, radius_m}), which is buffered into a polygon so the
    violation check is uniform.
    """
    if fence_type not in FENCE_TYPES:
        raise GeofenceError(f"fence_type must be one of {FENCE_TYPES}")
    if not name or not name.strip():
        raise GeofenceError("name is required")

    fence_id = uuid.uuid4()
    params: dict[str, Any] = {
        "id": fence_id,
        "session_id": session_id,
        "name": name.strip(),
        "fence_type": fence_type,
        "created_by": created_by,
    }

    if circle is not None:
        lat, lon = _valid_coord(circle.get("lat"), circle.get("lon"))
        radius = float(circle.get("radius_m", 0))
        if not 10 <= radius <= 100_000:
            raise GeofenceError("radius_m must be between 10 and 100000")
        geometry_sql = """
            ST_Buffer(ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, :radius)
        """
        params.update({"lat": lat, "lon": lon, "radius": radius})
    elif polygon is not None:
        if len(polygon) < 3:
            raise GeofenceError("polygon needs at least 3 points")
        if len(polygon) > 500:
            raise GeofenceError("polygon has too many points (max 500)")
        ring = [_valid_coord(p.get("lat"), p.get("lon")) for p in polygon]
        if ring[0] != ring[-1]:
            ring.append(ring[0])  # close the ring
        wkt_ring = ", ".join(f"{lon} {lat}" for lat, lon in ring)
        geometry_sql = "ST_GeogFromText(:wkt)"
        params["wkt"] = f"POLYGON(({wkt_ring}))"
    else:
        raise GeofenceError("either polygon or circle is required")

    db.execute(
        text(f"""
            INSERT INTO skitak_geofences (id, session_id, name, fence_type, geometry, created_by)
            VALUES (:id, :session_id, :name, :fence_type, {geometry_sql}, :created_by)
        """),
        params,
    )
    db.commit()
    return str(fence_id)


def list_geofences(db: Session, session_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = db.execute(
        text("""
            SELECT id, name, fence_type, created_by, created_at, active,
                   ST_AsGeoJSON(geometry::geometry) AS geojson
            FROM skitak_geofences
            WHERE session_id = :session_id
            ORDER BY created_at
        """),
        {"session_id": session_id},
    ).mappings().all()
    fences = []
    for row in rows:
        fence = dict(row)
        geometry = json.loads(fence.pop("geojson"))
        fence["points"] = [{"lat": c[1], "lon": c[0]} for c in geometry["coordinates"][0]]
        fences.append(fence)
    return fences


def delete_geofence(db: Session, session_id: uuid.UUID, fence_id: uuid.UUID) -> bool:
    result = db.execute(
        text("""
            DELETE FROM skitak_geofences
            WHERE id = :fence_id AND session_id = :session_id
        """),
        {"fence_id": fence_id, "session_id": session_id},
    )
    db.commit()
    return result.rowcount > 0


def recent_events(db: Session, session_id: uuid.UUID, limit: int = 50) -> list[dict[str, Any]]:
    rows = db.execute(
        text("""
            SELECT e.id, e.geofence_id, g.name AS geofence_name, g.fence_type,
                   e.tak_uid, e.callsign, e.event_type, e.occurred_at,
                   ST_Y(e.location::geometry) AS lat, ST_X(e.location::geometry) AS lon
            FROM skitak_geofence_events e
            JOIN skitak_geofences g ON g.id = e.geofence_id
            WHERE e.session_id = :session_id
            ORDER BY e.occurred_at DESC
            LIMIT :limit
        """),
        {"session_id": session_id, "limit": limit},
    ).mappings().all()
    return [dict(r) for r in rows]


# ── Violation detection ───────────────────────────────────────────────────

def active_fences_with_containment(
    db: Session, session_id: uuid.UUID, lat: float, lon: float
) -> list[dict[str, Any]]:
    """Active fences for the session, each with whether the point is inside."""
    rows = db.execute(
        text("""
            SELECT id, name, fence_type,
                   ST_Covers(
                       geometry,
                       ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography
                   ) AS inside
            FROM skitak_geofences
            WHERE session_id = :session_id AND active
        """),
        {"session_id": session_id, "lat": lat, "lon": lon},
    ).mappings().all()
    return [dict(r) for r in rows]


class GeofenceMonitor:
    """
    Transition detector. Keeps per-(fence, device) violation state in memory,
    persists each transition, and calls `emit` with the event payload so the
    dashboard hears about it immediately.

    State is process-local: after a server restart the first violating fix
    re-alerts once, which is the safe failure mode.
    """

    def __init__(self, emit: Callable[[dict[str, Any]], None] | None = None):
        self._emit = emit
        self._violating: dict[tuple[str, str], bool] = {}
        self._fence_count_cache: dict[str, tuple[int, float]] = {}

    def session_has_fences(self, db: Session, session_id: uuid.UUID) -> bool:
        """Cheap cached pre-filter so fence-less sessions skip spatial SQL."""
        key = str(session_id)
        now = time.monotonic()
        cached = self._fence_count_cache.get(key)
        if cached is not None and cached[1] > now:
            return cached[0] > 0
        count = db.execute(
            text("SELECT COUNT(*) FROM skitak_geofences WHERE session_id = :s AND active"),
            {"s": session_id},
        ).scalar_one()
        self._fence_count_cache[key] = (count, now + FENCE_CACHE_TTL_S)
        return count > 0

    def check(
        self,
        db: Session,
        session_id: uuid.UUID,
        tak_uid: str,
        callsign: str | None,
        lat: float,
        lon: float,
    ) -> list[dict[str, Any]]:
        """Evaluate one position; persist + emit any transitions. Returns them."""
        if not self.session_has_fences(db, session_id):
            return []

        transitions = []
        for fence in active_fences_with_containment(db, session_id, lat, lon):
            violating = (not fence["inside"]) if fence["fence_type"] == "keep_in" else bool(fence["inside"])
            key = (str(fence["id"]), tak_uid)
            previous = self._violating.get(key, False)
            if violating == previous:
                continue
            self._violating[key] = violating

            event_type = "violation" if violating else "cleared"
            db.execute(
                text("""
                    INSERT INTO skitak_geofence_events
                        (geofence_id, session_id, tak_uid, callsign, event_type, location)
                    VALUES (:fence_id, :session_id, :tak_uid, :callsign, :event_type,
                            ST_SetSRID(ST_MakePoint(:lon, :lat), 4326))
                """),
                {
                    "fence_id": fence["id"],
                    "session_id": session_id,
                    "tak_uid": tak_uid,
                    "callsign": callsign,
                    "event_type": event_type,
                    "lat": lat,
                    "lon": lon,
                },
            )
            db.commit()

            payload = {
                "geofence_id": str(fence["id"]),
                "geofence_name": fence["name"],
                "fence_type": fence["fence_type"],
                "event_type": event_type,
                "session_id": str(session_id),
                "tak_uid": tak_uid,
                "callsign": callsign,
                "lat": lat,
                "lon": lon,
            }
            transitions.append(payload)
            who = callsign or tak_uid
            if event_type == "violation":
                verb = "left" if fence["fence_type"] == "keep_in" else "entered"
                logger.warning(f"SkiTAK geofence violation: {who} {verb} '{fence['name']}'")
            else:
                logger.info(f"SkiTAK geofence cleared: {who} back to safe for '{fence['name']}'")
            if self._emit is not None:
                try:
                    self._emit(payload)
                except Exception as e:
                    logger.error(f"SkiTAK: geofence emit failed: {e}")
        return transitions


def _valid_coord(lat: Any, lon: Any) -> tuple[float, float]:
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError) as e:
        raise GeofenceError("invalid coordinates") from e
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise GeofenceError("coordinates out of range")
    return lat, lon
