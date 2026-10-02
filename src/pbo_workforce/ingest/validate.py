"""Row validation rules, rejection reasons, and warning codes (D7-D10).

Everything here is pure: rows in, decisions out. The loader decides what to
write; these functions decide what is trustworthy.
"""

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from pbo_workforce.db.tables import Source
from pbo_workforce.domain.period import YearMonth, parse_yyyymm
from pbo_workforce.domain.tenure import Tenure, parse_tenure
from pbo_workforce.ingest.normalize import (
    DepartmentResolver,
    canonical_name,
    normalize_name_key,
)
from pbo_workforce.ingest.reader import CellValue, RawRow, SourceFileError
from pbo_workforce.ingest.sources import Measure, SheetSpec


class RejectReason(StrEnum):
    """Why a row was quarantined. Checked in this order; the first wins."""

    INVALID_DATE = "INVALID_DATE"
    UNKNOWN_DEPARTMENT = "UNKNOWN_DEPARTMENT"
    BLANK_TENURE = "BLANK_TENURE"
    UNKNOWN_TENURE = "UNKNOWN_TENURE"
    NULL_MEASURE = "NULL_MEASURE"
    # Not a finite number, or a fractional headcount.
    INVALID_MEASURE = "INVALID_MEASURE"
    NEGATIVE_MEASURE = "NEGATIVE_MEASURE"
    # Found after row checks: two or more rows share a key (D10).
    DUPLICATE_KEY = "DUPLICATE_KEY"


class WarningCode(StrEnum):
    """Accepted as-is, but reported for review (D9, D10)."""

    FTE_EXCEEDS_HEADCOUNT = "FTE_EXCEEDS_HEADCOUNT"
    SUSPECT_DATE = "SUSPECT_DATE"
    DUPLICATE_DEPARTMENT_ROW = "DUPLICATE_DEPARTMENT_ROW"


# Natural key of a workforce row: department (canonical English name), month,
# tenure, source. Unique among current rows in ``workforce_monthly``.
type RowKey = tuple[str, YearMonth, Tenure, Source]


@dataclass(frozen=True)
class RowWarning:
    """A warning tied to one source row."""

    sheet: str
    row_number: int
    code: WarningCode
    detail: str
    raw: Mapping[str, CellValue]


@dataclass(frozen=True)
class Accepted:
    """A workforce row that passed every check."""

    sheet: str
    row_number: int
    source: Source
    department: str  # canonical English long name
    period: YearMonth
    tenure: Tenure
    headcount: int
    fte: float | None
    raw: Mapping[str, CellValue]
    warnings: tuple[RowWarning, ...] = ()

    @property
    def key(self) -> RowKey:
        """Natural key; unique in ``workforce_monthly``."""
        return (self.department, self.period, self.tenure, self.source)


@dataclass(frozen=True)
class Rejected:
    """A quarantined row. The whole row is rejected, never part of it (D8)."""

    sheet: str
    row_number: int
    reason: RejectReason
    detail: str
    raw: Mapping[str, CellValue]
    # Natural key, when date, department, and tenure were valid. Lets the
    # loader tell "quarantined now" from "absent" for an existing row (D16).
    key: RowKey | None = None


class _RejectError(Exception):
    def __init__(self, reason: RejectReason, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


def validate_row(
    raw: RawRow, spec: SheetSpec, resolver: DepartmentResolver
) -> Accepted | Rejected:
    """Accept or quarantine one workforce row.

    Checks run in ``RejectReason`` order and the first failure is recorded,
    so the reason code is deterministic. Accepted rows carry any warnings.
    """
    try:
        period = _period(raw.values["date"])
        department = _department(raw.values["department"], resolver)
        tenure = _tenure(raw.values["tenure"], spec)
    except _RejectError as rejection:
        return Rejected(
            raw.sheet, raw.row_number, rejection.reason, rejection.detail, raw.values
        )
    key: RowKey = (department, period, tenure, spec.source)
    try:
        measures = {m: _measure(raw.values[m], m) for m in spec.required_measures}
    except _RejectError as rejection:
        return Rejected(
            raw.sheet,
            raw.row_number,
            rejection.reason,
            rejection.detail,
            raw.values,
            key,
        )

    headcount = int(measures[Measure.HEADCOUNT])
    fte = measures.get(Measure.FTE)
    warnings: list[RowWarning] = []
    if fte is not None and fte > headcount:
        warnings.append(
            _warning(
                raw,
                WarningCode.FTE_EXCEEDS_HEADCOUNT,
                f"fte {fte:g} > headcount {headcount}",
            )
        )
    cadence = spec.cadence
    if cadence and period < cadence.until and period.month != cadence.month:
        warnings.append(
            _warning(
                raw,
                WarningCode.SUSPECT_DATE,
                f"{period.year}{period.month:02d} is off the annual cadence "
                f"(month {cadence.month} before "
                f"{cadence.until.year}{cadence.until.month:02d})",
            )
        )
    return Accepted(
        sheet=raw.sheet,
        row_number=raw.row_number,
        source=spec.source,
        department=department,
        period=period,
        tenure=tenure,
        headcount=headcount,
        fte=fte,
        raw=raw.values,
        warnings=tuple(warnings),
    )


def _warning(raw: RawRow, code: WarningCode, detail: str) -> RowWarning:
    return RowWarning(raw.sheet, raw.row_number, code, detail, raw.values)


def _period(value: CellValue) -> YearMonth:
    try:
        return parse_yyyymm(value)
    except ValueError as exc:
        raise _RejectError(RejectReason.INVALID_DATE, str(exc)) from exc


def _department(value: CellValue, resolver: DepartmentResolver) -> str:
    name = resolver.resolve(value) if isinstance(value, str) else None
    if name is None:
        raise _RejectError(
            RejectReason.UNKNOWN_DEPARTMENT, f"unknown department {value!r}"
        )
    return name


def _tenure(value: CellValue, spec: SheetSpec) -> Tenure:
    if value is None:
        raise _RejectError(RejectReason.BLANK_TENURE, "tenure is blank")
    tenure = parse_tenure(value) if isinstance(value, str) else None
    if tenure is None or tenure not in spec.allowed_tenures:
        raise _RejectError(
            RejectReason.UNKNOWN_TENURE, f"tenure {value!r} not allowed in {spec.name}"
        )
    return tenure


def _measure(value: CellValue, measure: Measure) -> float:
    if value is None:
        raise _RejectError(RejectReason.NULL_MEASURE, f"{measure} is null")
    if isinstance(value, str) or not math.isfinite(value):
        raise _RejectError(
            RejectReason.INVALID_MEASURE, f"{measure} {value!r} not a number"
        )
    if measure is Measure.HEADCOUNT and not float(value).is_integer():
        raise _RejectError(
            RejectReason.INVALID_MEASURE, f"headcount {value!r} is not whole"
        )
    if value < 0:
        raise _RejectError(RejectReason.NEGATIVE_MEASURE, f"{measure} {value!r} < 0")
    return float(value)


def reject_duplicate_keys(
    rows: Sequence[Accepted],
) -> tuple[list[Accepted], list[Rejected]]:
    """Quarantine every row whose key occurs more than once (D10).

    All copies are rejected, not all-but-one: with conflicting values there
    is no basis for choosing, and silently picking one would hide the issue.
    """
    by_key: defaultdict[RowKey, list[Accepted]] = defaultdict(list)
    for row in rows:
        by_key[row.key].append(row)
    kept: list[Accepted] = []
    rejected: list[Rejected] = []
    for row in rows:
        group = by_key[row.key]
        if len(group) == 1:
            kept.append(row)
            continue
        others = ", ".join(str(r.row_number) for r in group if r is not row)
        rejected.append(
            Rejected(
                row.sheet,
                row.row_number,
                RejectReason.DUPLICATE_KEY,
                f"same department, month, tenure as row(s) {others}",
                row.raw,
                row.key,
            )
        )
    return kept, rejected


@dataclass(frozen=True)
class DepartmentRecord:
    """A department as it will be stored, in Departments-sheet order."""

    long_name_en: str
    long_name_fr: str
    short_name_en: str | None
    short_name_fr: str | None


def validate_departments(
    rows: Iterable[RawRow],
) -> tuple[list[DepartmentRecord], list[RowWarning]]:
    """Canonicalize the Departments sheet and collapse identical duplicates.

    Departments are reference data every other row depends on, so problems
    here fail the whole import rather than quarantining a row.

    Raises:
        SourceFileError: a long name is blank, or two rows share an English
            name (after normalization) but differ in any other field.
    """
    records: dict[str, tuple[int, DepartmentRecord]] = {}
    warnings: list[RowWarning] = []
    for raw in rows:
        record = _department_record(raw)
        key = normalize_name_key(record.long_name_en)
        first = records.get(key)
        if first is None:
            records[key] = (raw.row_number, record)
        elif first[1] == record:
            warnings.append(
                _warning(
                    raw,
                    WarningCode.DUPLICATE_DEPARTMENT_ROW,
                    f"identical to row {first[0]}; collapsed",
                )
            )
        else:
            raise SourceFileError(
                f"Departments rows {first[0]} and {raw.row_number} share the name "
                f"{record.long_name_en!r} but differ; fix the source file"
            )
    return [record for _, record in records.values()], warnings


def _department_record(raw: RawRow) -> DepartmentRecord:
    return DepartmentRecord(
        long_name_en=_required_text(raw, "long_name_en"),
        long_name_fr=_required_text(raw, "long_name_fr"),
        short_name_en=_optional_text(raw, "short_name_en"),
        short_name_fr=_optional_text(raw, "short_name_fr"),
    )


def _required_text(raw: RawRow, column: str) -> str:
    text = _optional_text(raw, column)
    if text is None:
        raise SourceFileError(f"Departments row {raw.row_number}: {column} is blank")
    return text


def _optional_text(raw: RawRow, column: str) -> str | None:
    value = raw.values[column]
    return None if value is None else canonical_name(str(value))
