"""GET /api/departments: shape, ordering, and the shared error format."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from pbo_workforce.api.deps import get_session
from pbo_workforce.db.tables import Department


def add_departments(session: Session) -> None:
    # Inserted out of ID order to prove the endpoint sorts.
    session.add_all(
        [
            Department(
                id=2,
                long_name_en="Office of the Prime Minister",
                long_name_fr="Cabinet du Premier ministre",
            ),
            Department(
                id=1,
                long_name_en="Accessibility Standards Canada",
                long_name_fr="Normes d\u2019accessibilité Canada",
                short_name_en="ASC",
                short_name_fr="NAC",
            ),
        ]
    )
    session.flush()


def test_departments_exact_shape_and_order(client: TestClient, session: Session):
    add_departments(session)

    response = client.get("/api/departments")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {
        "departments": [
            {
                "dept_id": 1,
                "dept_long": {
                    "en": "Accessibility Standards Canada",
                    "fr": "Normes d\u2019accessibilité Canada",
                },
                "dept_short": {"en": "ASC", "fr": "NAC"},
            },
            {
                "dept_id": 2,
                "dept_long": {
                    "en": "Office of the Prime Minister",
                    "fr": "Cabinet du Premier ministre",
                },
                "dept_short": None,
            },
        ]
    }


def test_departments_empty(client: TestClient):
    assert client.get("/api/departments").json() == {"departments": []}


def test_unknown_route_uses_standard_error_body(client: TestClient):
    response = client.get("/api/nothing-here")

    assert response.status_code == 404
    assert response.json() == {"error": {"code": "not_found", "message": "Not Found"}}


def test_wrong_method_uses_standard_error_body(client: TestClient):
    response = client.post("/api/departments")

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"


def test_unexpected_error_hides_details(
    app: FastAPI, client: TestClient, caplog: pytest.LogCaptureFixture
):
    def broken_session() -> Session:
        raise RuntimeError("SELECT secret FROM department")

    app.dependency_overrides[get_session] = broken_session

    response = client.get("/api/departments")

    assert response.status_code == 500
    error = response.json()["error"]
    assert error["code"] == "internal_error"
    assert "secret" not in response.text
    assert "Traceback" not in response.text
    # The reference in the response lets support find the logged traceback.
    reference = error["message"].split("reference ")[1].rstrip(")")
    assert any(reference in record.getMessage() for record in caplog.records)
    assert any(record.exc_info for record in caplog.records)
