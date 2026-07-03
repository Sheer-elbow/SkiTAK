"""Invite token lifecycle — the security perimeter of the enrollment flow."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from skitak.enrollment import (
    PACKAGE_REDOWNLOAD_HOURS,
    TOKEN_RETENTION_DAYS,
    _cleanup_stale_tokens,
    _consume_token,
    _get_token,
    create_invite_token,
)
from skitak.sessions import create_session, create_team


def _mint(session):
    sid = uuid.UUID(create_session(session, "S", "skiing", "GUIDE-1"))
    tid = uuid.UUID(create_team(session, sid, "Team", "Cyan"))
    return create_invite_token(session, sid, tid, "Team", "Cyan")


def test_token_roundtrip(session):
    token = _mint(session)
    invite = _get_token(session, token)
    assert invite is not None
    assert invite["team_name"] == "Team"
    assert invite["used_at"] is None


def test_unknown_token(session):
    assert _get_token(session, "does-not-exist") is None


def test_token_single_use(session):
    token = _mint(session)
    assert _consume_token(session, token, "SwiftFox1") is True
    # Second redemption must fail — this is what stops invite replay
    assert _consume_token(session, token, "BoldHawk2") is False

    invite = _get_token(session, token)
    assert invite["used_at"] is not None
    assert invite["callsign"] == "SwiftFox1"


def test_consume_with_package_caches_p12(session):
    token = _mint(session)
    assert _consume_token(session, token, "KeenLynx3", p12_data=b"fake-p12") is True
    invite = _get_token(session, token)
    assert invite["client_p12_data"] == b"fake-p12"
    assert invite["package_generated_at"] is not None


def test_expired_token_rejected(session):
    token = _mint(session)
    session.execute(
        text("UPDATE skitak_invite_tokens SET expires_at = :past WHERE token = :token"),
        {"past": datetime.now(timezone.utc) - timedelta(hours=1), "token": token},
    )
    session.commit()
    assert _get_token(session, token) is None


def test_cleanup_purges_old_tokens_and_p12(session):
    keep = _mint(session)
    purge = _mint(session)
    stale_p12 = _mint(session)

    now = datetime.now(timezone.utc)
    session.execute(
        text("UPDATE skitak_invite_tokens SET expires_at = :old WHERE token = :token"),
        {"old": now - timedelta(days=TOKEN_RETENTION_DAYS + 1), "token": purge},
    )
    _consume_token(session, stale_p12, "AgileBear4", p12_data=b"private-key-material")
    session.execute(
        text("""
            UPDATE skitak_invite_tokens
            SET package_generated_at = :old WHERE token = :token
        """),
        {"old": now - timedelta(hours=PACKAGE_REDOWNLOAD_HOURS + 1), "token": stale_p12},
    )
    session.commit()

    _cleanup_stale_tokens(session)

    assert _get_token(session, keep) is not None
    row = session.execute(
        text("SELECT 1 FROM skitak_invite_tokens WHERE token = :t"), {"t": purge}
    ).first()
    assert row is None
    # p12 blob (private key material) must be wiped after the window
    stale_row = _get_token(session, stale_p12)
    assert stale_row["client_p12_data"] is None
