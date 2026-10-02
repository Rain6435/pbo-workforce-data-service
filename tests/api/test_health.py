"""GET /health: database ping, no authentication."""

from collections.abc import Iterator

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from pbo_workforce.api.deps import get_session
from pbo_workforce.db.engine import make_engine

# Nothing listens on port 1, so connecting fails immediately.
UNREACHABLE = "postgresql+psycopg://nobody@127.0.0.1:1/none?connect_timeout=2"


def test_health_ok(client: TestClient):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_503_when_database_is_down(app: FastAPI, client: TestClient):
    engine = make_engine(UNREACHABLE)

    def unreachable_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = unreachable_session

    response = client.get("/health")

    assert response.status_code == 503
    assert response.json() == {
        "error": {"code": "unavailable", "message": "Database unavailable"}
    }
    assert "127.0.0.1" not in response.text
    engine.dispose()
