"""
Client enrollment — handles the zero-friction iOS onboarding flow.

Flow:
  1. Guide calls POST /api/skitak/sessions/<id>/teams/<id>/invite
     → server creates a one-time token (stored in DB with TTL)
  2. Guide shares the resulting link with clients
  3. Client taps link → iOS app calls GET /api/skitak/enroll/<token>
  4. Server generates a signed client cert, returns JSON payload
  5. iOS app installs cert into Keychain, connects to CoT stream
"""
from __future__ import annotations

import base64
import os
import secrets
import subprocess
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from flask import Blueprint, jsonify, current_app, request
from sqlalchemy import text
from sqlalchemy.orm import Session

bp = Blueprint("enrollment", __name__, url_prefix="/api/skitak/enroll")

TOKEN_TTL_HOURS = 24


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


def consume_token(db: Session, token: str) -> dict[str, Any] | None:
    row = db.execute(
        text("""
            SELECT session_id, team_id, team_name, team_color, expires_at, used_at
            FROM skitak_invite_tokens
            WHERE token = :token
        """),
        {"token": token},
    ).mappings().first()

    if not row:
        return None
    if row["used_at"] is not None:
        return None  # already used
    if row["expires_at"] < datetime.now(timezone.utc):
        return None  # expired

    # Mark as used
    db.execute(
        text("UPDATE skitak_invite_tokens SET used_at = :now WHERE token = :token"),
        {"now": datetime.now(timezone.utc), "token": token},
    )
    db.commit()
    return dict(row)


# ── Enrollment endpoint ───────────────────────────────────────────────────

@bp.get("/<token>")
def enroll(token: str):
    """
    Called by the iOS app when a client taps an invite link.
    Returns a JSON payload containing signed client cert + CA cert + config.
    """
    from flask import g
    db: Session = _get_db()

    invite = consume_token(db, token)
    if not invite:
        return jsonify({"error": "Invalid or expired invite link"}), 410

    # Generate a callsign from the device user-agent or a random one
    callsign = _generate_callsign()

    # Generate client certificate signed by the OTS CA
    try:
        client_p12, p12_passphrase = _generate_client_cert(callsign)
    except Exception as e:
        current_app.logger.error(f"Cert generation failed: {e}")
        return jsonify({"error": "Certificate generation failed"}), 500

    # Load the CA cert to send to the client
    ca_cert_pem = _load_ca_cert()

    return jsonify({
        "callsign": callsign,
        "teamName": invite["team_name"],
        "teamColor": invite["team_color"],
        "sessionId": invite["session_id"],
        "caCertBase64": base64.b64encode(ca_cert_pem).decode(),
        "clientP12Base64": base64.b64encode(client_p12).decode(),
        "p12Passphrase": p12_passphrase,
    })


# ── Certificate generation ────────────────────────────────────────────────

def _generate_client_cert(callsign: str) -> tuple[bytes, str]:
    """
    Generate a client certificate signed by the OTS CA.
    Uses OpenSSL via subprocess — OTS exposes its CA in the data directory.
    In production, OTS's cert API should be used directly.
    """
    data_dir = Path(current_app.config.get("OTS_DATA_DIR", "/data/opentakserver"))
    ca_cert = data_dir / "certs" / "ca.pem"
    ca_key = data_dir / "certs" / "ca.key"
    passphrase = secrets.token_urlsafe(16)
    uid = str(uuid.uuid4())

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        key_file = tmp / "client.key"
        csr_file = tmp / "client.csr"
        cert_file = tmp / "client.crt"
        p12_file = tmp / "client.p12"

        # Generate key
        subprocess.run(
            ["openssl", "genrsa", "-out", str(key_file), "2048"],
            check=True, capture_output=True,
        )

        # Generate CSR
        subprocess.run(
            ["openssl", "req", "-new",
             "-key", str(key_file),
             "-out", str(csr_file),
             "-subj", f"/CN={callsign}/UID={uid}"],
            check=True, capture_output=True,
        )

        # Sign with CA (90-day validity)
        subprocess.run(
            ["openssl", "x509", "-req",
             "-in", str(csr_file),
             "-CA", str(ca_cert),
             "-CAkey", str(ca_key),
             "-CAcreateserial",
             "-out", str(cert_file),
             "-days", "90",
             "-sha256"],
            check=True, capture_output=True,
        )

        # Pack as PKCS12
        subprocess.run(
            ["openssl", "pkcs12", "-export",
             "-out", str(p12_file),
             "-inkey", str(key_file),
             "-in", str(cert_file),
             "-certfile", str(ca_cert),
             "-passout", f"pass:{passphrase}"],
            check=True, capture_output=True,
        )

        return p12_file.read_bytes(), passphrase


def _load_ca_cert() -> bytes:
    data_dir = Path(current_app.config.get("OTS_DATA_DIR", "/data/opentakserver"))
    ca_cert = data_dir / "certs" / "ca.pem"
    return ca_cert.read_bytes()


def _generate_callsign() -> str:
    adjectives = ["Swift", "Bold", "Keen", "Bright", "Sharp", "Quick", "Agile"]
    nouns = ["Fox", "Hawk", "Wolf", "Bear", "Lynx", "Stag", "Hare"]
    import random
    return f"{random.choice(adjectives)}{random.choice(nouns)}{random.randint(1, 99)}"


def _get_db():
    from flask import g, current_app
    if "db" not in g:
        from sqlalchemy.orm import Session as SASession
        g.db = SASession(current_app.extensions["sqlalchemy"].engine)
    return g.db
