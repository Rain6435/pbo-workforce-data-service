"""Row validation: one test per reason and warning code (D7-D10)."""

import pytest

from pbo_workforce.db.tables import Source
from pbo_workforce.domain.period import YearMonth
from pbo_workforce.domain.tenure import Tenure
from pbo_workforce.ingest.aliases import KNOWN_ALIASES
from pbo_workforce.ingest.normalize import DepartmentResolver
from pbo_workforce.ingest.reader import CellValue, RawRow, SourceFileError
from pbo_workforce.ingest.sources import CAF, DEPARTMENTS_SHEET, FPS, RCMP, SheetSpec
from pbo_workforce.ingest.validate import (
    Accepted,
    DepartmentRecord,
    Rejected,
    RejectReason,
    WarningCode,
    reject_duplicate_keys,
    validate_departments,
    validate_row,
)

RESOLVER = DepartmentResolver(
    ["Privy Council Office", "Canadian Armed Forces"], KNOWN_ALIASES
)


def fps_row(row_number: int = 2, /, **values: CellValue) -> RawRow:
    base: dict[str, CellValue] = {
        "date": 201511,
        "tenure": "Term",
        "department": "Privy Council Office",
        "headcount": 20,
        "fte": 15.8,
    }
    return RawRow(FPS.name, row_number, base | values)


def caf_row(**values: CellValue) -> RawRow:
    base: dict[str, CellValue] = {
        "date": 201603,
        "tenure": "Combined",
        "department": "Canadian Armed Forces",
        "headcount": 66602,
    }
    return RawRow(CAF.name, 2, base | values)


def rejection(raw: RawRow, spec: SheetSpec = FPS) -> RejectReason:
    result = validate_row(raw, spec, RESOLVER)
    assert isinstance(result, Rejected)
    assert result.raw == raw.values  # raw values kept for the quarantine table
    return result.reason


def accepted(raw: RawRow, spec: SheetSpec = FPS) -> Accepted:
    result = validate_row(raw, spec, RESOLVER)
    assert isinstance(result, Accepted), result
    return result


def test_valid_fps_row_is_accepted():
    row = accepted(fps_row())
    assert (row.department, row.period, row.tenure) == (
        "Privy Council Office",
        YearMonth(2015, 11),
        Tenure.TERM,
    )
    assert (row.headcount, row.fte, row.source, row.warnings) == (
        20,
        15.8,
        Source.FPS,
        (),
    )


def test_valid_caf_row_has_no_fte():
    row = accepted(caf_row(), CAF)
    assert (row.tenure, row.fte, row.source) == (Tenure.COMBINED, None, Source.CAF)


def test_alias_resolves_to_canonical_department():
    assert accepted(fps_row(department="Privy Council Officee")).department == (
        "Privy Council Office"
    )


@pytest.mark.parametrize("date", [201513, 2015, "Nov 2015", None, 201511.5])
def test_invalid_date(date: CellValue):
    assert rejection(fps_row(date=date)) is RejectReason.INVALID_DATE


@pytest.mark.parametrize("department", ["Privy Council Offic", None, 42])
def test_unknown_department(department: CellValue):
    assert rejection(fps_row(department=department)) is RejectReason.UNKNOWN_DEPARTMENT


def test_blank_tenure():
    # D7: blank is a data error, not the reported category "Missing".
    assert rejection(fps_row(tenure=None)) is RejectReason.BLANK_TENURE


@pytest.mark.parametrize("tenure", ["Permanent", "Combined", 3])
def test_unknown_tenure(tenure: CellValue):
    assert rejection(fps_row(tenure=tenure)) is RejectReason.UNKNOWN_TENURE


def test_fps_tenure_not_allowed_in_caf():
    assert rejection(caf_row(tenure="Term"), CAF) is RejectReason.UNKNOWN_TENURE


@pytest.mark.parametrize("column", ["headcount", "fte"])
def test_null_measure(column: str):
    assert rejection(fps_row(**{column: None})) is RejectReason.NULL_MEASURE


def test_null_headcount_in_caf():
    assert rejection(caf_row(headcount=None), CAF) is RejectReason.NULL_MEASURE


@pytest.mark.parametrize(
    "values",
    [
        {"headcount": "20"},
        {"fte": "n/a"},
        {"headcount": 20.5},
        {"fte": float("nan")},
        {"fte": float("inf")},
    ],
)
def test_invalid_measure(values: dict[str, CellValue]):
    assert rejection(fps_row(**values)) is RejectReason.INVALID_MEASURE


def test_integral_float_headcount_is_accepted():
    assert accepted(fps_row(headcount=20.0)).headcount == 20


@pytest.mark.parametrize("values", [{"headcount": -20}, {"fte": -0.5}])
def test_negative_measure(values: dict[str, CellValue]):
    assert rejection(fps_row(**values)) is RejectReason.NEGATIVE_MEASURE


def test_first_failing_check_wins():
    raw = fps_row(date=None, department="Nowhere", tenure=None, headcount=-1)
    assert rejection(raw) is RejectReason.INVALID_DATE


def test_alias_resolved_row_with_null_measure_is_null_measure():
    # The real file's misspelled row also lacks a headcount (row 2672).
    raw = fps_row(department="Privy Council Officee", headcount=None)
    assert rejection(raw) is RejectReason.NULL_MEASURE


def test_fte_exceeds_headcount_is_accepted_with_warning():
    row = accepted(fps_row(headcount=3, fte=3.07))
    assert row.fte == 3.07  # D9: value kept as-is
    assert [w.code for w in row.warnings] == [WarningCode.FTE_EXCEEDS_HEADCOUNT]


def test_fte_equal_to_headcount_is_not_a_warning():
    assert accepted(fps_row(headcount=3, fte=3)).warnings == ()


@pytest.mark.parametrize("spec", [RCMP, CAF])
def test_off_cadence_date_is_suspect(spec: SheetSpec):
    raw = RawRow(
        spec.name,
        2,
        {
            "date": 201504,
            "tenure": "Combined",
            "department": "Canadian Armed Forces",
            "headcount": 1,
        },
    )
    row = accepted(raw, spec)
    assert [w.code for w in row.warnings] == [WarningCode.SUSPECT_DATE]
    assert row.warnings[0].row_number == 2


@pytest.mark.parametrize("date", [201603, 202503, 202504, 202606])
def test_on_cadence_dates_are_not_suspect(date: int):
    assert accepted(caf_row(date=date), CAF).warnings == ()


def test_fps_has_no_cadence_rule():
    assert accepted(fps_row(date=201504)).warnings == ()


def test_duplicate_keys_reject_every_copy():
    first = accepted(fps_row(2))
    second = accepted(fps_row(3, tenure="Term ", fte=10.0))  # same key
    other = accepted(fps_row(4, tenure="Casual"))

    kept, rejected = reject_duplicate_keys([first, second, other])

    assert kept == [other]
    assert [(r.row_number, r.reason) for r in rejected] == [
        (2, RejectReason.DUPLICATE_KEY),
        (3, RejectReason.DUPLICATE_KEY),
    ]


def test_same_key_in_different_sources_is_not_duplicate():
    fps = accepted(fps_row(tenure="Missing"))
    caf = accepted(caf_row(date=201511, department="Privy Council Office"), CAF)
    assert reject_duplicate_keys([fps, caf]) == ([fps, caf], [])


def dept_row(row_number: int, *values: CellValue) -> RawRow:
    keys = ("long_name_en", "long_name_fr", "short_name_en", "short_name_fr")
    return RawRow(DEPARTMENTS_SHEET, row_number, dict(zip(keys, values, strict=True)))


def test_departments_are_canonicalized_in_sheet_order():
    records, warnings = validate_departments(
        [
            dept_row(
                2, "Canadian Armed Forces ", "Forces armées canadiennes ", "CAF", "FAC"
            ),
            dept_row(
                3, " Global Affairs Canada", "Affaires mondiales Canada", "GAC", "AMC"
            ),
            dept_row(
                4,
                "Office of the Prime Minister",
                "Cabinet du Premier ministre",
                None,
                None,
            ),
        ]
    )
    assert records == [
        DepartmentRecord(
            "Canadian Armed Forces", "Forces armées canadiennes", "CAF", "FAC"
        ),
        DepartmentRecord(
            "Global Affairs Canada", "Affaires mondiales Canada", "GAC", "AMC"
        ),
        DepartmentRecord(
            "Office of the Prime Minister", "Cabinet du Premier ministre", None, None
        ),
    ]
    assert warnings == []


def test_identical_duplicate_department_is_collapsed_with_warning():
    cfia = ("Canadian Food Inspection Agency", "ACIA long", "CFIA", "ACIA")
    records, warnings = validate_departments([dept_row(13, *cfia), dept_row(14, *cfia)])
    assert len(records) == 1
    assert [(w.row_number, w.code) for w in warnings] == [
        (14, WarningCode.DUPLICATE_DEPARTMENT_ROW)
    ]


def test_conflicting_duplicate_department_fails():
    with pytest.raises(SourceFileError, match="rows 13 and 14"):
        validate_departments(
            [
                dept_row(13, "Canadian Food Inspection Agency", "A", "CFIA", "ACIA"),
                dept_row(14, "Canadian Food Inspection Agency ", "B", "CFIA", "ACIA"),
            ]
        )


@pytest.mark.parametrize("column", [0, 1])
def test_blank_long_name_fails(column: int):
    values: list[CellValue] = ["English", "French", None, None]
    values[column] = None
    with pytest.raises(SourceFileError, match="is blank"):
        validate_departments([dept_row(5, *values)])
