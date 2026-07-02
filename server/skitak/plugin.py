"""
SkiTAK plugin entry point for OpenTAKServer.

OTS discovers this class via the `opentakserver.plugin` entry point group
(see pyproject.toml) and calls, in order:

  1. load_metadata()        — before activation, no app context
  2. activate(app, enabled) — inside the running server
  3. registers self.blueprint on the Flask app

The blueprint tree gives us:
  /api/skitak/...   sessions, teams, tracks (authenticated)
  /api/skitak/clients/...  client roster (authenticated)
  /api/skitak/enroll/<token>...  token-gated enrollment (anonymous by design)
  /join/<token>     invite landing page (anonymous)
"""
from __future__ import annotations

import os
import traceback
from importlib import metadata as importlib_metadata
from pathlib import Path

from flask import Blueprint, Flask
from opentakserver.extensions import db, logger
from opentakserver.plugins.Plugin import Plugin
from sqlalchemy import text


class SkiTAKPlugin(Plugin):

    def __init__(self):
        super().__init__()
        self.name = "SkiTAK"
        self.distro = "skitak"
        self.blueprint = _build_blueprint()
        self._enabled = False

    # ── Plugin contract ───────────────────────────────────────────────────

    def load_metadata(self) -> dict:
        try:
            md = importlib_metadata.metadata(self.distro)
            self.metadata = {
                "name": self.name,
                "distro": self.distro,
                "author": md.get("Author", "SkiTAK"),
                "version": md.get("Version", "0.0.0"),
            }
        except importlib_metadata.PackageNotFoundError:
            self.metadata = {
                "name": self.name,
                "distro": self.distro,
                "author": "SkiTAK",
                "version": "0.0.0",
            }
        return self.metadata

    def activate(self, app: Flask, enabled: bool = True) -> None:
        self._app = app
        self._enabled = enabled
        if not enabled:
            logger.info("SkiTAK plugin is disabled — skipping activation")
            return

        with app.app_context():
            try:
                self._apply_schema()
            except Exception as e:
                logger.error(f"SkiTAK: failed to apply database schema: {e}")
                logger.error(traceback.format_exc())
                raise

            try:
                self._set_admin_password(app)
            except Exception as e:
                # Never block startup on this; the default-password warning below still fires
                logger.error(f"SkiTAK: failed to set administrator password: {e}")

        logger.info(f"SkiTAK plugin v{self.metadata.get('version')} activated")

    def stop(self) -> None:
        self._enabled = False

    def get_info(self) -> dict | None:
        return {**self.metadata, "enabled": self._enabled}

    # ── Startup work ──────────────────────────────────────────────────────

    def _apply_schema(self) -> None:
        """Apply the SkiTAK DDL. Every statement is idempotent (IF NOT EXISTS)."""
        # PostGIS normally comes from docker/postgres/init.sql (superuser);
        # try here too so non-Docker setups work when the DB user is allowed to.
        try:
            with db.engine.begin() as conn:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        except Exception as e:
            logger.warning(
                f"SkiTAK: could not ensure the postgis extension exists ({e}); "
                "if the schema fails next, create it as a superuser"
            )

        schema = (Path(__file__).parent / "schema.sql").read_text()
        # Strip `--` comments before splitting on ';' — psycopg3 executes one
        # statement at a time. schema.sql must not put ';' or '--' inside
        # string literals.
        stripped = "\n".join(line.split("--")[0] for line in schema.splitlines())
        with db.engine.begin() as conn:
            for statement in stripped.split(";"):
                if statement.strip():
                    conn.execute(text(statement))
        logger.info("SkiTAK: database schema is up to date")

    @staticmethod
    def _set_admin_password(app: Flask) -> None:
        """
        OTS creates an `administrator` account with the password `password`.
        If SKITAK_ADMIN_PASSWORD is set and the account still has the default
        password, replace it. If it's unset and the default is live, warn loudly.
        """
        from flask_security.utils import hash_password, verify_password

        datastore = app.security.datastore
        admin = datastore.find_user(username="administrator")
        if admin is None:
            return

        has_default_password = verify_password("password", admin.password)
        wanted = os.environ.get("SKITAK_ADMIN_PASSWORD")

        if wanted and has_default_password:
            admin.password = hash_password(wanted)
            db.session.commit()
            logger.info("SkiTAK: administrator password set from SKITAK_ADMIN_PASSWORD")
        elif has_default_password:
            logger.warning(
                "SkiTAK: the administrator account still has the DEFAULT password. "
                "Set SKITAK_ADMIN_PASSWORD or change it immediately."
            )


def _build_blueprint() -> Blueprint:
    from .api import bp as api_bp
    from .clients import bp as clients_bp
    from .enrollment import bp as enrollment_bp
    from .join import bp as join_bp

    parent = Blueprint("skitak_plugin", __name__)
    parent.register_blueprint(api_bp)
    parent.register_blueprint(clients_bp)
    parent.register_blueprint(enrollment_bp)
    parent.register_blueprint(join_bp)
    return parent
