"""Import report: counts, reconciliation, and rendering.

The report is what an analyst reads after an import, so every quarantined
row and warning is listed with its sheet and Excel row number, and each sheet
states that nothing was lost: read = accepted + rejected + collapsed.

For workforce sheets it also lists what the import changed compared with the
stored data (D16), every revised or closed row with its old and new values,
and checks: current rows before + added - closed = current rows after.
"""

from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pbo_workforce.db.tables import ClosedReason
from pbo_workforce.domain.period import YearMonth
from pbo_workforce.domain.tenure import Tenure
from pbo_workforce.ingest.validate import Rejected, RowWarning
from pbo_workforce.ingest.versioning import Measures

# Revised and closed rows listed in the text report per sheet; the JSON
# report always lists all of them.
_TEXT_LIST_LIMIT = 50


class Outcome(StrEnum):
    """What the import run did."""

    IMPORTED = "imported"
    # Identical file already imported successfully; nothing written (D14).
    SKIPPED = "skipped"


@dataclass(frozen=True)
class VersionChange:
    """One row whose current version an import revised or closed (D16)."""

    department: str
    period: YearMonth
    tenure: Tenure
    reason: ClosedReason
    old: Measures
    # New values for a revision; None when the row was closed.
    new: Measures | None
    # Excel row of the new value (revision) or of the quarantined row; None
    # when the row is absent from the file.
    row_number: int | None

    def describe(self) -> str:
        """One line for the text report."""
        where = f"{self.department}, {self.period.year}-{self.period.month:02d}, "
        where += self.tenure.value
        old = _measures(self.old)
        if self.new is not None:
            change = f"revised {old} -> {_measures(self.new)}"
        else:
            change = f"closed ({self.reason.value}), was {old}"
        row = f" (row {self.row_number})" if self.row_number is not None else ""
        return f"{where}: {change}{row}"


@dataclass(frozen=True)
class VersionCounts:
    """How an import changed one source's current rows (D16)."""

    current_before: int
    current_after: int
    unchanged: int
    added: int
    revised: int
    closed: int

    @property
    def reconciles(self) -> bool:
        """Current rows before + added - closed = current rows after."""
        return self.current_before + self.added - self.closed == self.current_after


@dataclass
class SheetReport:
    """Counts and details for one sheet."""

    sheet: str
    read: int = 0
    accepted: int = 0
    # Identical duplicate rows folded into one (Departments only, D10).
    collapsed: int = 0
    rejections: list[Rejected] = field(default_factory=list[Rejected])
    warnings: list[RowWarning] = field(default_factory=list[RowWarning])
    # Workforce sheets only; None for the Departments sheet.
    versions: VersionCounts | None = None
    changes: list[VersionChange] = field(default_factory=list[VersionChange])

    @property
    def rejected(self) -> int:
        """Number of quarantined rows."""
        return len(self.rejections)

    @property
    def rows_reconcile(self) -> bool:
        """Every row read is accounted for exactly once."""
        return self.read == self.accepted + self.rejected + self.collapsed

    @property
    def reconciles(self) -> bool:
        """Rows read and current versions both add up."""
        versions_ok = self.versions is None or self.versions.reconciles
        return self.rows_reconcile and versions_ok

    def rejected_by_reason(self) -> dict[str, int]:
        """Rejection counts per reason code, sorted by code."""
        return dict(sorted(Counter(r.reason.value for r in self.rejections).items()))

    def warnings_by_code(self) -> dict[str, int]:
        """Warning counts per code, sorted by code."""
        return dict(sorted(Counter(w.code.value for w in self.warnings).items()))

    def counts(self) -> dict[str, Any]:
        """Summary stored in ``import_batch.counts``. Any: JSON values."""
        return {
            "read": self.read,
            "accepted": self.accepted,
            "collapsed": self.collapsed,
            "rejected": self.rejected_by_reason(),
            "warnings": self.warnings_by_code(),
            "versions": None if self.versions is None else vars(self.versions),
        }


@dataclass
class ImportReport:
    """Result of one ``run_import`` call."""

    file_name: str
    file_sha256: str
    outcome: Outcome
    batch_id: int
    sheets: list[SheetReport] = field(default_factory=list[SheetReport])

    @property
    def reconciles(self) -> bool:
        """All sheets reconcile."""
        return all(sheet.reconciles for sheet in self.sheets)

    def to_json(self) -> dict[str, Any]:
        """Machine-readable form, including every rejection and warning.

        Any: JSON values.
        """
        return {
            "file_name": self.file_name,
            "file_sha256": self.file_sha256,
            "outcome": self.outcome.value,
            "batch_id": self.batch_id,
            "reconciles": self.reconciles,
            "sheets": [
                {
                    "sheet": sheet.sheet,
                    **sheet.counts(),
                    "reconciles": sheet.reconciles,
                    "rejections": [
                        {
                            "row": r.row_number,
                            "reason": r.reason.value,
                            "detail": r.detail,
                            "raw": dict(r.raw),
                        }
                        for r in sheet.rejections
                    ],
                    "warnings_detail": [
                        {
                            "row": w.row_number,
                            "code": w.code.value,
                            "detail": w.detail,
                            "raw": dict(w.raw),
                        }
                        for w in sheet.warnings
                    ],
                    "changes": [
                        {
                            "department": c.department,
                            "period": f"{c.period.year}-{c.period.month:02d}",
                            "tenure": c.tenure.value,
                            "reason": c.reason.value,
                            "old": {"headcount": c.old[0], "fte": c.old[1]},
                            "new": None
                            if c.new is None
                            else {"headcount": c.new[0], "fte": c.new[1]},
                            "row": c.row_number,
                        }
                        for c in sheet.changes
                    ],
                }
                for sheet in self.sheets
            ],
        }

    def to_text(self) -> str:
        """Human-readable summary for the terminal."""
        if self.outcome is Outcome.SKIPPED:
            return (
                f"{self.file_name} (sha256 {self.file_sha256[:12]}...) was already "
                f"imported as batch {self.batch_id}; nothing to do. "
                "Use --force to import it again."
            )
        lines = [
            f"Imported {self.file_name} as batch {self.batch_id} "
            f"(sha256 {self.file_sha256[:12]}...)",
            "",
        ]
        for sheet in self.sheets:
            lines.extend(_sheet_lines(sheet))
            lines.append("")
        rows_ok = all(sheet.rows_reconcile for sheet in self.sheets)
        versions_ok = all(
            sheet.versions.reconciles for sheet in self.sheets if sheet.versions
        )
        lines.append(
            "Reconciliation (read = accepted + rejected + collapsed): "
            + ("OK" if rows_ok else "FAILED")
        )
        lines.append(
            "Versions (current before + added - closed = current after): "
            + ("OK" if versions_ok else "FAILED")
        )
        return "\n".join(lines)


def _sheet_lines(sheet: SheetReport) -> list[str]:
    status = "ok" if sheet.reconciles else "MISMATCH"
    lines = [
        f"[{sheet.sheet}]",
        f"  read {sheet.read}, accepted {sheet.accepted}, rejected {sheet.rejected}"
        + (f", collapsed {sheet.collapsed}" if sheet.collapsed else "")
        + f" ({status})",
    ]
    for reason, count in sheet.rejected_by_reason().items():
        lines.append(f"  rejected {reason}: {count}")
    for code, count in sheet.warnings_by_code().items():
        lines.append(f"  warning  {code}: {count}")
    for r in sheet.rejections:
        lines.append(f"    row {r.row_number}: {r.reason} - {r.detail}")
    for w in sheet.warnings:
        lines.append(f"    row {w.row_number}: {w.code} - {w.detail}")
    if sheet.versions is not None:
        v = sheet.versions
        lines.append(
            f"  versions: unchanged {v.unchanged}, added {v.added}, revised "
            f"{v.revised}, closed {v.closed} (current rows {v.current_before} -> "
            f"{v.current_after})"
        )
        for change in sheet.changes[:_TEXT_LIST_LIMIT]:
            lines.append(f"    {change.describe()}")
        hidden = len(sheet.changes) - _TEXT_LIST_LIMIT
        if hidden > 0:
            lines.append(f"    ... {hidden} more (see --report-json)")
    return lines


def _measures(measures: Measures) -> str:
    headcount, fte = measures
    return f"headcount {headcount}" + ("" if fte is None else f", fte {fte:g}")
