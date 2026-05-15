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
    GET /join/<token>  (served by Nginx → React SPA)
    → Shows "Open in SkiTAK" deep link + "Download for iTAK" button

Token behaviour:
  - Invite tokens are single-use for the native app JSON endpoint
  - The /package endpoint caches the generated cert for 2h re-download
    (so a failed iTAK import can be retried without a new invite)
"""
from __future__ import annotations

import base64
import io
import random
import secrets
import subprocess
import tempfile
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from textwrap import dedent
from typing import Any

from flask import Blueprint, Response, jsonify, current_app, request
from sqlalchemy import text
from sqlalchemy.orm import Session

bp = Blueprint("enrollment", __name__, url_prefix="/api/skitak/enroll")

TOKEN_TTL_HOURS = 24
PACKAGE_REDOWNLOAD_HOURS = 2   # how long a generated package can be re-downloaded

# Conventional TAK cert passphrase used in data packages —
# TAK clients expect this default; the cert itself provides security, not the p12 password.
TAK_P12_PASSWORD = "atakatak"


# ── Token management ──────────────────────────────────────────────────────

def create_invite_token(
    db: Session,
    session_id: str,
    team_id: str,
    team_name: str,
    team_color: str,
) -> str:
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=TOKEN_TTL_HOURS)
    db.execute(
        text("""
            INSERT INTO skitak_invite_tokens
                (token, session_id, team_id, team_name, team_color, expires_at)
            VALUES (:token, :session_id, :team_id, :team_name, :team_color, :expires_at)
        """),
        {
            "token": token,
            "session_id": session_id,
            "team_id": team_id,
            "team_name": team_name,
            "team_color": team_color,
            "expires_at": expires_at,
        },
    )
    db.commit()
    return token


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
    if row["expires_at"] < datetime.now(timezone.utc):
        return None
    return dict(row)


def _consume_token(db: Session, token: str, callsign: str) -> bool:
    """Mark token as used (native app flow — one-time only)."""
    result = db.execute(
        text("""
            UPDATE skitak_invite_tokens
            SET used_at = :now, callsign = :callsign
            WHERE token = :token AND used_at IS NULL
            RETURNING token
        """),
        {"now": datetime.now(timezone.utc), "callsign": callsign, "token": token},
    )
    db.commit()
    return result.rowcount == 1


def _cache_package(db: Session, token: str, callsign: str, p12_data: bytes) -> None:
    """Cache generated cert for the package re-download window."""
    db.execute(
        text("""
            UPDATE skitak_invite_tokens
            SET callsign = :callsign,
                client_p12_data = :p12_data,
                package_generated_at = :now,
                used_at = COALESCE(used_at, :now)
            WHERE token = :token
        """),
        {
            "callsign": callsign,
            "p12_data": p12_data,
            "now": datetime.now(timezone.utc),
            "token": token,
        },
    )
    db.commit()


# ── Enrollment endpoints ──────────────────────────────────────────────────

@bp.get("/<token>")
def enroll_json(token: str):
    """
    Native SkiTAK app flow.
    Returns JSON with base64 certs — consumed once.
    """
    db = _get_db()
    invite = _get_token(db, token)
    if not invite:
        return jsonify({"error": "Invalid or expired invite link"}), 410
    if invite["used_at"] is not None:
        return jsonify({"error": "This invite has already been used"}), 410

    callsign = _generate_callsign()
    try:
        client_p12, p12_pass = _generate_client_cert(callsign, password=secrets.token_urlsafe(16))
    except Exception as e:
        current_app.logger.error(f"Cert generation failed: {e}")
        return jsonify({"error": "Certificate generation failed"}), 500

    if not _consume_token(db, token, callsign):
        return jsonify({"error": "This invite has already been used"}), 410

    return jsonify({
        "callsign": callsign,
        "teamName": invite["team_name"],
        "teamColor": invite["team_color"],
        "sessionId": invite["session_id"],
        "caCertBase64": base64.b64encode(_load_ca_cert()).decode(),
        "clientP12Base64": base64.b64encode(client_p12).decode(),
        "p12Passphrase": p12_pass,
    })


@bp.get("/<token>/package")
def enroll_package(token: str):
    """
    iTAK / ATAK flow.
    Returns a TAK Data Package (.zip) that iTAK imports in one tap.
    Re-downloadable for PACKAGE_REDOWNLOAD_HOURS after first generation.
    """
    db = _get_db()
    invite = _get_token(db, token)
    if not invite:
        return jsonify({"error": "Invalid or expired invite link"}), 410

    # Re-download window: serve cached cert if generated recently
    if invite["package_generated_at"] is not None:
        generated_at = invite["package_generated_at"]
        if isinstance(generated_at, str):
            generated_at = datetime.fromisoformat(generated_at)
        age = datetime.now(timezone.utc) - generated_at.replace(tzinfo=timezone.utc)
        if age.total_seconds() < PACKAGE_REDOWNLOAD_HOURS * 3600:
            # Serve the cached package
            zip_bytes = _build_data_package(
                callsign=invite["callsign"],
                team_name=invite["team_name"],
                team_color=invite["team_color"],
                client_p12=invite["client_p12_data"],
                server_host=_server_host(),
            )
            return _zip_response(zip_bytes, invite["callsign"])
        else:
            return jsonify({"error": "Download window expired — ask your guide for a new invite"}), 410

    # First download: generate cert with conventional TAK password
    callsign = _generate_callsign()
    try:
        client_p12, _ = _generate_client_cert(callsign, password=TAK_P12_PASSWORD)
    except Exception as e:
        current_app.logger.error(f"Cert generation failed: {e}")
        return jsonify({"error": "Certificate generation failed"}), 500

    _cache_package(db, token, callsign, client_p12)

    zip_bytes = _build_data_package(
        callsign=callsign,
        team_name=invite["team_name"],
        team_color=invite["team_color"],
        client_p12=client_p12,
        server_host=_server_host(),
    )
    return _zip_response(zip_bytes, callsign)


def _zip_response(zip_bytes: bytes, callsign: str) -> Response:
    filename = f"SkiTAK-{callsign}.zip"
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
      certs/truststore.p12    — server CA cert, password: atakatak
      certs/userCert.p12      — signed client cert, password: atakatak
      atak/config.pref        — server connection + identity prefs
    """
    ca_pem = _load_ca_cert()
    truststore_p12 = _build_truststore_p12(ca_pem)
    package_uid = str(uuid.uuid4())

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("MANIFEST/manifest.xml",
                    _manifest_xml(callsign, package_uid))
        zf.writestr("certs/truststore.p12", truststore_p12)
        zf.writestr("certs/userCert.p12",   client_p12)
        zf.writestr("atak/config.pref",
                    _config_pref(callsign, team_name, team_color, server_host))
    return buf.getvalue()


def _manifest_xml(callsign: str, package_uid: str) -> str:
    return dedent(f"""\
        <MissionPackageManifest version="2">
           <Configuration>
              <Parameter name="uid"   value="{package_uid}"/>
              <Parameter name="name"  value="SkiTAK - {callsign}"/>
              <Parameter name="onReceiveDelete" value="false"/>
           </Configuration>
           <Contents>
              <Content ignore="false" zipEntry="certs/truststore.p12">
                 <Parameter name="name" value="truststore.p12"/>
              </Content>
              <Content ignore="false" zipEntry="certs/userCert.p12">
                 <Parameter name="name" value="userCert.p12"/>
              </Content>
              <Content ignore="false" zipEntry="atak/config.pref">
                 <Parameter name="name" value="config.pref"/>
              </Content>
           </Contents>
        </MissionPackageManifest>
    """)


def _config_pref(callsign: str, team_name: str, team_color: str, server_host: str) -> str:
    """
    TAK preference file — sets identity, team colour, and server connection.
    The connectString format is: host:port:protocol
    ssl = TLS with mutual cert auth (port 8089)
    """
    return dedent(f"""\
        <?xml version='1.0' standalone='yes'?>
        <preferences>
           <preference version="1" name="com.atakmap.app_preferences">
              <entry key="locationCallsign" class="class java.lang.String">{callsign}</entry>
              <entry key="locationTeam"     class="class java.lang.String">{team_color}</entry>
              <entry key="atakRoleType"     class="class java.lang.String">Team Member</entry>
              <entry key="locationUnitType" class="class java.lang.String">a-f-G-U-C</entry>
           </preference>
           <preference version="1" name="cot_streams">
              <entry key="count"               class="class java.lang.Integer">1</entry>
              <entry key="description0"        class="class java.lang.String">SkiTAK</entry>
              <entry key="enabled0"            class="class java.lang.Boolean">true</entry>
              <entry key="connectString0"      class="class java.lang.String">{server_host}:8089:ssl</entry>
              <entry key="caLocation0"         class="class java.lang.String">cert/truststore.p12</entry>
              <entry key="caPassword0"         class="class java.lang.String">{TAK_P12_PASSWORD}</entry>
              <entry key="certificateLocation0" class="class java.lang.String">cert/userCert.p12</entry>
              <entry key="clientPassword0"     class="class java.lang.String">{TAK_P12_PASSWORD}</entry>
           </preference>
        </preferences>
    """)


def _build_truststore_p12(ca_pem: bytes) -> bytes:
    """Wrap the CA PEM cert as a PKCS12 truststore with the standard TAK password."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        ca_file = tmp / "ca.pem"
        ts_file = tmp / "truststore.p12"
        ca_file.write_bytes(ca_pem)
        subprocess.run(
            ["openssl", "pkcs12", "-export",
             "-nokeys",
             "-in", str(ca_file),
             "-out", str(ts_file),
             "-passout", f"pass:{TAK_P12_PASSWORD}",
             "-legacy"],     # -legacy flag needed for TAK client compatibility
            check=True, capture_output=True,
        )
        return ts_file.read_bytes()


# ── Certificate generation ────────────────────────────────────────────────

def _generate_client_cert(callsign: str, password: str) -> tuple[bytes, str]:
    data_dir = Path(current_app.config.get("OTS_DATA_DIR", "/data/opentakserver"))
    ca_cert = data_dir / "certs" / "ca.pem"
    ca_key  = data_dir / "certs" / "ca.key"
    uid = str(uuid.uuid4())

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        key_file  = tmp / "client.key"
        csr_file  = tmp / "client.csr"
        cert_file = tmp / "client.crt"
        p12_file  = tmp / "client.p12"

        subprocess.run(
            ["openssl", "genrsa", "-out", str(key_file), "2048"],
            check=True, capture_output=True,
        )
        subprocess.run(
            ["openssl", "req", "-new",
             "-key", str(key_file),
             "-out", str(csr_file),
             "-subj", f"/CN={callsign}/UID={uid}"],
            check=True, capture_output=True,
        )
        subprocess.run(
            ["openssl", "x509", "-req",
             "-in", str(csr_file),
             "-CA", str(ca_cert), "-CAkey", str(ca_key), "-CAcreateserial",
             "-out", str(cert_file),
             "-days", "90", "-sha256"],
            check=True, capture_output=True,
        )
        subprocess.run(
            ["openssl", "pkcs12", "-export",
             "-out", str(p12_file),
             "-inkey", str(key_file),
             "-in", str(cert_file),
             "-certfile", str(ca_cert),
             "-passout", f"pass:{password}",
             "-legacy"],
            check=True, capture_output=True,
        )
        return p12_file.read_bytes(), password


def _load_ca_cert() -> bytes:
    data_dir = Path(current_app.config.get("OTS_DATA_DIR", "/data/opentakserver"))
    return (data_dir / "certs" / "ca.pem").read_bytes()


def _server_host() -> str:
    return current_app.config.get("OTS_SERVER_ADDRESS", request.host.split(":")[0])


def _generate_callsign() -> str:
    adjectives = ["Swift", "Bold", "Keen", "Bright", "Sharp", "Quick", "Agile"]
    nouns      = ["Fox", "Hawk", "Wolf", "Bear", "Lynx", "Stag", "Hare"]
    return f"{random.choice(adjectives)}{random.choice(nouns)}{random.randint(1, 99)}"


def _get_db():
    from flask import g
    if "db" not in g:
        from sqlalchemy.orm import Session as SASession
        g.db = SASession(current_app.extensions["sqlalchemy"].engine)
    return g.db
