"""
Planned routes — a guide uploads a GPX file for a session; it is stored in
PostGIS (for the dashboard) and broadcast to the session's devices as a TAK
route CoT so it appears on iTAK/ATAK maps.
"""
from __future__ import annotations

import json
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Any
from xml.sax.saxutils import escape, quoteattr

from opentakserver.extensions import logger
from sqlalchemy import text
from sqlalchemy.orm import Session

MAX_GPX_BYTES = 5 * 1024 * 1024
# ATAK gets sluggish with huge routes; the dashboard keeps full resolution
MAX_COT_ROUTE_POINTS = 200

GPX_NS = "{http://www.topografix.com/GPX/1/1}"
GPX10_NS = "{http://www.topografix.com/GPX/1/0}"


class GpxError(ValueError):
    pass


# ── GPX parsing ───────────────────────────────────────────────────────────

def parse_gpx(data: bytes) -> tuple[str, list[tuple[float, float, float | None]]]:
    """
    Extract (name, [(lat, lon, ele), ...]) from a GPX 1.0/1.1 file.
    Accepts track points, route points, or bare waypoints — in that order of
    preference.
    """
    if len(data) > MAX_GPX_BYTES:
        raise GpxError("GPX file too large (max 5 MB)")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        raise GpxError(f"Not a valid GPX file: {e}") from e
    if not root.tag.endswith("gpx"):
        raise GpxError("Not a GPX file")

    ns = GPX_NS if root.tag.startswith(GPX_NS) else GPX10_NS if root.tag.startswith(GPX10_NS) else ""

    def collect(path: str) -> list[tuple[float, float, float | None]]:
        points = []
        for pt in root.iter(f"{ns}{path}"):
            try:
                lat = float(pt.get("lat", ""))
                lon = float(pt.get("lon", ""))
            except ValueError:
                continue
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                continue
            ele_el = pt.find(f"{ns}ele")
            ele = None
            if ele_el is not None and ele_el.text:
                try:
                    ele = float(ele_el.text)
                except ValueError:
                    pass
            points.append((lat, lon, ele))
        return points

    points = collect("trkpt") or collect("rtept") or collect("wpt")
    if len(points) < 2:
        raise GpxError("GPX contains fewer than 2 usable points")

    # Explicit None checks: ElementTree elements are falsy when childless,
    # so an `or` chain would skip a perfectly good <name> element.
    name = ""
    for path in (f"{ns}trk/{ns}name", f"{ns}rte/{ns}name", f"{ns}metadata/{ns}name", f"{ns}name"):
        name_el = root.find(path)
        if name_el is not None and name_el.text:
            name = name_el.text.strip()
            break
    return name or "Planned route", points


def decimate(points: list, limit: int = MAX_COT_ROUTE_POINTS) -> list:
    """Every-Nth downsample keeping first and last points."""
    if len(points) <= limit:
        return points
    step = (len(points) - 1) / (limit - 1)
    return [points[round(i * step)] for i in range(limit)]


# ── Storage ───────────────────────────────────────────────────────────────

def store_route(
    db: Session,
    session_id: uuid.UUID,
    name: str,
    points: list[tuple[float, float, float | None]],
    uploaded_by: str | None = None,
) -> str:
    """Replace the session's planned route (one route per session for now)."""
    route_id = uuid.uuid4()
    linestring = ", ".join(f"{lon} {lat}" for lat, lon, _ in points)
    db.execute(
        text("DELETE FROM skitak_routes WHERE session_id = :session_id"),
        {"session_id": session_id},
    )
    db.execute(
        text("""
            INSERT INTO skitak_routes (id, session_id, name, geometry, point_count, uploaded_by)
            VALUES (:id, :session_id, :name,
                    ST_GeogFromText(:wkt),
                    :point_count, :uploaded_by)
        """),
        {
            "id": route_id,
            "session_id": session_id,
            "name": name,
            "wkt": f"LINESTRING({linestring})",
            "point_count": len(points),
            "uploaded_by": uploaded_by,
        },
    )
    db.commit()
    return str(route_id)


def get_route(db: Session, session_id: uuid.UUID) -> dict[str, Any] | None:
    row = db.execute(
        text("""
            SELECT id, name, point_count, uploaded_by, uploaded_at,
                   ST_AsGeoJSON(geometry::geometry) AS geojson
            FROM skitak_routes
            WHERE session_id = :session_id
            ORDER BY uploaded_at DESC
            LIMIT 1
        """),
        {"session_id": session_id},
    ).mappings().first()
    if not row:
        return None
    route = dict(row)
    geometry = json.loads(route.pop("geojson"))
    # GeoJSON is [lon, lat]; hand the dashboard {lat, lon} pairs
    route["points"] = [{"lat": c[1], "lon": c[0]} for c in geometry["coordinates"]]
    return route


def delete_route(db: Session, session_id: uuid.UUID) -> bool:
    result = db.execute(
        text("DELETE FROM skitak_routes WHERE session_id = :session_id"),
        {"session_id": session_id},
    )
    db.commit()
    return result.rowcount > 0


# ── TAK route CoT ─────────────────────────────────────────────────────────

def route_cot_xml(
    name: str,
    points: list[tuple[float, float, float | None]],
    route_uid: str,
    stale_hours: int = 24,
) -> str:
    """
    Build an ATAK route CoT (type b-m-r): one <link> checkpoint per point.
    Point list is decimated to keep the event a sane size on devices.
    """
    pts = decimate(points)
    now = datetime.now(timezone.utc)
    stale = now + timedelta(hours=stale_hours)
    iso = "%Y-%m-%dT%H:%M:%S.%fZ"

    links = "\n    ".join(
        f'<link uid={quoteattr(f"{route_uid}.{i}")} '
        f'callsign={quoteattr(f"CP{i + 1}")} '
        f'type="b-m-p-c" point={quoteattr(f"{lat},{lon},{ele if ele is not None else 0}")}/>'
        for i, (lat, lon, ele) in enumerate(pts)
    )
    first_lat, first_lon, first_ele = pts[0]

    return f"""<event version="2.0" uid={quoteattr(route_uid)} type="b-m-r" how="h-e" \
time="{now.strftime(iso)}" start="{now.strftime(iso)}" stale="{stale.strftime(iso)}">
  <point lat="{first_lat}" lon="{first_lon}" hae="{first_ele if first_ele is not None else 0}" ce="9999999.0" le="9999999.0"/>
  <detail>
    <contact callsign={quoteattr(name)}/>
    <link_attr planningmethod="Infil" color="-16776961" method="Walking" prefix="CP" \
type="On Foot" stroke="-16776961" direction="Infil" routetype="Primary" order="Ascending Check Points"/>
    {links}
    <__routeinfo>
      <__navcues/>
    </__routeinfo>
    <remarks>{escape(f"SkiTAK planned route: {name}")}</remarks>
  </detail>
</event>"""


def broadcast_route_to_teams(
    rabbit_host: str,
    rabbit_user: str,
    rabbit_password: str,
    group_names: list[str],
    cot_xml: str,
    sender_uid: str = "skitak-server",
) -> int:
    """
    Publish the route CoT to each team group's OUT routing key on OTS's
    `groups` exchange — the same path cot_parser uses to reach connected
    devices. Returns the number of groups published to.
    """
    import pika

    if not group_names:
        return 0
    credentials = pika.PlainCredentials(rabbit_user, rabbit_password)
    connection = pika.BlockingConnection(
        pika.ConnectionParameters(host=rabbit_host, credentials=credentials)
    )
    try:
        channel = connection.channel()
        body = json.dumps({"uid": sender_uid, "cot": cot_xml})
        for group_name in group_names:
            channel.basic_publish(
                exchange="groups",
                routing_key=f"{group_name}.OUT",
                body=body,
            )
        logger.info(f"SkiTAK: broadcast planned route to {len(group_names)} team group(s)")
        return len(group_names)
    finally:
        connection.close()
