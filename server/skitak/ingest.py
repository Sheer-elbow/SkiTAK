"""
Track ingestion — consumes OpenTAKServer's `firehose` RabbitMQ exchange
(every CoT event, published as JSON {"uid": ..., "cot": "<event .../>"}) and
stores position updates as PostGIS track points.

A device is attributed to a session/team by its callsign: enrollment records
the callsign on the invite token, so any position sent while the token's
session is running (started_at set, ended_at null) is stored against it.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

from opentakserver.extensions import logger
from sqlalchemy import text
from sqlalchemy.orm import Session

from .tracks import store_track_point

MAPPING_CACHE_TTL_S = 30
RETRY_DELAY_S = 5


def parse_cot_position(cot_xml: str) -> dict[str, Any] | None:
    """
    Parse a CoT event into the dict shape store_track_point expects.
    Returns None for anything that isn't a usable position update.
    """
    try:
        event = ET.fromstring(cot_xml)
    except ET.ParseError:
        return None
    if event.tag != "event" or not event.get("type", "").startswith("a-"):
        return None

    point = event.find("point")
    if point is None:
        return None
    try:
        lat = float(point.get("lat", ""))
        lon = float(point.get("lon", ""))
    except ValueError:
        return None
    if lat == 0.0 and lon == 0.0:
        return None  # placeholder points (pings, disconnects)

    detail = event.find("detail")
    if detail is None:
        detail = ET.Element("detail")
    contact = detail.find("contact")
    track = detail.find("track")
    status = detail.find("status")

    recorded_at: Any = datetime.now(timezone.utc)
    if event.get("time"):
        try:
            recorded_at = datetime.fromisoformat(event.get("time").replace("Z", "+00:00"))
        except ValueError:
            pass

    return {
        "uid": event.get("uid"),
        "callsign": contact.get("callsign") if contact is not None else None,
        "time": recorded_at,
        "point": {
            "lat": lat,
            "lon": lon,
            "hae": _float(point.get("hae")),
            "ce": _float(point.get("ce")),
        },
        "detail": {
            "track": {
                "speed": _float(track.get("speed")) if track is not None else None,
                "course": _float(track.get("course")) if track is not None else None,
            },
            "status": {
                "battery": _int(status.get("battery")) if status is not None else None,
            },
        },
    }


def resolve_active_membership(
    db_session: Session, callsign: str
) -> tuple[uuid.UUID, uuid.UUID] | None:
    """(session_id, team_id) for a callsign enrolled into a running session."""
    row = db_session.execute(
        text("""
            SELECT it.session_id, it.team_id
            FROM skitak_invite_tokens it
            JOIN skitak_sessions s ON s.id = it.session_id
            WHERE it.callsign = :callsign
              AND it.used_at IS NOT NULL
              AND s.started_at IS NOT NULL
              AND s.ended_at IS NULL
            ORDER BY it.used_at DESC
            LIMIT 1
        """),
        {"callsign": callsign},
    ).first()
    return (row[0], row[1]) if row else None


def ingest_position(db_session: Session, position: dict[str, Any]) -> bool:
    """Store one parsed position against its session. Returns True if stored."""
    callsign = position.get("callsign")
    if not callsign:
        return False

    membership = resolve_active_membership(db_session, callsign)
    if membership is None:
        return False
    session_id, team_id = membership

    if team_id is not None:
        db_session.execute(
            text("""
                INSERT INTO skitak_team_members (team_id, tak_uid, callsign)
                VALUES (:team_id, :tak_uid, :callsign)
                ON CONFLICT (team_id, tak_uid) DO NOTHING
            """),
            {"team_id": team_id, "tak_uid": position["uid"], "callsign": callsign},
        )

    store_track_point(db_session, {**position, "session_id": session_id})
    return True


class TrackIngestWorker:
    """Background consumer thread. Started by the plugin inside the main
    opentakserver process; reconnects with backoff if RabbitMQ drops."""

    def __init__(self, app):
        self._app = app
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._cache: dict[str, tuple[Any, float]] = {}
        with app.app_context():
            from opentakserver.extensions import db

            self._engine = db.engine
        self._rabbit_host = app.config.get("OTS_RABBITMQ_SERVER_ADDRESS", "127.0.0.1")
        self._rabbit_user = app.config.get("OTS_RABBITMQ_USERNAME", "guest")
        self._rabbit_password = app.config.get("OTS_RABBITMQ_PASSWORD", "guest")

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run, name="skitak-track-ingest", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ── Consumer loop ─────────────────────────────────────────────────────

    def _run(self) -> None:
        import pika

        while not self._stop.is_set():
            try:
                credentials = pika.PlainCredentials(self._rabbit_user, self._rabbit_password)
                connection = pika.BlockingConnection(
                    pika.ConnectionParameters(host=self._rabbit_host, credentials=credentials)
                )
                channel = connection.channel()
                channel.exchange_declare("firehose", durable=True, exchange_type="fanout")
                queue = channel.queue_declare("", exclusive=True, auto_delete=True)
                channel.queue_bind(queue.method.queue, exchange="firehose")
                channel.basic_consume(
                    queue.method.queue, self._on_message, auto_ack=True
                )
                logger.info("SkiTAK: track ingest worker consuming the firehose exchange")
                while not self._stop.is_set():
                    connection.process_data_events(time_limit=1)
                connection.close()
            except Exception as e:
                if self._stop.is_set():
                    break
                logger.warning(
                    f"SkiTAK: track ingest connection failed ({e}); retrying in {RETRY_DELAY_S}s"
                )
                self._stop.wait(RETRY_DELAY_S)

    def _on_message(self, channel, method, properties, body) -> None:
        try:
            payload = json.loads(body)
            position = parse_cot_position(payload.get("cot", ""))
            if position is None:
                return
            if not self._cached_is_active(position.get("callsign")):
                return
            with Session(self._engine) as db_session:
                ingest_position(db_session, position)
        except Exception as e:
            logger.error(f"SkiTAK: failed to ingest track point: {e}")

    def _cached_is_active(self, callsign: str | None) -> bool:
        """Cheap pre-filter so non-session traffic doesn't hit the DB per event."""
        if not callsign:
            return False
        now = time.monotonic()
        cached = self._cache.get(callsign)
        if cached is not None and cached[1] > now:
            return cached[0]
        with Session(self._engine) as db_session:
            active = resolve_active_membership(db_session, callsign) is not None
        self._cache[callsign] = (active, now + MAPPING_CACHE_TTL_S)
        if len(self._cache) > 4096:
            self._cache = {k: v for k, v in self._cache.items() if v[1] > now}
        return active


def _float(value: str | None) -> float | None:
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


def _int(value: str | None) -> int | None:
    try:
        return int(float(value)) if value is not None else None
    except ValueError:
        return None
