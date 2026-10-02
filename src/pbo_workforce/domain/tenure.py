"""Tenure categories and parsing of raw tenure labels."""

from enum import StrEnum


class Tenure(StrEnum):
    """Employment tenure as reported by the source.

    ``COMBINED`` is used by the RCMP and CAF sheets, which report a single
    headcount with no tenure breakdown.
    """

    INDETERMINATE = "indeterminate"
    TERM = "term"
    CASUAL = "casual"
    STUDENT = "student"
    MISSING = "missing"
    COMBINED = "combined"


# The five Federal Public Service categories that carry FTE, in the order the
# API returns them. ``MISSING`` is a category the source reports (tenure not
# recorded by the employer), not an absence of data.
FTE_TENURES: tuple[Tenure, ...] = (
    Tenure.INDETERMINATE,
    Tenure.TERM,
    Tenure.CASUAL,
    Tenure.STUDENT,
    Tenure.MISSING,
)

# JSON field name for each FTE tenure in ``fte_per_quarter`` objects. Kept as
# an explicit mapping so renaming an enum value cannot silently change the API.
API_FIELD: dict[Tenure, str] = {
    Tenure.INDETERMINATE: "indeterminate",
    Tenure.TERM: "term",
    Tenure.CASUAL: "casual",
    Tenure.STUDENT: "student",
    Tenure.MISSING: "missing",
}


def parse_tenure(raw: str | None) -> Tenure | None:
    """Map a raw source label to a ``Tenure``, or ``None`` if it is not one.

    Matching ignores surrounding whitespace and case, which absorbs the
    ``"Term "`` and ``"Indeterminate "`` variants in the source (D7). A blank
    label also returns ``None``: callers that must tell blank from unknown
    (the validator does, D7/D8) check for blank first.
    """
    if raw is None:
        return None
    try:
        return Tenure(raw.strip().casefold())
    except ValueError:
        return None
