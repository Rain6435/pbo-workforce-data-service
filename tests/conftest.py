"""Shared fixtures: a real PostgreSQL test database, migrated once per session.

Each test runs inside a transaction that is rolled back afterwards, so tests
never see each other's data. PostgreSQL DDL is transactional, so even
migration tests can run this way. API fixtures are in ``tests/api/conftest.py``.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import Connection, Engine, make_url
from sqlalchemy.orm import Session

from pbo_workforce.db.engine import make_engine

REPO_ROOT = Path(__file__).resolve().parent.parent
TEST_API_KEY = "test-key-not-a-secret"


class _TestEnv(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    test_database_url: str | None = None


def _test_database_url() -> str:
    url = _TestEnv().test_database_url
    if url is None:
        pytest.exit("TEST_DATABASE_URL is not set (see .env.example)", returncode=2)
    # The session starts by downgrading to an empty schema: refuse anything
    # that is not clearly a throwaway test database.
    database = make_url(url).database or ""
    if not database.endswith("_test"):
        pytest.exit(f"Refusing to use {database!r}: name must end in _test", 2)
    return url


def _alembic_config(connection: Connection) -> Config:
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.attributes["connection"] = connection
    return config


@pytest.fixture(scope="session")
def test_database_url() -> str:
    """URL of the test database, as the schema owner."""
    return _test_database_url()


@pytest.fixture(scope="session")
def engine(test_database_url: str) -> Iterator[Engine]:
    """Engine on the test database, reset and migrated to head once."""
    engine = make_engine(test_database_url)
    with engine.begin() as connection:
        config = _alembic_config(connection)
        command.downgrade(config, "base")
        command.upgrade(config, "head")
    yield engine
    engine.dispose()


@pytest.fixture
def connection(engine: Engine) -> Iterator[Connection]:
    """A connection inside a transaction that is rolled back after the test."""
    with engine.connect() as connection:
        transaction = connection.begin()
        yield connection
        transaction.rollback()


@pytest.fixture
def session(connection: Connection) -> Iterator[Session]:
    """ORM session on the test transaction; commits become savepoints."""
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        yield session


@pytest.fixture
def alembic_config(connection: Connection) -> Config:
    """Alembic config that runs migrations inside the test transaction."""
    return _alembic_config(connection)
