"""GET /api/departments/{id}/fte: shape, D3 values, filters, errors.

Data goes through the real importer. ASC rows (FTE):

    month    indeterminate  term  casual   student
    2021-10      29.5        9.0
    2021-11      30.5                       1.25
    2021-12      30.8                               <- no casual row
    2022-01                         1.333333

    2021 Q4: indeterminate 90.8 / 3 = 30.27, term 3.0, student 0.42
    2022 Q1: casual 1.33 (one reporting month)
"""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Connection

from pbo_workforce.api.app import create_app
from pbo_workforce.api.schemas import TenureFilter
from pbo_workforce.api.security import API_KEY_HEADER
from pbo_workforce.config import Settings
from pbo_workforce.domain.period import QuarterBasis
from pbo_workforce.domain.tenure import FTE_TENURES
from pbo_workforce.ingest.load import run_import
from tests.conftest import TEST_API_KEY
from tests.factories import build_workbook

ASC = "Accessibility Standards Canada"
ASC_ID, RCMP_ID, CAF_ID = 1, 4, 5  # order of DEFAULT_DEPARTMENTS
RCMP = "Royal Canadian Mounted Police - Members"


@pytest.fixture(autouse=True)
def imported(connection: Connection, tmp_path: Path) -> None:
    path = build_workbook(
        tmp_path / "fte.xlsx",
        fps=[
            (202110, "Indeterminate", ASC, 30, 29.5),
            (202110, "Term", ASC, 10, 9.0),
            (202111, "Indeterminate", ASC, 31, 30.5),
            (202111, "Student", ASC, 3, 1.25),
            (202112, "Indeterminate", ASC, 31, 30.8),
            (202201, "Casual", ASC, 2, 1.333333),
        ],
        rcmp=[(202503, "Combined", RCMP, 20130)],
        caf=[(202503, "Combined", "Canadian Armed Forces", 65746)],
    )
    run_import(path, connection)


def test_fte_exact_shape(client: TestClient):
    response = client.get(f"/api/departments/{ASC_ID}/fte")

    assert response.status_code == 200
    assert response.json() == {
        "fte_per_quarter": [
            {
                "year": 2021,
                "quarter": 4,
                "indeterminate": 30.27,
                "term": 3.0,
                "casual": 0.0,
                "student": 0.42,
                "missing": 0.0,
            },
            {
                "year": 2022,
                "quarter": 1,
                "indeterminate": 0.0,
                "term": 0.0,
                "casual": 1.33,
                "student": 0.0,
                "missing": 0.0,
            },
        ]
    }


def test_year_filter(client: TestClient):
    body = client.get(f"/api/departments/{ASC_ID}/fte?year=2022").json()
    assert [(q["year"], q["quarter"]) for q in body["fte_per_quarter"]] == [(2022, 1)]


def test_year_without_data_is_an_empty_list(client: TestClient):
    response = client.get(f"/api/departments/{ASC_ID}/fte?year=2015")
    assert (response.status_code, response.json()) == (200, {"fte_per_quarter": []})


def test_tenure_filter_returns_only_selected_keys(client: TestClient):
    body = client.get(f"/api/departments/{ASC_ID}/fte?tenure=casual&tenure=term").json()

    assert body["fte_per_quarter"] == [
        {"year": 2021, "quarter": 4, "term": 3.0, "casual": 0.0},
        {"year": 2022, "quarter": 1, "term": 0.0, "casual": 1.33},
    ]


def test_tenure_filter_is_case_insensitive_and_deduplicated(client: TestClient):
    body = client.get(f"/api/departments/{ASC_ID}/fte?tenure=TERM&tenure=Term").json()
    assert body["fte_per_quarter"][0] == {"year": 2021, "quarter": 4, "term": 3.0}


def test_combined_filters(client: TestClient):
    body = client.get(f"/api/departments/{ASC_ID}/fte?year=2021&tenure=student").json()
    assert body == {"fte_per_quarter": [{"year": 2021, "quarter": 4, "student": 0.42}]}


@pytest.mark.parametrize("dept_id", [RCMP_ID, CAF_ID])
def test_rcmp_and_caf_have_no_fte(client: TestClient, dept_id: int):
    # D11: headcount-only sources; documented as a question for analysts.
    response = client.get(f"/api/departments/{dept_id}/fte")
    assert (response.status_code, response.json()) == (200, {"fte_per_quarter": []})


def test_unknown_department_is_404(client: TestClient):
    response = client.get("/api/departments/999/fte")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "department_not_found",
            "message": "No department with id 999",
        }
    }


@pytest.mark.parametrize(
    "query",
    [
        "1/fte?year=abc",
        "1/fte?year=1999",
        "1/fte?year=2101",
        "1/fte?year=2021.5",
        "1/fte?tenure=permanent",
        "1/fte?tenure=combined",  # RCMP/CAF category has no FTE
        "1/fte?tenure=",
        "0/fte",
        "2147483648/fte",  # beyond PostgreSQL integer: 422, not a 500
        "abc/fte",
    ],
)
def test_invalid_parameters_are_422(client: TestClient, query: str):
    response = client.get(f"/api/departments/{query}")

    assert response.status_code == 422
    body = response.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == "invalid_request"


def test_422_message_names_the_parameter(client: TestClient):
    message = client.get("/api/departments/1/fte?year=1999").json()["error"]["message"]
    assert message.startswith("query.year:")


def test_tenure_filter_values_match_fte_tenures():
    assert [f.to_tenure() for f in TenureFilter] == list(FTE_TENURES)


def test_quarter_basis_setting_switches_to_fiscal(api_settings: Settings, app: FastAPI):
    fiscal = create_app(
        api_settings.model_copy(update={"quarter_basis": QuarterBasis.FISCAL})
    )
    fiscal.dependency_overrides = app.dependency_overrides
    with TestClient(fiscal, headers={API_KEY_HEADER: TEST_API_KEY}) as client:
        body = client.get(f"/api/departments/{ASC_ID}/fte?tenure=casual").json()

    # Oct-Dec 2021 = fiscal 2021-22 Q3; Jan 2022 = Q4 of the same fiscal year.
    assert body["fte_per_quarter"] == [
        {"year": 2021, "quarter": 3, "casual": 0.0},
        {"year": 2021, "quarter": 4, "casual": 1.33},
    ]


def test_openapi_offers_tenure_as_a_multi_select(client: TestClient):
    # A plain array of the enum (no anyOf/null) renders as a multi-select in
    # Swagger UI; docs/api.md describes that.
    schema = client.get("/openapi.json").json()
    parameters = schema["paths"]["/api/departments/{dept_id}/fte"]["get"]["parameters"]
    tenure = next(p for p in parameters if p["name"] == "tenure")
    assert tenure["required"] is False
    assert tenure["schema"]["type"] == "array"
    assert tenure["schema"]["items"] == {"$ref": "#/components/schemas/TenureFilter"}
    assert schema["components"]["schemas"]["TenureFilter"]["enum"] == [
        "indeterminate",
        "term",
        "casual",
        "student",
        "missing",
    ]
