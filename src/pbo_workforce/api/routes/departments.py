"""Department and FTE endpoints."""

from typing import Annotated

from fastapi import APIRouter, Path, Query
from pydantic import BeforeValidator

from pbo_workforce.api.deps import SessionDep, SettingsDep
from pbo_workforce.api.errors import ApiError
from pbo_workforce.api.schemas import (
    Department,
    DepartmentsResponse,
    ErrorResponse,
    FtePerQuarterResponse,
    FteQuarter,
    TenureFilter,
)
from pbo_workforce.domain.tenure import FTE_TENURES
from pbo_workforce.repositories.departments import get_department, list_departments
from pbo_workforce.repositories.workforce import fte_per_quarter

router = APIRouter(prefix="/api/departments", tags=["departments"])

# PostgreSQL integer range: larger IDs cannot exist, and passing one to the
# database would raise an out-of-range error (a 500) instead of a 404.
_MAX_ID = 2_147_483_647


def _lower(value: object) -> object:
    return value.lower() if isinstance(value, str) else value


# ``?tenure=Term`` and ``?tenure=term`` are equivalent (D12).
TenureParam = Annotated[TenureFilter, BeforeValidator(_lower)]


@router.get("", response_model=DepartmentsResponse)
def get_departments(session: SessionDep) -> DepartmentsResponse:
    """List all departments with bilingual long and short names."""
    return DepartmentsResponse(
        departments=[Department.from_row(row) for row in list_departments(session)]
    )


@router.get(
    "/{dept_id}/fte",
    response_model=FtePerQuarterResponse,
    response_model_exclude_unset=True,
    responses={404: {"model": ErrorResponse, "description": "Unknown department"}},
)
def get_fte_per_quarter(
    *,
    session: SessionDep,
    settings: SettingsDep,
    dept_id: Annotated[int, Path(ge=1, le=_MAX_ID)],
    year: Annotated[
        int | None, Query(ge=2000, le=2100, description="Year of the quarter.")
    ] = None,
    # A plain array (not ``| None``) so OpenAPI and Swagger UI show a
    # multi-select of the allowed values; empty means all tenures.
    tenure: Annotated[
        list[TenureParam],
        Query(
            default_factory=list,
            description="Tenures to include; repeat for several. Default: all.",
        ),
    ],
) -> FtePerQuarterResponse:
    """Mean monthly FTE per quarter and tenure for one department.

    Quarters are calendar quarters by default (``QUARTER_BASIS``). RCMP and
    CAF report headcount only, so their list is empty (D11).
    """
    if get_department(session, dept_id) is None:
        raise ApiError(404, "department_not_found", f"No department with id {dept_id}")
    tenures = [t.to_tenure() for t in tenure] if tenure else list(FTE_TENURES)
    quarters = fte_per_quarter(
        session, dept_id, settings.quarter_basis, year=year, tenures=tenures
    )
    return FtePerQuarterResponse(
        fte_per_quarter=[FteQuarter.from_quarter(q) for q in quarters]
    )
