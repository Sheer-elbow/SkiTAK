"""Shared helpers for the SkiTAK blueprints."""
from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any

TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
CALLSIGN_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]")


def parse_uuid(value: str) -> uuid.UUID | None:
    """Parse a path/body parameter into a UUID, or None if invalid."""
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        return None


def valid_token(token: str) -> bool:
    """Invite tokens are URL-safe base64 — reject anything else before it reaches SQL or HTML."""
    return bool(TOKEN_RE.match(token or ""))


def safe_filename(name: str, fallback: str = "track") -> str:
    """Strip anything that could break a Content-Disposition header or filesystem path."""
    cleaned = CALLSIGN_SAFE_RE.sub("", name or "")
    return cleaned or fallback


def serialise(row: Any) -> dict[str, Any]:
    d = dict(row)
    for k, v in d.items():
        if isinstance(v, datetime):
            d[k] = v.isoformat()
        elif isinstance(v, uuid.UUID):
            d[k] = str(v)
    return d
