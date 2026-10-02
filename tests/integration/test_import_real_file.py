"""Import the real data/data.xlsx and check every planted data problem.

The file is imported once per module inside a transaction that is rolled
back at the end, so the tests below share one ~20 s import.
"""

from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import Connection, Engine, func, select

from pbo_workforce.db.tables import (
    Department,
    DepartmentAlias,
    ImportRejection,
    ImportWarning,
    Source,
    WorkforceMonthly,
)
from pbo_workforce.ingest.load import run_import
from pbo_workforce.ingest.report import ImportReport, SheetReport

pytestmark = pytest.mark.slow

DATA_FILE = Path(__file__).resolve().parents[2] / "data" / "data.xlsx"


@pytest.fixture(scope="module")
def imported(engine: Engine) -> Iterator[tuple[Connection, ImportReport]]:
    with engine.connect() as connection:
        transaction = connection.begin()
        report = run_import(DATA_FILE, connection)
        yield connection, report
        transaction.rollback()


@pytest.fixture
def db(imported: tuple[Connection, ImportReport]) -> Connection:
    return imported[0]


@pytest.fixture
def sheets(imported: tuple[Connection, ImportReport]) -> dict[str, SheetReport]:
    return {sheet.sheet: sheet for sheet in imported[1].sheets}


def department_id(db: Connection, name: str) -> int:
    found = db.scalar(select(Department.id).where(Department.long_name_en == name))
    assert found is not None, name
    return found


def rejected_rows(db: Connection, reason: str) -> list[int]:
    return list(
        db.scalars(
            select(ImportRejection.source_row)
            .where(ImportRejection.reason_code == reason)
            .order_by(ImportRejection.source_row)
        )
    )


def has_row(db: Connection, name: str, period: date, tenure: str) -> bool:
    return (
        db.scalar(
            select(func.count())
            .select_from(WorkforceMonthly)
            .where(
                WorkforceMonthly.department_id == department_id(db, name),
                WorkforceMonthly.period == period,
                WorkforceMonthly.tenure == tenure,
            )
        )
        == 1
    )


def test_sheet_counts_and_reconciliation(
    imported: tuple[Connection, ImportReport], sheets: dict[str, SheetReport]
):
    assert imported[1].reconciles
    counts = {
        name: (s.read, s.accepted, s.rejected, s.collapsed)
        for name, s in sheets.items()
    }
    assert counts == {
        "Departments": (102, 101, 0, 1),
        "Federal Public Service": (44408, 44391, 17, 0),
        "RCMP": (26, 26, 0, 0),
        "CAF": (26, 26, 0, 0),
    }


def test_rows_stored_per_source(db: Connection):
    stored = dict(
        db.execute(
            select(WorkforceMonthly.source, func.count()).group_by(
                WorkforceMonthly.source
            )
        ).all()
    )
    assert stored == {Source.FPS: 44391, Source.RCMP: 26, Source.CAF: 26}


def test_asc_is_department_1(db: Connection):
    assert department_id(db, "Accessibility Standards Canada") == 1


def test_problem_1_name_variants_resolve(db: Connection):
    # Workforce-sheet variants: double space, leading and trailing spaces.
    assert has_row(db, "Public Service Commission of Canada", date(2015, 10, 1), "term")
    assert has_row(
        db,
        "Innovation, Science and Economic Development Canada",
        date(2015, 12, 1),
        "casual",
    )
    assert has_row(
        db,
        "Office of the Commissioner for Federal Judicial Affairs Canada",
        date(2016, 1, 1),
        "term",
    )
    assert rejected_rows(db, "UNKNOWN_DEPARTMENT") == []


def test_problem_1_departments_sheet_names_are_stripped(db: Connection):
    names = set(db.scalars(select(Department.long_name_en)))
    for name in (
        "Canadian Armed Forces",
        "Global Affairs Canada",
        "Federal Economic Development Agency for Southern Ontario",
    ):
        assert name in names
    assert all(n == n.strip() for n in names)


def test_problem_1_misspelling_resolves_through_alias(db: Connection):
    pco = department_id(db, "Privy Council Office")
    assert db.execute(
        select(DepartmentAlias.alias_normalized, DepartmentAlias.department_id)
    ).all() == [("Privy Council Officee", pco)]
    # Row 2672 is the misspelled row; it is also missing its headcount, so it
    # is quarantined for that rather than as an unknown department.
    raw = db.scalar(
        select(ImportRejection.raw).where(ImportRejection.source_row == 2672)
    )
    assert raw is not None
    assert raw["department"] == "Privy Council Officee"
    assert 2672 in rejected_rows(db, "NULL_MEASURE")


def test_problem_2_tenure_variants_are_accepted(db: Connection):
    assert has_row(
        db, "Environment and Climate Change Canada", date(2016, 3, 1), "term"
    )
    assert has_row(
        db, "Communications Security Establishment", date(2016, 4, 1), "indeterminate"
    )
    assert rejected_rows(db, "UNKNOWN_TENURE") == []


def test_problem_3_blank_tenure_is_quarantined(db: Connection):
    assert rejected_rows(db, "BLANK_TENURE") == [3845]
    assert not has_row(
        db, "Public Prosecution Service of Canada", date(2016, 3, 1), "missing"
    )


def test_problem_4_null_measures_are_quarantined(db: Connection):
    # 9 null headcounts and 8 null FTEs, two rows with both: 15 rows.
    null_headcount = [490, 633, 639, 887, 1225, 1519, 1520, 2672, 2678]
    null_fte = [497, 633, 891, 1226, 1227, 1228, 1519, 1521]
    assert rejected_rows(db, "NULL_MEASURE") == sorted({*null_headcount, *null_fte})


def test_problem_5_negative_headcount_is_quarantined(db: Connection):
    assert rejected_rows(db, "NEGATIVE_MEASURE") == [502]


def test_problem_6_fte_above_headcount_is_a_warning(
    db: Connection, sheets: dict[str, SheetReport]
):
    # 34 rows have fte > headcount; one of them (row 502) is quarantined for
    # its negative headcount, leaving 33 accepted with a warning.
    warned = sheets["Federal Public Service"].warnings
    assert len(warned) == 33
    assert all(w.code == "FTE_EXCEEDS_HEADCOUNT" for w in warned)
    stored_fte = db.scalar(
        select(WorkforceMonthly.fte).where(WorkforceMonthly.source_row == 9238)
    )
    assert stored_fte == pytest.approx(2365.07, abs=0.01)  # value not altered


def test_problem_7_duplicate_department_collapsed(db: Connection):
    assert (
        db.scalar(
            select(func.count())
            .select_from(Department)
            .where(Department.long_name_en == "Canadian Food Inspection Agency")
        )
        == 1
    )
    assert db.execute(
        select(ImportWarning.sheet, ImportWarning.source_row).where(
            ImportWarning.reason_code == "DUPLICATE_DEPARTMENT_ROW"
        )
    ).all() == [("Departments", 14)]


def test_problem_8_missing_short_names_are_null(db: Connection):
    # 10 departments, each missing both the English and French short name.
    missing = db.execute(
        select(Department.short_name_en, Department.short_name_fr).where(
            (Department.short_name_en.is_(None)) | (Department.short_name_fr.is_(None))
        )
    ).all()
    assert len(missing) == 10
    assert all(row == (None, None) for row in missing)


def test_problem_9_suspect_rcmp_and_caf_dates_are_warnings(db: Connection):
    assert db.execute(
        select(ImportWarning.sheet, ImportWarning.source_row)
        .where(ImportWarning.reason_code == "SUSPECT_DATE")
        .order_by(ImportWarning.sheet)
    ).all() == [("CAF", 2), ("RCMP", 2)]
    # Accepted unchanged.
    assert has_row(
        db, "Royal Canadian Mounted Police - Members", date(2015, 4, 1), "combined"
    )


def test_problem_10_absent_tenure_rows_are_not_invented(db: Connection):
    tenures = set(
        db.scalars(
            select(WorkforceMonthly.tenure).where(
                WorkforceMonthly.department_id
                == department_id(db, "Accessibility Standards Canada"),
                WorkforceMonthly.period == date(2021, 12, 1),
            )
        )
    )
    assert tenures == {"indeterminate", "term", "student"}


def test_reimporting_the_same_file_changes_nothing(
    imported: tuple[Connection, ImportReport],
):
    # D16: a forced re-import compares every row with the stored version and
    # finds nothing to revise, add, or close.
    db, _ = imported
    again = run_import(DATA_FILE, db, force=True)

    assert again.reconciles
    for sheet in again.sheets:
        if sheet.versions is not None:
            assert (sheet.versions.added, sheet.versions.revised) == (0, 0)
            assert sheet.versions.closed == 0
            assert sheet.versions.unchanged == sheet.accepted
    assert db.scalar(select(func.count()).select_from(WorkforceMonthly)) == 44443
