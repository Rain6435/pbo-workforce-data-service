"""Least-privilege roles from migration 0002, checked by connecting as them.

The roles' credentials come from DATABASE_URL and IMPORT_DATABASE_URL; the
tests point them at the test database.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Connection, Engine, make_url, text
from sqlalchemy.exc import DBAPIError

from pbo_workforce.config import get_migration_settings
from pbo_workforce.db.engine import make_engine
from pbo_workforce.ingest.load import run_import
from pbo_workforce.ingest.report import Outcome
from tests.factories import build_workbook


def role_connection(url: str, test_database_url: str) -> Iterator[Connection]:
    database = make_url(test_database_url).database
    engine: Engine = make_engine(
        make_url(url).set(database=database).render_as_string(hide_password=False)
    )
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            yield connection
            transaction.rollback()
    finally:
        engine.dispose()


@pytest.fixture
def api_role(engine: Engine, test_database_url: str) -> Iterator[Connection]:
    # ``engine`` first: it applies the migrations that create the roles.
    yield from role_connection(get_migration_settings().database_url, test_database_url)


@pytest.fixture
def import_role(engine: Engine, test_database_url: str) -> Iterator[Connection]:
    yield from role_connection(
        get_migration_settings().import_database_url, test_database_url
    )


def sqlstate(connection: Connection, statement: str) -> str | None:
    """Run ``statement`` in a savepoint; return the SQLSTATE it failed with."""
    savepoint = connection.begin_nested()
    try:
        connection.execute(text(statement))
    except DBAPIError as exc:
        savepoint.rollback()
        return getattr(exc.orig, "sqlstate", None)
    savepoint.rollback()
    return None


INSUFFICIENT_PRIVILEGE = "42501"
READ_ONLY_TRANSACTION = "25006"


def test_api_role_can_read_served_data(api_role: Connection):
    assert sqlstate(api_role, "SELECT * FROM department") is None
    assert sqlstate(api_role, "SELECT * FROM workforce_current") is None


@pytest.mark.parametrize(
    "statement",
    [
        # History of row versions (D16): the API reads workforce_current only.
        "SELECT * FROM workforce_monthly",
        "SELECT * FROM import_rejection",
        "SELECT * FROM import_warning",
        "SELECT * FROM import_batch",
        "SELECT * FROM alembic_version",
    ],
)
def test_api_role_cannot_read_import_internals(api_role: Connection, statement: str):
    assert sqlstate(api_role, statement) == INSUFFICIENT_PRIVILEGE


def test_api_role_sessions_are_read_only(api_role: Connection):
    assert sqlstate(api_role, "DELETE FROM department") == READ_ONLY_TRANSACTION


def test_api_role_cannot_write_even_in_read_write_transaction(api_role: Connection):
    api_role.execute(text("SET TRANSACTION READ WRITE"))
    assert sqlstate(api_role, "DELETE FROM department") == INSUFFICIENT_PRIVILEGE


def test_api_role_has_statement_timeout(api_role: Connection):
    assert api_role.scalar(text("SHOW statement_timeout")) == "5s"


def test_import_role_cannot_change_schema(import_role: Connection):
    assert sqlstate(import_role, "CREATE TABLE t (x int)") == INSUFFICIENT_PRIVILEGE
    assert sqlstate(import_role, "DROP TABLE department") == INSUFFICIENT_PRIVILEGE
    assert sqlstate(import_role, "SELECT * FROM alembic_version") == (
        INSUFFICIENT_PRIVILEGE
    )


def test_import_role_can_run_an_import(import_role: Connection, tmp_path: Path):
    path = build_workbook(
        tmp_path / "w.xlsx",
        fps=[(202110, "Term", "Accessibility Standards Canada", 2, 1.5)],
        caf=[(201603, "Combined", "Canadian Armed Forces", 50)],
    )
    assert run_import(path, import_role).outcome is Outcome.IMPORTED
