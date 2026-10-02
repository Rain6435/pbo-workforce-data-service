"""API keys, security headers, docs exposure, and security settings."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from pydantic_settings import SettingsConfigDict
from sqlalchemy.orm import Session

from pbo_workforce.api.app import create_app
from pbo_workforce.api.deps import get_session
from pbo_workforce.api.security import API_KEY_HEADER, hash_api_key
from pbo_workforce.config import Settings

UNUSED = "postgresql+psycopg://unused@localhost/unused"
PROTECTED = ["/api/departments", "/api/departments/1/fte"]


class _ExplicitSettings(Settings):
    """Settings from explicit values only, never from the developer's .env."""

    model_config = SettingsConfigDict(env_file=None)


def settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": UNUSED,
        "environment": "dev",
        "docs_enabled": False,
    }
    return _ExplicitSettings.model_validate(values | overrides)


@pytest.mark.parametrize("path", PROTECTED)
def test_missing_key_is_401(anonymous_client: TestClient, path: str):
    response = anonymous_client.get(path)

    assert response.status_code == 401
    assert response.json() == {
        "error": {"code": "unauthorized", "message": "Missing X-API-Key header"}
    }


@pytest.mark.parametrize("key", ["wrong", "test-key-not-a-secret ", "TEST-KEY"])
def test_wrong_key_is_401(anonymous_client: TestClient, key: str):
    response = anonymous_client.get(PROTECTED[0], headers={API_KEY_HEADER: key})

    assert response.status_code == 401
    assert response.json()["error"] == {
        "code": "unauthorized",
        "message": "Invalid API key",
    }


def test_empty_key_is_treated_as_missing(anonymous_client: TestClient):
    response = anonymous_client.get(PROTECTED[0], headers={API_KEY_HEADER: ""})
    assert response.json()["error"]["message"] == "Missing X-API-Key header"


def test_valid_key_is_accepted(client: TestClient):
    assert client.get(PROTECTED[0]).status_code == 200


def test_auth_runs_before_validation(anonymous_client: TestClient):
    # An anonymous caller learns nothing about parameters or departments.
    assert anonymous_client.get("/api/departments/1/fte?year=1").status_code == 401
    assert anonymous_client.get("/api/departments/999/fte").status_code == 401


def test_any_configured_key_is_accepted(session: Session):
    app = create_app(
        settings(api_key_hashes=frozenset({hash_api_key("a"), hash_api_key("b")}))
    )
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as client:
        for key in ("a", "b"):
            response = client.get(PROTECTED[0], headers={API_KEY_HEADER: key})
            assert response.status_code == 200


def test_health_needs_no_key(anonymous_client: TestClient):
    assert anonymous_client.get("/health").status_code == 200


def test_hash_is_sha256_hex():
    assert hash_api_key("abc") == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )


@pytest.mark.parametrize(
    ("path", "status"),
    [
        ("/api/departments", 200),
        ("/health", 200),
        ("/api/departments/999/fte", 404),
        ("/api/departments/1/fte?year=1", 422),
        ("/nowhere", 404),
    ],
)
def test_security_headers_on_every_response(client: TestClient, path: str, status: int):
    response = client.get(path)

    assert response.status_code == status
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "default-src 'none'" in response.headers["content-security-policy"]


def test_security_headers_on_401(anonymous_client: TestClient):
    response = anonymous_client.get(PROTECTED[0])
    assert response.headers["cache-control"] == "no-store"


def test_security_headers_on_500(app: FastAPI, client: TestClient):
    def broken() -> Session:
        raise RuntimeError("boom")

    app.dependency_overrides[get_session] = broken

    response = client.get(PROTECTED[0])

    assert response.status_code == 500
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_no_cors_headers_by_default(client: TestClient):
    response = client.get(PROTECTED[0], headers={"Origin": "https://example.org"})
    assert "access-control-allow-origin" not in response.headers


def test_docs_disabled_by_default():
    app = create_app(settings(environment="dev", api_key_hashes="0" * 64))
    with TestClient(app) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404


def test_docs_when_enabled_document_the_api_key(client: TestClient):
    docs = client.get("/docs")
    assert docs.status_code == 200
    assert "content-security-policy" not in docs.headers  # Swagger UI needs CDN

    schema = client.get("/openapi.json").json()
    assert schema["components"]["securitySchemes"]["APIKeyHeader"] == {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-Key",
        "description": "API key issued to the client.",
    }


def test_settings_read_hashes_from_comma_separated_env(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("API_KEY_HASHES", f" {'A' * 64} , {'b' * 64},")
    assert settings().api_key_hashes == frozenset({"a" * 64, "b" * 64})


def test_settings_reject_plaintext_keys():
    with pytest.raises(ValidationError, match="SHA-256"):
        settings(api_key_hashes="my-secret-key")


def test_settings_refuse_docs_in_prod():
    with pytest.raises(ValidationError, match="DOCS_ENABLED"):
        settings(environment="prod", docs_enabled=True, api_key_hashes="0" * 64)


def test_settings_refuse_prod_without_keys():
    with pytest.raises(ValidationError, match="API_KEY_HASHES"):
        settings(environment="prod", api_key_hashes="")
