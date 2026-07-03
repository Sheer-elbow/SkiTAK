"""
OTS user + group management for SkiTAK teams.

Why this exists:
  - eud_handler authenticates a TLS client by looking up an OTS user whose
    username matches the certificate CN, and drops the connection if none
    exists. So every enrolled device needs an OTS user account.
  - CoT routing between devices is driven by Group/GroupUser rows. One OTS
    group per SkiTAK team gives PLAN.md's visibility model: team members see
    their team; the guide (the user who creates the team) is added to every
    team group in their session.
  - Deactivating a device's user account (`user.active = False`) makes
    eud_handler refuse the cert on the next connection — that is our
    certificate revocation.
"""
from __future__ import annotations

import secrets
import uuid

from flask import current_app
from flask_security.utils import hash_password
from opentakserver.extensions import db, logger
from opentakserver.models.Group import Group, GroupTypeEnum
from opentakserver.models.GroupUser import GroupUser

GROUP_PREFIX = "skitak-"


def group_name_for_team(team_id: uuid.UUID | str) -> str:
    """Stable, unique OTS group name for a SkiTAK team."""
    return f"{GROUP_PREFIX}{str(team_id)[:8]}"


def ensure_team_group(team_id: uuid.UUID, guide_user=None) -> Group:
    """
    Create the OTS group backing a SkiTAK team (idempotent). If a guide user
    is given (the authenticated user creating the team), add them to the
    group in both directions so they see and reach the whole team.
    """
    name = group_name_for_team(team_id)
    group = db.session.execute(
        db.session.query(Group).filter_by(name=name)
    ).scalar_one_or_none()
    if group is None:
        group = Group()  # __init__ assigns the next free bitpos
        group.name = name
        group.type = GroupTypeEnum.SYSTEM
        group.description = f"SkiTAK team {team_id}"
        db.session.add(group)
        db.session.commit()
        logger.info(f"SkiTAK: created OTS group {name} (bitpos {group.bitpos})")

    if guide_user is not None and getattr(guide_user, "id", None) is not None:
        add_user_to_group(guide_user, group)
    return group


def add_user_to_group(user, group: Group) -> None:
    """Give a user read+write membership of a group (idempotent)."""
    for direction in (Group.IN, Group.OUT):
        existing = db.session.execute(
            db.session.query(GroupUser).filter_by(
                user_id=user.id, group_id=group.id, direction=direction
            )
        ).scalar_one_or_none()
        if existing is None:
            membership = GroupUser()
            membership.user_id = user.id
            membership.group_id = group.id
            membership.direction = direction
            membership.enabled = True
            db.session.add(membership)
        elif not existing.enabled:
            existing.enabled = True
    db.session.commit()


def create_device_user(callsign: str, team_id: uuid.UUID | None = None):
    """
    Create (or reactivate) the OTS user account a device authenticates as —
    eud_handler matches the cert CN against usernames. The password is random
    and never shared: these accounts exist only for cert authentication.
    """
    datastore = current_app.security.datastore
    user = datastore.find_user(username=callsign)
    if user is None:
        role = datastore.find_or_create_role(
            name="user", permissions={"user-read", "user-write"}
        )
        user = datastore.create_user(
            username=callsign,
            password=hash_password(secrets.token_urlsafe(32)),
            roles=[role],
        )
        db.session.commit()
        logger.info(f"SkiTAK: created device user {callsign}")
    elif not user.active:
        user.active = True
        db.session.commit()
        logger.info(f"SkiTAK: reactivated device user {callsign}")

    if team_id is not None:
        add_user_to_group(user, ensure_team_group(team_id))
    return user


def deactivate_device_user(callsign: str) -> bool:
    """
    Revoke a device's access: eud_handler rejects certs whose user is
    inactive. Returns True if a user was deactivated.
    """
    if not callsign:
        return False
    datastore = current_app.security.datastore
    user = datastore.find_user(username=callsign)
    if user is None or not user.active:
        return False
    user.active = False
    db.session.commit()
    logger.info(f"SkiTAK: deactivated device user {callsign}")
    return True


def revoke_session_devices(session_id: uuid.UUID) -> list[str]:
    """
    Deactivate every device user enrolled through this session's invites.
    Called on session end so ex-clients don't retain live tracking access.
    """
    from sqlalchemy import text

    rows = db.session.execute(
        text("""
            SELECT callsign FROM skitak_invite_tokens
            WHERE session_id = :session_id
              AND used_at IS NOT NULL
              AND callsign IS NOT NULL
        """),
        {"session_id": session_id},
    ).scalars().all()

    revoked = [cs for cs in rows if deactivate_device_user(cs)]
    if revoked:
        logger.info(f"SkiTAK: revoked {len(revoked)} device user(s) for session {session_id}")
    return revoked
