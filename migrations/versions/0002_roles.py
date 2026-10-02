"""Least-privilege database roles for the API and the importer.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-29

* ``pbo_api`` may only SELECT the two tables the API serves. It is also
  read-only at the session level and has a statement timeout, so even a bug
  in the API cannot change data or hold the database with a runaway query.
* ``pbo_import`` may read and write the application tables, but cannot
  change the schema (no DDL) and cannot touch ``alembic_version``.

Role passwords are not stored here: they are taken from ``DATABASE_URL`` and
``IMPORT_DATABASE_URL``, so the password a process connects with and the
role's password cannot drift apart. Roles are cluster-wide, so they are
created only if missing and their passwords are (re)set on every upgrade.
"""

from collections.abc import Sequence

import psycopg
from alembic import op
from psycopg import sql
from sqlalchemy import make_url

from pbo_workforce.config import get_migration_settings

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

API_ROLE = "pbo_api"
IMPORT_ROLE = "pbo_import"
ROLES = (API_ROLE, IMPORT_ROLE)

API_TABLES = ("department", "workforce_monthly")
APP_TABLES = (
    "department",
    "department_alias",
    "import_batch",
    "workforce_monthly",
    "import_rejection",
    "import_warning",
)


def _password(url: str, role: str, setting: str) -> str:
    parsed = make_url(url)
    if parsed.username != role or not parsed.password:
        raise RuntimeError(f"{setting} must connect as {role!r} with a password")
    return parsed.password


def _execute(statement: sql.Composed) -> None:
    """Run a composed statement on Alembic's connection (same transaction).

    Role DDL cannot take bind parameters, so the password is embedded as a
    literal quoted by psycopg (``sql.Literal``), never by string formatting.
    The rendered statement is executed without parameters, so nothing
    re-interprets ``%`` or ``:`` characters in a password.
    """
    pooled = op.get_bind().connection
    driver = pooled.driver_connection
    if not isinstance(driver, psycopg.Connection) or pooled.dbapi_connection is None:
        raise TypeError("migrations require an open psycopg connection")
    cursor = pooled.dbapi_connection.cursor()
    try:
        cursor.execute(statement.as_string(driver.adapters))
    finally:
        cursor.close()


def upgrade() -> None:
    """Create or update the roles, then grant their privileges."""
    settings = get_migration_settings()
    passwords = {
        API_ROLE: _password(settings.database_url, API_ROLE, "DATABASE_URL"),
        IMPORT_ROLE: _password(
            settings.import_database_url, IMPORT_ROLE, "IMPORT_DATABASE_URL"
        ),
    }
    for role, password in passwords.items():
        exists = op.get_bind().exec_driver_sql(
            "SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)
        )
        verb = "ALTER" if exists.first() else "CREATE"
        _execute(
            sql.SQL(verb + " ROLE {} WITH LOGIN PASSWORD {}").format(
                sql.Identifier(role), sql.Literal(password)
            )
        )

    api = sql.Identifier(API_ROLE)
    importer = sql.Identifier(IMPORT_ROLE)
    _execute(
        sql.SQL("ALTER ROLE {} SET default_transaction_read_only = on").format(api)
    )
    _execute(sql.SQL("ALTER ROLE {} SET statement_timeout = '5s'").format(api))
    _execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}, {}").format(api, importer))
    _execute(
        sql.SQL("GRANT SELECT ON {} TO {}").format(
            sql.SQL(", ").join(sql.Identifier(t) for t in API_TABLES), api
        )
    )
    _execute(
        sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON {} TO {}").format(
            sql.SQL(", ").join(sql.Identifier(t) for t in APP_TABLES), importer
        )
    )
    # Identity columns draw from sequences; inserting needs USAGE on them.
    _execute(
        sql.SQL("GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO {}").format(importer)
    )


def downgrade() -> None:
    """Revoke this database's grants, then drop roles no other database uses."""
    for role in (sql.Identifier(r) for r in ROLES):
        _execute(
            sql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {}").format(role)
        )
        _execute(
            sql.SQL("REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {}").format(role)
        )
        _execute(sql.SQL("REVOKE USAGE ON SCHEMA public FROM {}").format(role))
    # A role still granted privileges in another database of the cluster
    # (e.g. dev and test databases side by side) cannot be dropped; keep it.
    for role in ROLES:
        _execute(
            sql.SQL(
                "DO $$ BEGIN EXECUTE format('DROP ROLE IF EXISTS %I', {}); "
                "EXCEPTION WHEN dependent_objects_still_exist THEN "
                "RAISE NOTICE 'role % still used elsewhere; kept', {}; END $$"
            ).format(sql.Literal(role), sql.Literal(role))
        )
