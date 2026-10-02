"""API fixtures: an app wired to the rolled-back test session, and clients."""

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from pbo_workforce.api.app import create_app
from pbo_workforce.api.deps import get_session
from pbo_workforce.api.security import API_KEY_HEADER, hash_api_key
from pbo_workforce.config import Settings
from tests.conftest import TEST_API_KEY


@pytest.fixture
def api_settings() -> Settings:
    """Settings for API tests; the URL is never used (sessions are injected)."""
    return Settings(
        database_url="postgresql+psycopg://unused@localhost/unused",
        api_key_hashes=frozenset({hash_api_key(TEST_API_KEY)}),
        environment="dev",
        docs_enabled=True,
    )


@pytest.fixture
def app(api_settings: Settings, session: Session) -> FastAPI:
    """The API, with requests using the rolled-back test session."""
    app = create_app(api_settings)

    def test_session() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = test_session
    return app


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    """Authenticated client; returns 500 responses instead of re-raising."""
    with TestClient(
        app, raise_server_exceptions=False, headers={API_KEY_HEADER: TEST_API_KEY}
    ) as test_client:
        yield test_client


@pytest.fixture
def anonymous_client(app: FastAPI) -> Iterator[TestClient]:
    """Client that sends no API key."""
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
