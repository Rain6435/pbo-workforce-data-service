"""Monthly periods, quarters, and the quarter basis (calendar or fiscal).

Data is stored monthly (D1); quarters are derived when queried so the quarter
definition stays a documented, configurable choice (D2).
"""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class QuarterBasis(StrEnum):
    """How months are grouped into quarters."""

    # Q1 = January to March.
    CALENDAR = "calendar"
    # Government of Canada fiscal year, April to March. Q1 = April to June.
    # The fiscal year is labelled by the calendar year it starts in, so
    # fiscal 2025-26 is year 2025 and March 2026 is 2025 Q4.
    FISCAL = "fiscal"


@dataclass(frozen=True, order=True)
class YearMonth:
    """A calendar month."""

    year: int
    month: int

    def __post_init__(self) -> None:
        if not 1 <= self.month <= 12:
            raise ValueError(f"month must be 1-12, got {self.month}")
        if not 1900 <= self.year <= 9999:
            raise ValueError(f"year must be 1900-9999, got {self.year}")

    def first_day(self) -> date:
        """The first day of the month, as stored in ``workforce_monthly.period``."""
        return date(self.year, self.month, 1)


@dataclass(frozen=True, order=True)
class Quarter:
    """A quarter within a (calendar or fiscal) year."""

    year: int
    quarter: int

    def __post_init__(self) -> None:
        if not 1 <= self.quarter <= 4:
            raise ValueError(f"quarter must be 1-4, got {self.quarter}")


def parse_yyyymm(value: object) -> YearMonth:
    """Parse a source ``date`` cell holding ``YYYYMM``.

    Accepts an int, an integral float (Excel stores numbers as floats), or a
    six-digit string (a cell formatted as text). Rejects bools, which are ints
    in Python but never a valid date, and anything that is not exactly six
    digits, so ``2015`` or ``2015031`` cannot be misread.

    Raises:
        ValueError: if ``value`` is not a valid ``YYYYMM``.
    """
    if isinstance(value, bool):
        raise ValueError(f"not a YYYYMM value: {value!r}")
    if isinstance(value, float):
        if not value.is_integer():
            raise ValueError(f"not a YYYYMM value: {value!r}")
        value = int(value)
    if isinstance(value, int):
        text = str(value)
    elif isinstance(value, str):
        text = value.strip()
    else:
        raise ValueError(f"not a YYYYMM value: {value!r}")
    if len(text) != 6 or not text.isdecimal() or not text.isascii():
        raise ValueError(f"not a YYYYMM value: {value!r}")
    return YearMonth(int(text[:4]), int(text[4:]))


def quarter_offset_months(basis: QuarterBasis) -> int:
    """Months between January and the first month of ``basis``'s year.

    Shifting a month back by this offset and taking its calendar quarter
    gives its quarter under ``basis``. ``to_quarter`` and the SQL in
    ``repositories/workforce.py`` both use it, so there is one definition.
    """
    match basis:
        case QuarterBasis.CALENDAR:
            return 0
        case QuarterBasis.FISCAL:
            return 3


def to_quarter(ym: YearMonth, basis: QuarterBasis) -> Quarter:
    """Return the quarter that ``ym`` falls in under ``basis``.

    The function converts a calendar month into a quarter label expressed in the
    chosen quarter basis. The key idea is to shift each month by a constant
    offset so that the first month of the reporting year lines up with January in
    an internal, basis-normalized timeline.

    For a calendar basis, the reporting year starts in January and the offset is
    zero. For a fiscal basis, the reporting year starts in April and the offset is
    three months, because April is treated as the first month of fiscal year
    ``Y``.

    The normalized month index is computed as:

        index = ym.year * 12 + (ym.month - 1) - quarter_offset_months(basis)

    This effectively re-labels months relative to the start of the reporting
    year. Dividing by 12 gives the reporting year number, and the remainder
    divided by 3 gives the quarter number within that year:

        reporting_year = index // 12
        quarter_number = (index % 12) // 3 + 1

    Examples:
        - ``YearMonth(2024, 1)`` with ``CALENDAR`` -> ``Quarter(2024, 1)``.
        - ``YearMonth(2024, 4)`` with ``FISCAL`` -> ``Quarter(2024, 1)``.
        - ``YearMonth(2025, 3)`` with ``FISCAL`` -> ``Quarter(2024, 4)``.

    This preserves the rule that quarter labels are derived from the chosen
    basis rather than stored separately, so the definition remains consistent
    across any downstream use, including SQL queries and reporting logic.
    """
    index = ym.year * 12 + (ym.month - 1) - quarter_offset_months(basis)
    return Quarter(index // 12, index % 12 // 3 + 1)


def year_bounds(year: int, basis: QuarterBasis) -> tuple[YearMonth, YearMonth]:
    """First and last month of ``year`` under ``basis`` (inclusive)."""
    offset = quarter_offset_months(basis)
    first = year * 12 + offset
    last = first + 11
    return YearMonth(first // 12, first % 12 + 1), YearMonth(last // 12, last % 12 + 1)
