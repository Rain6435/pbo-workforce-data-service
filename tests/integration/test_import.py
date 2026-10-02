"""Import pipeline on small factory workbooks: counts, idempotency, rollback."""

from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import Connection, func, select

from pbo_workforce.config import get_import_settings
from pbo_workforce.db.tables import (
    BatchStatus,
    ClosedReason,
    Department,
    DepartmentAlias,
    ImportBatch,
    ImportRejection,
    ImportWarning,
    WorkforceMonthly,
    workforce_current,
)
from pbo_workforce.ingest.cli import main
from pbo_workforce.ingest.load import run_import
from pbo_workforce.ingest.reader import SourceFileError
from pbo_workforce.ingest.report import (
    ImportReport,
    Outcome,
    SheetReport,
    VersionCounts,
)
from pbo_workforce.ingest.sources import CAF, FPS, RCMP
from tests.factories import (
    ASC,
    CAF_DEPT,
    CFIA,
    DEFAULT_DEPARTMENTS,
    PCO,
    RCMP_MEMBERS,
    build_workbook,
)

ASC_NAME = "Accessibility Standards Canada"
PCO_NAME = "Privy Council Office"
RCMP_NAME = "Royal Canadian Mounted Police - Members"

# One row per rule; Excel row numbers in comments.
PLANTED_FPS = [
    (202110, "Indeterminate", ASC_NAME, 10, 9.5),  # 2 accepted
    (202110, "Term ", ASC_NAME, 2, 2.5),  # 3 accepted, FTE_EXCEEDS_HEADCOUNT
    (202110, "Casual", "Privy Council Officee", 5, 4),  # 4 accepted via alias
    (202110, None, PCO_NAME, 3, 3),  # 5 BLANK_TENURE
    (202110, "Student", "Privy  Council Office", None, 1),  # 6 NULL_MEASURE
    (202110, "Term", "Unknown Agency", 1, 1),  # 7 UNKNOWN_DEPARTMENT
    (202113, "Term", PCO_NAME, 1, 1),  # 8 INVALID_DATE
    (202110, "Term", PCO_NAME, -1, 1),  # 9 NEGATIVE_MEASURE
    (202111, "Term", f" {PCO_NAME}", 4, 4),  # 10 DUPLICATE_KEY (with 11)
    (202111, "Term", PCO_NAME, 5, 5),  # 11 DUPLICATE_KEY (with 10)
    (202110, "Combined", PCO_NAME, 1, 1),  # 12 UNKNOWN_TENURE
]
PLANTED_RCMP = [
    (201504, "Combined", RCMP_NAME, 100),  # 2 SUSPECT_DATE
    (201603, "Combined", RCMP_NAME, 100),
    (202503, "Combined", RCMP_NAME, 101),
]
PLANTED_CAF = [(201603, "Combined", "Canadian Armed Forces", 50)]
PLANTED_DEPARTMENTS = [
    ASC,
    PCO,
    CFIA,
    CFIA,  # row 5: identical duplicate, collapsed
    RCMP_MEMBERS,
    ("Canadian Armed Forces ", "Forces armées canadiennes ", "CAF", "FAC"),
]


@pytest.fixture
def planted(tmp_path: Path) -> Path:
    return build_workbook(
        tmp_path / "planted.xlsx",
        departments=PLANTED_DEPARTMENTS,
        fps=PLANTED_FPS,
        rcmp=PLANTED_RCMP,
        caf=PLANTED_CAF,
    )


def count(connection: Connection, model: type[object]) -> int:
    return connection.scalar(select(func.count()).select_from(model)) or 0


def test_full_import_counts(connection: Connection, planted: Path):
    report = run_import(planted, connection)

    assert report.outcome is Outcome.IMPORTED
    assert report.reconciles
    by_sheet = {s.sheet: s for s in report.sheets}
    fps = by_sheet[FPS.name]
    assert (fps.read, fps.accepted, fps.rejected) == (11, 3, 8)
    assert fps.rejected_by_reason() == {
        "BLANK_TENURE": 1,
        "DUPLICATE_KEY": 2,
        "INVALID_DATE": 1,
        "NEGATIVE_MEASURE": 1,
        "NULL_MEASURE": 1,
        "UNKNOWN_DEPARTMENT": 1,
        "UNKNOWN_TENURE": 1,
    }
    assert fps.warnings_by_code() == {"FTE_EXCEEDS_HEADCOUNT": 1}
    assert [r.row_number for r in fps.rejections] == list(range(5, 13))
    assert by_sheet[RCMP.name].warnings_by_code() == {"SUSPECT_DATE": 1}
    assert by_sheet[CAF.name].accepted == 1
    departments = by_sheet["Departments"]
    assert (departments.read, departments.accepted, departments.collapsed) == (
        6,
        5,
        1,
    )

    assert count(connection, WorkforceMonthly) == 3 + 3 + 1
    assert count(connection, ImportRejection) == 8
    assert count(connection, ImportWarning) == 3  # FTE, SUSPECT_DATE, dup dept
    assert count(connection, Department) == 5


def test_rows_keep_provenance(connection: Connection, planted: Path):
    report = run_import(planted, connection)

    row = connection.execute(
        select(WorkforceMonthly).where(
            WorkforceMonthly.source_sheet == FPS.name, WorkforceMonthly.source_row == 3
        )
    ).one()
    assert (row.import_batch_id, row.source_sheet, row.tenure) == (
        report.batch_id,
        FPS.name,
        "term",
    )


def test_rejection_stores_raw_values(connection: Connection, planted: Path):
    run_import(planted, connection)

    raw = connection.scalar(
        select(ImportRejection.raw).where(ImportRejection.reason_code == "BLANK_TENURE")
    )
    assert raw == {
        "date": 202110,
        "tenure": None,
        "department": PCO_NAME,
        "headcount": 3,
        "fte": 3,
    }


def test_alias_resolves_privy_council_officee(connection: Connection, planted: Path):
    run_import(planted, connection)

    pco_id = connection.scalar(
        select(Department.id).where(Department.long_name_en == PCO_NAME)
    )
    assert (
        connection.scalar(
            select(WorkforceMonthly.department_id).where(
                WorkforceMonthly.source_sheet == FPS.name,
                WorkforceMonthly.source_row == 4,
            )
        )
        == pco_id
    )
    assert connection.execute(
        select(DepartmentAlias.alias_normalized, DepartmentAlias.department_id)
    ).all() == [("Privy Council Officee", pco_id)]


def test_departments_stored_canonical_with_ids_in_sheet_order(
    connection: Connection, planted: Path
):
    run_import(planted, connection)

    rows = connection.execute(
        select(
            Department.id, Department.long_name_en, Department.long_name_fr
        ).order_by(Department.id)
    ).all()
    assert [tuple(r) for r in rows] == [
        (1, ASC_NAME, ASC[1]),
        (2, PCO_NAME, "Bureau du Conseil privé"),
        (3, "Canadian Food Inspection Agency", CFIA[1]),
        (4, RCMP_NAME, RCMP_MEMBERS[1]),
        (5, "Canadian Armed Forces", "Forces armées canadiennes"),
    ]


def test_second_import_of_same_file_is_a_noop(connection: Connection, planted: Path):
    first = run_import(planted, connection)
    second = run_import(planted, connection)

    assert second.outcome is Outcome.SKIPPED
    assert second.batch_id == first.batch_id
    assert count(connection, ImportBatch) == 1
    assert count(connection, WorkforceMonthly) == 7


def test_forced_reimport_of_same_file_changes_nothing(
    connection: Connection, planted: Path
):
    # D16: identical rows stay as they are, so --force adds a batch but no
    # versions, and every row keeps the batch that introduced it.
    first = run_import(planted, connection)
    forced = run_import(planted, connection, force=True)

    assert forced.outcome is Outcome.IMPORTED
    assert count(connection, ImportBatch) == 2
    assert count(connection, WorkforceMonthly) == 7
    assert set(connection.scalars(select(WorkforceMonthly.import_batch_id))) == {
        first.batch_id
    }
    fps = sheet(forced, FPS.name)
    assert fps.versions is not None
    assert (fps.versions.unchanged, fps.versions.added, fps.versions.closed) == (
        3,
        0,
        0,
    )
    assert fps.changes == []


def sheet(report: ImportReport, name: str) -> SheetReport:
    return next(s for s in report.sheets if s.sheet == name)


def versions(connection: Connection, period: date) -> list[tuple[object, ...]]:
    """ASC Indeterminate versions for ``period``, oldest first."""
    rows = connection.execute(
        select(
            WorkforceMonthly.fte,
            WorkforceMonthly.valid_to_batch_id,
            WorkforceMonthly.closed_reason,
        )
        .where(
            WorkforceMonthly.department_id == 1,
            WorkforceMonthly.period == period,
            WorkforceMonthly.tenure == "indeterminate",
        )
        .order_by(WorkforceMonthly.id)
    ).all()
    return [tuple(row) for row in rows]


ASC_OCT = (202110, "Indeterminate", ASC_NAME, 10, 9.5)


def test_row_absent_from_new_file_is_closed_not_deleted(
    connection: Connection, tmp_path: Path
):
    run_import(
        build_workbook(tmp_path / "v1.xlsx", fps=PLANTED_FPS[:3], caf=PLANTED_CAF),
        connection,
    )
    v2 = run_import(
        build_workbook(tmp_path / "v2.xlsx", fps=PLANTED_FPS[1:3], caf=PLANTED_CAF),
        connection,
    )

    assert versions(connection, date(2021, 10, 1)) == [
        (9.5, v2.batch_id, ClosedReason.ABSENT)
    ]
    current = connection.scalar(
        select(func.count())
        .select_from(workforce_current)
        .where(workforce_current.c.source == "fps")
    )
    assert (count(connection, WorkforceMonthly), current) == (4, 2)
    fps = sheet(v2, FPS.name)
    assert fps.versions is not None
    assert (fps.versions.current_before, fps.versions.current_after) == (3, 2)
    assert [c.describe() for c in fps.changes] == [
        f"{ASC_NAME}, 2021-10, indeterminate: closed (absent), "
        "was headcount 10, fte 9.5"
    ]


def test_revised_value_closes_old_version_and_adds_new_one(
    connection: Connection, tmp_path: Path
):
    run_import(build_workbook(tmp_path / "v1.xlsx", fps=[ASC_OCT]), connection)
    revised = (202110, "Indeterminate", ASC_NAME, 10, 9.75)
    v2 = run_import(build_workbook(tmp_path / "v2.xlsx", fps=[revised]), connection)

    assert versions(connection, date(2021, 10, 1)) == [
        (9.5, v2.batch_id, ClosedReason.REVISED),
        (9.75, None, None),
    ]
    assert [c.describe() for c in sheet(v2, FPS.name).changes] == [
        f"{ASC_NAME}, 2021-10, indeterminate: revised headcount 10, fte 9.5 -> "
        "headcount 10, fte 9.75 (row 2)"
    ]


def test_row_quarantined_in_new_file_is_closed_as_rejected(
    connection: Connection, tmp_path: Path
):
    run_import(build_workbook(tmp_path / "v1.xlsx", fps=[ASC_OCT]), connection)
    now_null = (202110, "Indeterminate", ASC_NAME, None, 9.5)
    v2 = run_import(build_workbook(tmp_path / "v2.xlsx", fps=[now_null]), connection)

    assert versions(connection, date(2021, 10, 1)) == [
        (9.5, v2.batch_id, ClosedReason.REJECTED)
    ]
    (change,) = sheet(v2, FPS.name).changes
    assert (change.reason, change.row_number) == (ClosedReason.REJECTED, 2)


def test_row_that_reappears_gets_a_new_version(connection: Connection, tmp_path: Path):
    other = (202110, "Term", ASC_NAME, 2, 2.0)
    run_import(build_workbook(tmp_path / "v1.xlsx", fps=[ASC_OCT, other]), connection)
    v2 = run_import(build_workbook(tmp_path / "v2.xlsx", fps=[other]), connection)
    run_import(build_workbook(tmp_path / "v3.xlsx", fps=[ASC_OCT, other]), connection)

    assert versions(connection, date(2021, 10, 1)) == [
        (9.5, v2.batch_id, ClosedReason.ABSENT),
        (9.5, None, None),
    ]


def test_older_file_imported_again_is_applied_not_skipped(
    connection: Connection, tmp_path: Path
):
    # Only a file identical to the latest import is a no-op (D14). Going back
    # to an earlier file restores its data.
    v1 = build_workbook(tmp_path / "v1.xlsx", fps=[ASC_OCT])
    run_import(v1, connection)
    run_import(build_workbook(tmp_path / "v2.xlsx", fps=[]), connection)

    again = run_import(v1, connection)

    assert again.outcome is Outcome.IMPORTED
    assert sheet(again, FPS.name).versions == VersionCounts(
        current_before=0,
        current_after=1,
        unchanged=0,
        added=1,
        revised=0,
        closed=0,
    )


def test_department_ids_are_stable_across_imports(
    connection: Connection, tmp_path: Path
):
    run_import(build_workbook(tmp_path / "v1.xlsx"), connection)
    new = ("Law Commission of Canada", "Commission du droit du Canada", None, None)
    renamed_pco = (f"  {PCO_NAME} ", "Bureau du Conseil privé (BCP)", "PCO", "BCP")
    run_import(
        build_workbook(
            tmp_path / "v2.xlsx",
            departments=[new, ASC, renamed_pco, CFIA, RCMP_MEMBERS, CAF_DEPT],
        ),
        connection,
    )

    ids = dict(connection.execute(select(Department.long_name_en, Department.id)).all())
    assert ids[ASC_NAME] == 1
    assert ids[PCO_NAME] == 2
    assert ids["Law Commission of Canada"] == len(DEFAULT_DEPARTMENTS) + 1
    assert (
        connection.scalar(select(Department.long_name_fr).where(Department.id == 2))
        == "Bureau du Conseil privé (BCP)"
    )


def test_department_missing_from_later_sheet_is_kept(
    connection: Connection, tmp_path: Path
):
    # D20: dropping a department from the sheet must not delete it or its ID.
    run_import(build_workbook(tmp_path / "v1.xlsx"), connection)
    without_pco = [d for d in DEFAULT_DEPARTMENTS if d is not PCO]
    run_import(
        build_workbook(tmp_path / "v2.xlsx", departments=without_pco), connection
    )

    ids = dict(connection.execute(select(Department.long_name_en, Department.id)).all())
    assert ids[PCO_NAME] == 2
    assert len(ids) == len(DEFAULT_DEPARTMENTS)


def test_rows_and_aliases_still_resolve_to_a_kept_department(
    connection: Connection, tmp_path: Path
):
    # PCO is the target of the reviewed alias "Privy Council Officee". When a
    # later sheet drops PCO, the alias and rows naming PCO still resolve to it
    # (D20) instead of failing the import with AliasConfigError.
    run_import(build_workbook(tmp_path / "v1.xlsx"), connection)
    without_pco = [d for d in DEFAULT_DEPARTMENTS if d is not PCO]
    report = run_import(
        build_workbook(
            tmp_path / "v2.xlsx",
            departments=without_pco,
            fps=[
                (202110, "Term", "Privy Council Officee", 2, 2),
                (202110, "Casual", PCO_NAME, 1, 1),
            ],
        ),
        connection,
    )

    fps = next(sheet for sheet in report.sheets if sheet.sheet == FPS.name)
    assert (fps.accepted, fps.rejected) == (2, 0)
    assert set(connection.scalars(select(WorkforceMonthly.department_id))) == {2}
    assert connection.execute(
        select(DepartmentAlias.alias_normalized, DepartmentAlias.department_id)
    ).all() == [("Privy Council Officee", 2)]


def test_conflicting_department_duplicate_rolls_back(
    connection: Connection, tmp_path: Path
):
    conflicting = (CFIA[0], "Autre nom", "CFIA", "ACIA")
    path = build_workbook(
        tmp_path / "bad.xlsx",
        departments=[*DEFAULT_DEPARTMENTS, conflicting],
        fps=PLANTED_FPS[:2],
    )

    with pytest.raises(SourceFileError, match="differ"):
        run_import(path, connection)

    assert count(connection, Department) == 0
    assert count(connection, WorkforceMonthly) == 0
    failed = connection.execute(select(ImportBatch.status, ImportBatch.error)).one()
    assert failed.status is BatchStatus.FAILED
    assert "rows 4 and 7" in (failed.error or "")


def test_failure_after_rows_were_written_rolls_back_everything(
    connection: Connection, tmp_path: Path
):
    # CAF is read last, after departments and FPS rows have been inserted.
    path = build_workbook(
        tmp_path / "no-caf.xlsx", fps=PLANTED_FPS[:2], omit_sheets=[CAF.name]
    )

    with pytest.raises(SourceFileError, match="'CAF' not found"):
        run_import(path, connection)

    assert count(connection, Department) == 0
    assert count(connection, WorkforceMonthly) == 0
    assert count(connection, ImportRejection) == 0


def test_failed_import_does_not_block_retry(connection: Connection, tmp_path: Path):
    path = build_workbook(tmp_path / "w.xlsx", omit_sheets=[CAF.name])
    with pytest.raises(SourceFileError):
        run_import(path, connection)

    build_workbook(path)  # fixed file at the same path
    assert run_import(path, connection).outcome is Outcome.IMPORTED


def test_header_drift_fails_the_import(connection: Connection, tmp_path: Path):
    path = build_workbook(
        tmp_path / "drift.xlsx",
        headers={FPS.name: ("date", "tenure", "department", "headcount", "FTE")},
    )

    with pytest.raises(SourceFileError, match="expected columns"):
        run_import(path, connection)
    assert count(connection, Department) == 0


def test_not_an_xlsx_file_fails(connection: Connection, tmp_path: Path):
    path = tmp_path / "data.xlsx"
    path.write_text("date,tenure\n")

    with pytest.raises(SourceFileError, match="not a readable"):
        run_import(path, connection)


def test_missing_file_fails_before_touching_the_database(
    connection: Connection, tmp_path: Path
):
    with pytest.raises(SourceFileError, match="cannot read"):
        run_import(tmp_path / "absent.xlsx", connection)
    assert count(connection, ImportBatch) == 0


@pytest.fixture
def cli_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv(
        "IMPORT_DATABASE_URL", "postgresql+psycopg://unused@localhost/unused"
    )
    get_import_settings.cache_clear()
    yield
    get_import_settings.cache_clear()


@pytest.mark.usefixtures("cli_env")
def test_cli_reports_failure_with_exit_code_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    assert main([str(tmp_path / "absent.xlsx")]) == 1
    assert "Import failed, nothing was changed" in capsys.readouterr().err


def test_cli_rejects_missing_argument(capsys: pytest.CaptureFixture[str]):
    with pytest.raises(SystemExit) as exit_info:
        main([])
    assert exit_info.value.code == 2
    assert "usage: pbo-import" in capsys.readouterr().err


def test_report_renders_text_and_json(connection: Connection, planted: Path):
    report = run_import(planted, connection)

    text = report.to_text()
    assert "[Federal Public Service]\n  read 11, accepted 3, rejected 8 (ok)" in text
    assert "  rejected DUPLICATE_KEY: 2" in text
    assert "    row 5: BLANK_TENURE - tenure is blank" in text
    assert "[Departments]\n  read 6, accepted 5, rejected 0, collapsed 1 (ok)" in text
    assert "Reconciliation (read = accepted + rejected + collapsed): OK" in text
    assert text.endswith(
        "Versions (current before + added - closed = current after): OK"
    )

    data = report.to_json()
    fps = data["sheets"][1]
    assert (data["outcome"], data["reconciles"], fps["sheet"]) == (
        "imported",
        True,
        FPS.name,
    )
    assert fps["rejections"][0] == {
        "row": 5,
        "reason": "BLANK_TENURE",
        "detail": "tenure is blank",
        "raw": {
            "date": 202110,
            "tenure": None,
            "department": PCO_NAME,
            "headcount": 3,
            "fte": 3,
        },
    }


def test_skipped_report_explains_how_to_force(connection: Connection, planted: Path):
    run_import(planted, connection)
    text = run_import(planted, connection).to_text()
    assert "was already imported as batch" in text
    assert "--force" in text
