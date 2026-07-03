"""
Test fixtures — run against a real PostgreSQL + PostGIS database.

Locally:
    docker run -d -p 5433:5432 -e POSTGRES_PASSWORD=skitak \
        -e POSTGRES_USER=skitak -e POSTGRES_DB=skitak_test postgis/postgis:16-3.4
    SKITAK_TEST_DATABASE_URI=postgresql+psycopg://skitak:skitak@localhost:5433/skitak_test pytest

CI provides the database as a service container (.github/workflows/ci.yml).
"""
from __future__ import annotations

import os

import pytest
from flask import Flask
from opentakserver.extensions import db
from sqlalchemy import text

DATABASE_URI = os.environ.get(
    "SKITAK_TEST_DATABASE_URI",
    "postgresql+psycopg://skitak:skitak@localhost:5433/skitak_test",
)

TABLES = [
    "skitak_pois",
    "skitak_session_clients",
    "skitak_clients",
    "skitak_invite_tokens",
    "skitak_track_points",
    "skitak_team_members",
    "skitak_teams",
    "skitak_sessions",
]


@pytest.fixture(scope="session")
def app():
    app = Flask(__name__)
    app.config.update(
        SQLALCHEMY_DATABASE_URI=DATABASE_URI,
        TESTING=True,
        SECRET_KEY="test-secret-key",
        SECURITY_PASSWORD_SALT="test-password-salt",
    )
    db.init_app(app)

    # Real OTS models + Flask-Security so @auth_required and the group/user
    # wiring behave exactly as they do inside OpenTAKServer.
    import importlib
    import pkgutil

    import sqlalchemy.exc
    from flask_security import Security, SQLAlchemyUserDatastore
    from flask_security.models import fsqla_v3 as fsqla

    try:
        fsqla.FsModels.set_db_info(db)
    except sqlalchemy.exc.InvalidRequestError:
        pass

    import opentakserver.models as ots_models

    for module in pkgutil.iter_modules(ots_models.__path__):
        importlib.import_module(f"opentakserver.models.{module.name}")

    from opentakserver.models.role import Role
    from opentakserver.models.user import User
    from opentakserver.models.WebAuthn import WebAuthn

    app.security = Security(app, SQLAlchemyUserDatastore(db, User, Role, WebAuthn))

    from skitak.plugin import SkiTAKPlugin

    plugin = SkiTAKPlugin()
    app.register_blueprint(plugin.blueprint)

    with app.app_context():
        db.session.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        db.session.commit()
        db.create_all()
        plugin._apply_schema()

    return app


@pytest.fixture()
def session(app):
    """A DB session with all SkiTAK tables (and OTS group tables) emptied."""
    from opentakserver.models.Group import Group
    from opentakserver.models.GroupUser import GroupUser

    with app.app_context():
        for table in TABLES:
            db.session.execute(text(f"DELETE FROM {table}"))
        db.session.query(GroupUser).delete()
        db.session.query(Group).delete()
        db.session.commit()
        yield db.session
        db.session.rollback()


@pytest.fixture()
def client(app):
    return app.test_client()
