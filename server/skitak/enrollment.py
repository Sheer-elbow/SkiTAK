"""
Client enrollment — zero-friction onboarding for both SkiTAK native app and iTAK/ATAK.

Two flows from the same invite token:

  Native app (SkiTAK iOS):
    GET /api/skitak/enroll/<token>
    → JSON payload with base64 certs — app installs to Keychain automatically

  iTAK / ATAK:
    GET /api/skitak/enroll/<token>/package
    → TAK Data Package (.zip) — import into iTAK/ATAK to configure everything

  Landing page (browser, decides which to use):
    GET /join/<token>  (see join.py)

Token behaviour:
  - A token is single-use: whichever flow redeems it first consumes it.
  - The /package endpoint caches the generated cert for 2h re-download
    (so a failed iTAK import can be retried without a new invite).

Certificates are issued by OpenTAKServer's own CertificateAuthority, so the
client certs land in the same CA store the CoT TLS listener (eud_handler)
validates against.
"""
from __future__ import annotations

import base64
import io
import os
import random
import re
import secrets
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from textwrap import dedent
from typing import Any
from xml.sax.saxutils import escape, quoteattr

from flask import Blueprint, Response, current_app, jsonify, request
from opentakserver.certificate_authority import CertificateAuthority
from opentakserver.extensions import db, logger
from sqlalchemy import text
from sqlalchemy.orm import Session

from .common import safe_filename, valid_token

bp = Blueprint("skitak_enrollment", __name__, url_prefix="/api/skitak/enroll")

TOKEN_TTL_HOURS = 24
PACKAGE_REDOWNLOAD_HOURS = 2   # how long a generated package can be re-downloaded
TOKEN_RETENTION_DAYS = 7       # expired tokens are purged after this

# Callsigns become OTS usernames and CA file paths — letters/digits/._ only
CALLSIGN_RE = re.compile(r"^[A-Za-z0-9._]{2,64}$")


# ── Token management ──────────────────────────────────────────────────────

def create_invite_token(
    db: Session,
    session_id: uuid.UUID | None,
    team_id: uuid.UUID | None,
    team_name: str,
    team_color: str,
    callsign: str | None = None,
) -> str:
    """
    Mint a single-use invite. If `callsign` is set (invites for known roster
    clients), the enrolling device gets that identity — keeping the client's
    history and OTS user account stable across sessions. Otherwise a random
    callsign is generated at redemption.
    """
    _cleanup_stale_tokens(db)
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=TOKEN_TTL_HOURS)
    db.execute(
        text("""
            INSERT INTO skitak_invite_tokens
                (token, session_id, team_id, team_name, team_color, expires_at, callsign)
            VALUES (:token, :session_id, :team_id, :team_name, :team_color, :expires_at, :callsign)
        """),
        {
            "token": token,
            "session_id": session_id,
            "team_id": team_id,
            "team_name": team_name,
            "team_color": team_color,
            "expires_at": expires_at,
            "callsign": callsign,
        },
    )
    db.commit()
    return token


def _cleanup_stale_tokens(db: Session) -> None:
    """Opportunistic hygiene, run on each token mint (guide-frequency, cheap).

    Cached client .p12 blobs are private key material — never keep them past
    the re-download window.
    """
    now = datetime.now(timezone.utc)
    db.execute(
        text("DELETE FROM skitak_invite_tokens WHERE expires_at < :cutoff"),
        {"cutoff": now - timedelta(days=TOKEN_RETENTION_DAYS)},
    )
    db.execute(
        text("""
            UPDATE skitak_invite_tokens
            SET client_p12_data = NULL
            WHERE client_p12_data IS NOT NULL
              AND package_generated_at < :cutoff
        """),
        {"cutoff": now - timedelta(hours=PACKAGE_REDOWNLOAD_HOURS)},
    )
    db.commit()


def _get_token(db: Session, token: str) -> dict[str, Any] | None:
    """Fetch token row without consuming it."""
    row = db.execute(
        text("""
            SELECT token, session_id, team_id, team_name, team_color,
                   expires_at, used_at, callsign,
                   client_p12_data, package_generated_at
            FROM skitak_invite_tokens
            WHERE token = :token
        """),
        {"token": token},
    ).mappings().first()
    if not row:
        return None
    if _aware(row["expires_at"]) < datetime.now(timezone.utc):
        return None
    return dict(row)


def _consume_token(
    db: Session, token: str, callsign: str, p12_data: bytes | None = None
) -> bool:
    """Atomically mark a token as used. Returns False if it was already used."""
    result = db.execute(
        text("""
            UPDATE skitak_invite_tokens
            SET used_at = :now,
                callsign = :callsign,
                client_p12_data = CAST(:p12_data AS bytea),
                package_generated_at = CASE WHEN CAST(:p12_data AS bytea) IS NOT NULL THEN :now END
            WHERE token = :token AND used_at IS NULL
            RETURNING token
        """),
        {
            "now": datetime.now(timezone.utc),
            "callsign": callsign,
            "p12_data": p12_data,
            "token": token,
        },
    )
    db.commit()
    return result.rowcount == 1


# ── Enrollment endpoints ──────────────────────────────────────────────────

@bp.get("/<token>")
def enroll_json(token: str):
    """
    Native SkiTAK app flow.
    Returns JSON with base64 certs — consumes the token.
    """
    if not valid_token(token):
        return jsonify({"error": "Invalid or expired invite link"}), 410

    invite = _get_token(db.session, token)
    if not invite or invite["used_at"] is not None:
        return jsonify({"error": "Invalid or expired invite link"}), 410

    callsign = _enrollment_callsign(invite)
    try:
        client_p12 = _issue_p12(callsign)
        _create_device_identity(callsign, invite)
    except Exception as e:
        logger.error(f"SkiTAK: cert generation failed: {e}")
        return jsonify({"error": "Certificate generation failed"}), 500

    if not _consume_token(db.session, token, callsign):
        return jsonify({"error": "This invite has already been used"}), 410

    return jsonify({
        "callsign": callsign,
        "teamName": invite["team_name"],
        "teamColor": invite["team_color"],
        "sessionId": str(invite["session_id"]) if invite["session_id"] else None,
        "serverAddress": _server_host(),
        "serverPort": current_app.config.get("OTS_SSL_STREAMING_PORT", 8089),
        "caCertBase64": base64.b64encode(_load_ca_cert()).decode(),
        "clientP12Base64": base64.b64encode(client_p12).decode(),
        "p12Passphrase": _cert_password(),
    })


@bp.get("/<token>/package")
def enroll_package(token: str):
    """
    iTAK / ATAK flow.
    Returns a TAK Data Package (.zip) that iTAK imports in one tap.
    Re-downloadable for PACKAGE_REDOWNLOAD_HOURS after first generation.
    """
    if not valid_token(token):
        return jsonify({"error": "Invalid or expired invite link"}), 410

    invite = _get_token(db.session, token)
    if not invite:
        return jsonify({"error": "Invalid or expired invite link"}), 410

    # Already redeemed: allow re-download only within the window, from cache
    if invite["used_at"] is not None:
        cached = invite["client_p12_data"]
        generated_at = invite["package_generated_at"]
        if cached and generated_at is not None:
            age = datetime.now(timezone.utc) - _aware(generated_at)
            if age.total_seconds() < PACKAGE_REDOWNLOAD_HOURS * 3600:
                zip_bytes = _build_data_package(
                    callsign=invite["callsign"],
                    team_name=invite["team_name"],
                    team_color=invite["team_color"],
                    client_p12=cached,
                    server_host=_server_host(),
                )
                return _zip_response(zip_bytes, invite["callsign"])
        return jsonify(
            {"error": "This invite has already been used — ask your guide for a new one"}
        ), 410

    # First download: issue cert and consume the token
    callsign = _enrollment_callsign(invite)
    try:
        client_p12 = _issue_p12(callsign)
        _create_device_identity(callsign, invite)
    except Exception as e:
        logger.error(f"SkiTAK: cert generation failed: {e}")
        return jsonify({"error": "Certificate generation failed"}), 500

    if not _consume_token(db.session, token, callsign, p12_data=client_p12):
        return jsonify({"error": "This invite has already been used"}), 410

    zip_bytes = _build_data_package(
        callsign=callsign,
        team_name=invite["team_name"],
        team_color=invite["team_color"],
        client_p12=client_p12,
        server_host=_server_host(),
    )
    return _zip_response(zip_bytes, callsign)


def _zip_response(zip_bytes: bytes, callsign: str) -> Response:
    filename = f"SkiTAK-{safe_filename(callsign)}.zip"
    return Response(
        zip_bytes,
        mimetype="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(zip_bytes)),
        },
    )


# ── TAK Data Package assembly ─────────────────────────────────────────────

def _build_data_package(
    callsign: str,
    team_name: str,
    team_color: str,
    client_p12: bytes,
    server_host: str,
) -> bytes:
    """
    Assemble a TAK Data Package zip.

    Structure:
      MANIFEST/manifest.xml   — package descriptor (required by all TAK clients)
      certs/truststore.p12    — server CA truststore
      certs/userCert.p12      — signed client cert
      certs/config.pref       — server connection + identity prefs
    """
    truststore_p12 = _load_truststore_p12()
    package_uid = str(uuid.uuid4())

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("MANIFEST/manifest.xml",
                    _manifest_xml(callsign, package_uid))
        zf.writestr("certs/truststore.p12", truststore_p12)
        zf.writestr("certs/userCert.p12",   client_p12)
        zf.writestr("certs/config.pref",
                    _config_pref(callsign, team_name, team_color, server_host))
    return buf.getvalue()


def _manifest_xml(callsign: str, package_uid: str) -> str:
    # quoteattr because these land inside XML attribute values
    return dedent(f"""\
        <MissionPackageManifest version="2">
           <Configuration>
              <Parameter name="uid"   value={quoteattr(package_uid)}/>
              <Parameter name="name"  value={quoteattr(f"SkiTAK - {callsign}")}/>
              <Parameter name="onReceiveDelete" value="false"/>
           </Configuration>
           <Contents>
              <Content ignore="false" zipEntry="certs/truststore.p12">
                 <Parameter name="name" value="truststore.p12"/>
              </Content>
              <Content ignore="false" zipEntry="certs/userCert.p12">
                 <Parameter name="name" value="userCert.p12"/>
              </Content>
              <Content ignore="false" zipEntry="certs/config.pref">
                 <Parameter name="name" value="config.pref"/>
              </Content>
           </Contents>
        </MissionPackageManifest>
    """)


def _config_pref(callsign: str, team_name: str, team_color: str, server_host: str) -> str:
    """
    TAK preference file — sets identity, team colour, and server connection.
    The connectString format is: host:port:protocol
    ssl = TLS with mutual cert auth.
    """
    ssl_port = current_app.config.get("OTS_SSL_STREAMING_PORT", 8089)
    cert_password = _cert_password()
    return dedent(f"""\
        <?xml version='1.0' standalone='yes'?>
        <preferences>
           <preference version="1" name="com.atakmap.app_preferences">
              <entry key="locationCallsign" class="class java.lang.String">{escape(callsign)}</entry>
              <entry key="locationTeam"     class="class java.lang.String">{escape(team_color)}</entry>
              <entry key="atakRoleType"     class="class java.lang.String">Team Member</entry>
              <entry key="locationUnitType" class="class java.lang.String">a-f-G-U-C</entry>
           </preference>
           <preference version="1" name="cot_streams">
              <entry key="count"               class="class java.lang.Integer">1</entry>
              <entry key="description0"        class="class java.lang.String">SkiTAK</entry>
              <entry key="enabled0"            class="class java.lang.Boolean">true</entry>
              <entry key="connectString0"      class="class java.lang.String">{escape(server_host)}:{ssl_port}:ssl</entry>
              <entry key="caLocation0"         class="class java.lang.String">cert/truststore.p12</entry>
              <entry key="caPassword0"         class="class java.lang.String">{escape(cert_password)}</entry>
              <entry key="certificateLocation0" class="class java.lang.String">cert/userCert.p12</entry>
              <entry key="clientPassword0"     class="class java.lang.String">{escape(cert_password)}</entry>
           </preference>
        </preferences>
    """)


def _enrollment_callsign(invite: dict[str, Any]) -> str:
    """Preset callsign from the invite (roster clients) or a fresh random one."""
    preset = invite.get("callsign")
    if preset and CALLSIGN_RE.match(preset):
        return preset
    return _generate_callsign()


def _create_device_identity(callsign: str, invite: dict[str, Any]) -> None:
    """
    The cert alone is not enough: eud_handler authenticates the TLS client by
    matching the cert CN to an OTS username, and team visibility comes from
    OTS group membership. Create both here.
    """
    from .groups import create_device_user

    create_device_user(callsign, team_id=invite.get("team_id"))


# ── Certificate issuance (delegated to the OTS CA) ────────────────────────

def _issue_p12(callsign: str) -> bytes:
    """
    Issue a client certificate through OpenTAKServer's CA so the CoT TLS
    listener trusts it. Returns the PKCS12 bundle (password: OTS_CA_PASSWORD).
    """
    ca = CertificateAuthority(logger, current_app)
    ca.issue_certificate(callsign, False)
    p12_path = _ca_folder() / "certs" / callsign / f"{callsign}.p12"
    return p12_path.read_bytes()


def _load_ca_cert() -> bytes:
    return (_ca_folder() / "ca.pem").read_bytes()


def _load_truststore_p12() -> bytes:
    return (_ca_folder() / "truststore-root.p12").read_bytes()


def _ca_folder() -> Path:
    return Path(current_app.config.get("OTS_CA_FOLDER"))


def _cert_password() -> str:
    return current_app.config.get("OTS_CA_PASSWORD", "atakatak")


def _server_host() -> str:
    configured = os.environ.get("SKITAK_SERVER_ADDRESS") or current_app.config.get(
        "SKITAK_SERVER_ADDRESS"
    )
    return configured or request.host.split(":")[0]


def _generate_callsign() -> str:
    adjectives = ["Swift", "Bold", "Keen", "Bright", "Sharp", "Quick", "Agile"]
    nouns      = ["Fox", "Hawk", "Wolf", "Bear", "Lynx", "Stag", "Hare"]
    certs_dir = _ca_folder() / "certs"
    for _ in range(20):
        callsign = f"{random.choice(adjectives)}{random.choice(nouns)}{random.randint(1, 99)}"
        if not (certs_dir / callsign).exists():
            return callsign
    return f"Guest{secrets.token_hex(4)}"


def _aware(value: Any) -> datetime:
    """Normalise DB timestamps (str or naive datetime) to aware UTC."""
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value
