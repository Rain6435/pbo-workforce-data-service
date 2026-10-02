"""Import orchestration: one transaction per import (D14).

Order of work inside the transaction:

1. Take an advisory lock so two imports never interleave.
2. Skip if this exact file (SHA-256) was already imported, unless forced.
3. Record the batch, then upsert departments (stable IDs, D5) and aliases.
4. For each workforce sheet: validate every row, quarantine duplicates,
   compare with the stored current versions, close revised or vanished rows
   and insert new versions (D16), and store rejections and warnings.
5. Check reconciliation, finalize the batch, commit.

Any exception rolls back everything; a ``failed`` batch row is then written
in a separate transaction so the attempt is still on record.
"""

import hashlib
import logging
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from itertools import batched
from pathlib import Path

from sqlalchemy import Connection, Engine, delete, func, insert, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from pbo_workforce.db.tables import (
    BatchStatus,
    ClosedReason,
    Department,
    DepartmentAlias,
    ImportBatch,
    ImportRejection,
    ImportWarning,
    Source,
    WorkforceMonthly,
)
from pbo_workforce.domain.period import YearMonth
from pbo_workforce.domain.tenure import Tenure
from pbo_workforce.ingest.aliases import KNOWN_ALIASES
from pbo_workforce.ingest.normalize import (
    AliasConfigError,
    DepartmentResolver,
    normalize_name_key,
)
from pbo_workforce.ingest.reader import (
    SourceFileError,
    SourceWorkbook,
    iter_rows,
    open_workbook,
)
from pbo_workforce.ingest.report import (
    ImportReport,
    Outcome,
    SheetReport,
    VersionChange,
    VersionCounts,
)
from pbo_workforce.ingest.sources import (
    DEPARTMENTS_HEADER,
    DEPARTMENTS_SHEET,
    WORKFORCE_SHEETS,
    SheetSpec,
)
from pbo_workforce.ingest.validate import (
    Accepted,
    DepartmentRecord,
    Rejected,
    RowKey,
    reject_duplicate_keys,
    validate_departments,
    validate_row,
)
from pbo_workforce.ingest.versioning import SnapshotDiff, StoredVersion, diff_snapshot

logger = logging.getLogger(__name__)

# Arbitrary constant identifying the importer's advisory lock.
_IMPORT_LOCK_KEY = 0x50424F  # "PBO"
# Rows per INSERT or UPDATE statement: large enough to be fast, small enough
# to keep statements and memory modest.
_CHUNK_SIZE = 5000

# Natural key as stored: department ID, first day of month, tenure, source.
type _StoredKey = tuple[int, date, Tenure, Source]


class ReconciliationError(Exception):
    """A sheet's counts do not add up; the import is rolled back."""


# Failures whose message is safe and useful to store and show as-is.
KNOWN_FAILURES = (SourceFileError, AliasConfigError, ReconciliationError)


def run_import(
    path: Path, bind: Engine | Connection, *, force: bool = False
) -> ImportReport:
    """Import ``path`` in one transaction and return the report.

    ``bind`` is an engine (normal use) or a connection already in a
    transaction (tests), in which case the import runs in a savepoint.

    Raises:
        SourceFileError: the file is unreadable, a sheet is missing or has
            unexpected columns, or the Departments sheet is inconsistent.
        AliasConfigError: ``KNOWN_ALIASES`` no longer matches the data.
        ReconciliationError: rows were lost or double-counted.
    """
    digest = _sha256(path)
    print(path, digest)
    started_at = datetime.now(UTC)
    try:
        with (
            Session(bind=bind, join_transaction_mode="create_savepoint") as session,
            session.begin(),
        ):
            return _import(session, path, digest, started_at, force=force)
    except Exception as exc:
        _record_failure(bind, path, digest, started_at, exc)
        raise


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as file:
            for block in iter(lambda: file.read(1 << 20), b""):
                digest.update(block)
    except OSError as exc:
        raise SourceFileError(f"cannot read {path}: {exc.strerror}") from exc
    return digest.hexdigest()


def _import(
    session: Session, path: Path, digest: str, started_at: datetime, *, force: bool
) -> ImportReport:
    session.execute(select(func.pg_advisory_xact_lock(_IMPORT_LOCK_KEY)))
    if not force:
        # Skip only if this file is what the database currently holds: the
        # latest successful import. An older file imported again is a real
        # change (it restores its data, D16), so it is applied.
        latest = session.execute(
            select(ImportBatch.id, ImportBatch.file_sha256)
            .where(ImportBatch.status == BatchStatus.SUCCEEDED)
            .order_by(ImportBatch.id.desc())
            .limit(1)
        ).first()
        if latest is not None and latest.file_sha256 == digest:
            return ImportReport(path.name, digest, Outcome.SKIPPED, latest.id)

    batch = ImportBatch(
        file_sha256=digest,
        file_name=path.name,
        started_at=started_at,
        finished_at=started_at,
        status=BatchStatus.SUCCEEDED,
        counts={},
    )
    session.add(batch)
    session.flush()

    with open_workbook(path) as workbook:
        department_report, department_ids = _load_departments(
            session, workbook, batch.id
        )
        resolver = DepartmentResolver(department_ids, KNOWN_ALIASES)
        _replace_aliases(session, resolver.aliases, department_ids)
        sheets = [department_report]
        for spec in WORKFORCE_SHEETS:
            sheets.append(
                _load_sheet(session, workbook, spec, resolver, department_ids, batch.id)
            )

    report = ImportReport(path.name, digest, Outcome.IMPORTED, batch.id, sheets)
    if not report.reconciles:
        mismatched = [s.sheet for s in sheets if not s.reconciles]
        raise ReconciliationError(f"counts do not reconcile for {mismatched}")
    batch.counts = {sheet.sheet: sheet.counts() for sheet in sheets}
    batch.finished_at = datetime.now(UTC)
    return report


def _load_departments(
    session: Session, workbook: SourceWorkbook, batch_id: int
) -> tuple[SheetReport, dict[str, int]]:
    rows = list(iter_rows(workbook, DEPARTMENTS_SHEET, DEPARTMENTS_HEADER))
    records, warnings = validate_departments(rows)
    report = SheetReport(
        DEPARTMENTS_SHEET,
        read=len(rows),
        accepted=len(records),
        collapsed=len(warnings),
        warnings=warnings,
    )
    ids = _upsert_departments(session, records)
    _insert_issues(session, batch_id, report)
    return report, ids


def _upsert_departments(
    session: Session, records: Sequence[DepartmentRecord]
) -> dict[str, int]:
    """Insert new departments and update changed ones; never renumber (D5).

    Existing departments are matched by normalized English name and keep
    their ID. New ones get the next IDs in sheet order, so on a first import
    IDs follow the sheet from 1. Departments missing from a later sheet are
    kept (D20), because workforce rows and published results may refer to
    them.

    Returns the IDs of *all* departments, kept ones included, by canonical
    English name, so rows and reviewed aliases that name a kept department
    still resolve to it instead of failing the import.
    """
    existing = {
        normalize_name_key(d.long_name_en): d
        for d in session.scalars(select(Department))
    }
    next_id = max((d.id for d in existing.values()), default=0) + 1
    ids: dict[str, int] = {}
    for record in records:
        department = existing.get(normalize_name_key(record.long_name_en))
        if department is None:
            department = Department(id=next_id, **_fields(record))
            session.add(department)
            next_id += 1
        elif _fields(department) != _fields(record):
            for name, value in _fields(record).items():
                setattr(department, name, value)
            department.updated_at = datetime.now(UTC)
        ids[record.long_name_en] = department.id
    for kept in existing.values():
        ids.setdefault(kept.long_name_en, kept.id)
    session.flush()
    return ids


def _fields(item: Department | DepartmentRecord) -> dict[str, str | None]:
    return {
        "long_name_en": item.long_name_en,
        "long_name_fr": item.long_name_fr,
        "short_name_en": item.short_name_en,
        "short_name_fr": item.short_name_fr,
    }


def _replace_aliases(
    session: Session, aliases: Mapping[str, str], department_ids: Mapping[str, int]
) -> None:
    """Make ``department_alias`` mirror the reviewed map in ``aliases.py``."""
    session.execute(delete(DepartmentAlias))
    for alias, department in sorted(aliases.items()):
        session.add(
            DepartmentAlias(
                alias_normalized=alias,
                department_id=department_ids[department],
                note="reviewed alias in pbo_workforce/ingest/aliases.py",
            )
        )
    session.flush()


def _load_sheet(
    session: Session,
    workbook: SourceWorkbook,
    spec: SheetSpec,
    resolver: DepartmentResolver,
    department_ids: Mapping[str, int],
    batch_id: int,
) -> SheetReport:
    """Validate a workforce sheet and record what it changes (D16).

    Each file is a full snapshot of its sources, but nothing is deleted or
    overwritten: rows whose values changed, that are no longer in the file,
    or that are now quarantined have their current version closed, and new
    or revised rows get a new version. Re-importing an identical file
    therefore changes nothing.
    """
    report = SheetReport(spec.name)
    accepted: list[Accepted] = []
    for raw in iter_rows(workbook, spec.name, spec.header):
        report.read += 1
        result = validate_row(raw, spec, resolver)
        if isinstance(result, Rejected):
            report.rejections.append(result)
        else:
            accepted.append(result)
    accepted, duplicates = reject_duplicate_keys(accepted)
    report.rejections = sorted(
        report.rejections + duplicates, key=lambda r: r.row_number
    )
    report.accepted = len(accepted)
    report.warnings = [w for row in accepted for w in row.warnings]

    def stored_key(key: RowKey) -> _StoredKey:
        department, period, tenure, source = key
        return (department_ids[department], period.first_day(), tenure, source)

    current = _current_versions(session, spec.source)
    incoming = {stored_key(row.key): row for row in accepted}
    rejected = {stored_key(r.key): r for r in report.rejections if r.key is not None}
    diff = diff_snapshot(
        current,
        {key: (row.headcount, row.fte) for key, row in incoming.items()},
        rejected.keys(),
    )

    # Close first: the partial unique index allows one current version per key.
    _close_versions(session, batch_id, ClosedReason.REVISED, current, diff.revised)
    for reason, keys in diff.closed.items():
        _close_versions(session, batch_id, reason, current, keys)
    _insert_versions(
        session,
        batch_id,
        department_ids,
        [incoming[key] for key in [*diff.revised, *diff.added]],
    )
    _insert_issues(session, batch_id, report)

    report.versions = VersionCounts(
        current_before=len(current),
        current_after=_count_current(session, spec.source),
        unchanged=len(diff.unchanged),
        added=len(diff.added),
        revised=len(diff.revised),
        closed=sum(len(keys) for keys in diff.closed.values()),
    )
    report.changes = _describe_changes(
        diff, current, incoming, rejected, department_ids
    )
    return report


def _current_versions(
    session: Session, source: Source
) -> dict[_StoredKey, StoredVersion]:
    row = WorkforceMonthly
    result = session.execute(
        select(
            row.id,
            row.department_id,
            row.period,
            row.tenure,
            row.source,
            row.headcount,
            row.fte,
        )
        .where(row.source == source, row.valid_to_batch_id.is_(None))
        .order_by(row.department_id, row.period, row.tenure)
    )
    return {
        (r.department_id, r.period, r.tenure, r.source): StoredVersion(
            r.id, (r.headcount, r.fte)
        )
        for r in result
    }


def _close_versions(
    session: Session,
    batch_id: int,
    reason: ClosedReason,
    current: Mapping[_StoredKey, StoredVersion],
    keys: Sequence[_StoredKey],
) -> None:
    for chunk in batched((current[key].id for key in keys), _CHUNK_SIZE):
        session.execute(
            update(WorkforceMonthly)
            .where(WorkforceMonthly.id.in_(chunk))
            .values(valid_to_batch_id=batch_id, closed_reason=reason)
        )


def _insert_versions(
    session: Session,
    batch_id: int,
    department_ids: Mapping[str, int],
    rows: Sequence[Accepted],
) -> None:
    for chunk in batched(rows, _CHUNK_SIZE):
        session.execute(
            insert(WorkforceMonthly),
            [
                {
                    "department_id": department_ids[row.department],
                    "period": row.period.first_day(),
                    "tenure": row.tenure,
                    "source": row.source,
                    "headcount": row.headcount,
                    "fte": row.fte,
                    "import_batch_id": batch_id,
                    "source_sheet": row.sheet,
                    "source_row": row.row_number,
                }
                for row in chunk
            ],
        )


def _count_current(session: Session, source: Source) -> int:
    row = WorkforceMonthly
    count = session.scalar(
        select(func.count()).where(
            row.source == source, row.valid_to_batch_id.is_(None)
        )
    )
    return count or 0


def _describe_changes(
    diff: SnapshotDiff[_StoredKey],
    current: Mapping[_StoredKey, StoredVersion],
    incoming: Mapping[_StoredKey, Accepted],
    rejected: Mapping[_StoredKey, Rejected],
    department_ids: Mapping[str, int],
) -> list[VersionChange]:
    """Revised and closed rows, with names, for the import report."""
    names = {department_id: name for name, department_id in department_ids.items()}

    def change(
        key: _StoredKey, reason: ClosedReason, new: Accepted | None
    ) -> VersionChange:
        department_id, period, tenure, _ = key
        quarantined = rejected.get(key) if reason is ClosedReason.REJECTED else None
        row = new or quarantined
        return VersionChange(
            department=names[department_id],
            period=YearMonth(period.year, period.month),
            tenure=tenure,
            reason=reason,
            old=current[key].measures,
            new=None if new is None else (new.headcount, new.fte),
            row_number=None if row is None else row.row_number,
        )

    changes = [change(key, ClosedReason.REVISED, incoming[key]) for key in diff.revised]
    for reason, keys in diff.closed.items():
        changes.extend(change(key, reason, None) for key in keys)
    return changes


def _insert_issues(session: Session, batch_id: int, report: SheetReport) -> None:
    if report.rejections:
        session.execute(
            insert(ImportRejection),
            [
                {
                    "batch_id": batch_id,
                    "sheet": r.sheet,
                    "source_row": r.row_number,
                    "reason_code": r.reason.value,
                    "detail": r.detail,
                    "raw": dict(r.raw),
                }
                for r in report.rejections
            ],
        )
    if report.warnings:
        session.execute(
            insert(ImportWarning),
            [
                {
                    "batch_id": batch_id,
                    "sheet": w.sheet,
                    "source_row": w.row_number,
                    "reason_code": w.code.value,
                    "detail": w.detail,
                    "raw": dict(w.raw),
                }
                for w in report.warnings
            ],
        )


def _record_failure(
    bind: Engine | Connection,
    path: Path,
    digest: str,
    started_at: datetime,
    exc: Exception,
) -> None:
    """Write a ``failed`` batch in its own transaction; never mask ``exc``."""
    # Unexpected errors can carry SQL or data; store only their type.
    error = str(exc) if isinstance(exc, KNOWN_FAILURES) else type(exc).__name__
    try:
        with (
            Session(bind=bind, join_transaction_mode="create_savepoint") as session,
            session.begin(),
        ):
            session.add(
                ImportBatch(
                    file_sha256=digest,
                    file_name=path.name,
                    started_at=started_at,
                    finished_at=datetime.now(UTC),
                    status=BatchStatus.FAILED,
                    counts={},
                    error=error,
                )
            )
    except SQLAlchemyError:
        logger.exception("could not record the failed import")
