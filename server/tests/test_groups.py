"""OTS user/group wiring — the mechanics behind CoT auth and team visibility."""
from __future__ import annotations

import uuid

from opentakserver.models.Group import Group
from opentakserver.models.GroupUser import GroupUser

from skitak.enrollment import _consume_token, create_invite_token
from skitak.groups import (
    create_device_user,
    deactivate_device_user,
    ensure_team_group,
    group_name_for_team,
    revoke_session_devices,
)
from skitak.sessions import create_session, create_team


def _memberships(session, user_id, group_id):
    return session.query(GroupUser).filter_by(user_id=user_id, group_id=group_id).all()


def test_ensure_team_group_idempotent(app, session):
    team_id = uuid.uuid4()
    with app.test_request_context():
        group = ensure_team_group(team_id)
        again = ensure_team_group(team_id)
    assert group.id == again.id
    assert group.name == group_name_for_team(team_id)
    assert group.name.startswith("skitak-")
    assert group.bitpos >= 2


def test_ensure_team_group_adds_guide(app, session):
    team_id = uuid.uuid4()
    with app.test_request_context():
        guide = create_device_user("GuideSarah")
        group = ensure_team_group(team_id, guide_user=guide)
    directions = {m.direction for m in _memberships(session, guide.id, group.id)}
    assert directions == {"IN", "OUT"}


def test_create_device_user_joins_team_group(app, session):
    team_id = uuid.uuid4()
    with app.test_request_context():
        user = create_device_user("SwiftFox7", team_id=team_id)
    assert user.active
    assert any(r.name == "user" for r in user.roles)

    group = session.query(Group).filter_by(name=group_name_for_team(team_id)).one()
    directions = {m.direction for m in _memberships(session, user.id, group.id)}
    assert directions == {"IN", "OUT"}


def test_deactivate_and_reenroll(app, session):
    """Deactivation is our revocation: eud_handler rejects inactive users.
    Re-enrolling the same callsign must reactivate the account."""
    with app.test_request_context():
        user = create_device_user("BoldHawk9")
        assert deactivate_device_user("BoldHawk9") is True
        assert not user.active
        # Second revoke is a no-op
        assert deactivate_device_user("BoldHawk9") is False
        # Unknown callsign is a no-op
        assert deactivate_device_user("NoSuchUser") is False

        user = create_device_user("BoldHawk9")
        assert user.active


def test_revoke_session_devices(app, session):
    sid = uuid.UUID(create_session(session, "S", "skiing", "GUIDE-1"))
    tid = uuid.UUID(create_team(session, sid, "Team", "Cyan"))

    with app.test_request_context():
        token = create_invite_token(session, sid, tid, "Team", "Cyan")
        create_device_user("KeenLynx3", team_id=tid)
        _consume_token(session, token, "KeenLynx3")

        # A different session's device must be untouched
        other = create_device_user("OtherGuy1")

        revoked = revoke_session_devices(sid)

    assert revoked == ["KeenLynx3"]
    datastore = app.security.datastore
    assert not datastore.find_user(username="KeenLynx3").active
    assert other.active
