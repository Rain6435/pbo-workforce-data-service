"""Response models matching the required JSON shapes.

Field names and nesting follow the assignment's examples exactly; these
models are the API contract and appear in the OpenAPI schema.
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from pbo_workforce.db import tables
from pbo_workforce.domain.tenure import API_FIELD, Tenure
from pbo_workforce.repositories.workforce import QuarterFte


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class LocalizedText(_Frozen):
    """A text in both official languages."""

    en: str
    fr: str


class Department(_Frozen):
    """A department with its bilingual names."""

    dept_id: int
    dept_long: LocalizedText
    # null for the departments whose source row has no short names (10 in the
    # current file); an object with empty strings would look like real data.
    dept_short: LocalizedText | None

    @classmethod
    def from_row(cls, row: tables.Department) -> "Department":
        """Build from a stored department."""
        short = None
        if row.short_name_en is not None and row.short_name_fr is not None:
            short = LocalizedText(en=row.short_name_en, fr=row.short_name_fr)
        return cls(
            dept_id=row.id,
            dept_long=LocalizedText(en=row.long_name_en, fr=row.long_name_fr),
            dept_short=short,
        )


class DepartmentsResponse(_Frozen):
    """Body of ``GET /api/departments``."""

    departments: list[Department]


class TenureFilter(StrEnum):
    """Accepted values of the ``tenure`` query parameter (case-insensitive)."""

    INDETERMINATE = "indeterminate"
    TERM = "term"
    CASUAL = "casual"
    STUDENT = "student"
    MISSING = "missing"

    def to_tenure(self) -> Tenure:
        """The domain tenure this filter selects."""
        return Tenure(self.value)


class FteQuarter(_Frozen):
    """Mean monthly FTE per tenure for one quarter, rounded to 2 decimals (D4).

    Tenure fields not selected by the ``tenure`` filter are left *unset* and
    the route serializes with ``exclude_unset``, so they are omitted rather
    than sent as null. ``exclude_none`` was not used: it would also drop a
    value that is genuinely null, hiding a bug instead of exposing it.
    """

    year: int
    quarter: int
    indeterminate: float | None = None
    term: float | None = None
    casual: float | None = None
    student: float | None = None
    missing: float | None = None

    @classmethod
    def from_quarter(cls, row: QuarterFte) -> "FteQuarter":
        """Build from a repository row, setting only the tenures it holds."""
        values = {API_FIELD[tenure]: round(fte, 2) for tenure, fte in row.fte.items()}
        return cls.model_validate({"year": row.year, "quarter": row.quarter, **values})


class FtePerQuarterResponse(_Frozen):
    """Body of ``GET /api/departments/{dept_id}/fte``."""

    fte_per_quarter: list[FteQuarter]


class HealthResponse(_Frozen):
    """Body of ``GET /health``."""

    status: str


class ErrorDetail(_Frozen):
    """Machine-readable code and human-readable message."""

    code: str
    message: str


class ErrorResponse(_Frozen):
    """Body of every error response (D13)."""

    error: ErrorDetail
