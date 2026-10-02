"""YYYYMM parsing and quarter mapping (D1, D2)."""

from datetime import date

import pytest

from pbo_workforce.domain.period import (
    Quarter,
    QuarterBasis,
    YearMonth,
    parse_yyyymm,
    to_quarter,
    year_bounds,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (201503, YearMonth(2015, 3)),
        (202606, YearMonth(2026, 6)),
        (201512.0, YearMonth(2015, 12)),
        ("201601", YearMonth(2016, 1)),
        (" 201601 ", YearMonth(2016, 1)),
    ],
)
def test_parse_yyyymm_accepts(value: object, expected: YearMonth):
    assert parse_yyyymm(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        201503.5,
        201500,  # month 0
        201513,  # month 13
        2015,  # too short
        2015031,  # too long
        "2015-03",
        "",
        "٢٠١٥٠٣",  # Arabic-Indic digits: isdecimal() but not ASCII
        -201503,
        date(2015, 3, 1),
    ],
)
def test_parse_yyyymm_rejects(value: object):
    with pytest.raises(ValueError, match=r"YYYYMM|month|year"):
        parse_yyyymm(value)


def test_first_day_is_first_of_month():
    assert YearMonth(2021, 12).first_day() == date(2021, 12, 1)


def test_quarter_rejects_out_of_range():
    with pytest.raises(ValueError, match="quarter"):
        Quarter(2020, 5)


@pytest.mark.parametrize(
    ("month", "quarter"),
    [(1, 1), (3, 1), (4, 2), (6, 2), (7, 3), (9, 3), (10, 4), (12, 4)],
)
def test_calendar_quarter(month: int, quarter: int):
    assert to_quarter(YearMonth(2020, month), QuarterBasis.CALENDAR) == Quarter(
        2020, quarter
    )


@pytest.mark.parametrize(
    ("ym", "expected"),
    [
        (YearMonth(2025, 4), Quarter(2025, 1)),  # fiscal year starts in April
        (YearMonth(2025, 6), Quarter(2025, 1)),
        (YearMonth(2025, 7), Quarter(2025, 2)),
        (YearMonth(2025, 10), Quarter(2025, 3)),
        (YearMonth(2025, 12), Quarter(2025, 3)),
        (YearMonth(2026, 1), Quarter(2025, 4)),  # Jan-Mar belong to prior FY
        (YearMonth(2026, 3), Quarter(2025, 4)),  # last month of FY 2025-26
        (YearMonth(2026, 4), Quarter(2026, 1)),  # boundary: next FY
    ],
)
def test_fiscal_quarter(ym: YearMonth, expected: Quarter):
    assert to_quarter(ym, QuarterBasis.FISCAL) == expected


@pytest.mark.parametrize(
    ("basis", "first", "last"),
    [
        (QuarterBasis.CALENDAR, YearMonth(2025, 1), YearMonth(2025, 12)),
        (QuarterBasis.FISCAL, YearMonth(2025, 4), YearMonth(2026, 3)),
    ],
)
def test_year_bounds(basis: QuarterBasis, first: YearMonth, last: YearMonth):
    assert year_bounds(2025, basis) == (first, last)


@pytest.mark.parametrize("basis", list(QuarterBasis))
def test_year_bounds_agree_with_to_quarter(basis: QuarterBasis):
    first, last = year_bounds(2025, basis)
    assert to_quarter(first, basis) == Quarter(2025, 1)
    assert to_quarter(last, basis) == Quarter(2025, 4)
