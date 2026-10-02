"""SQLAlchemy table models.

The schema itself is owned by the Alembic migrations in ``migrations/``;
these models mirror it for typed queries, and
``tests/integration/test_migrations.py`` checks that the two agree.
"""

from datetime import date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Double,
    Enum,
    ForeignKey,
    Identity,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from pbo_workforce.domain.tenure import Tenure


class Source(StrEnum):
    """Which source sheet a workforce row came from (provenance)."""

    FPS = "fps"
    RCMP = "rcmp"
    CAF = "caf"


class BatchStatus(StrEnum):
    """Outcome of an import run."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ClosedReason(StrEnum):
    """Why a version of a workforce row stopped being current (D16)."""

    # The new file has the same key with a different headcount or FTE.
    REVISED = "revised"
    # The new file has no row for this key.
    ABSENT = "absent"
    # The new file has a row for this key, but it was quarantined.
    REJECTED = "rejected"


def _enum_values(enum_cls: type[StrEnum]) -> list[str]:
    return [member.value for member in enum_cls]


def _pg_enum(enum_cls: type[StrEnum], name: str) -> Enum:
    # Store the lower-case values, not the Python member names.
    return Enum(enum_cls, name=name, values_callable=_enum_values)


class Base(DeclarativeBase):
    """Declarative base with deterministic constraint names."""

    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(table_name)s_%(column_0_N_name)s",
            "uq": "uq_%(table_name)s_%(column_0_N_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


class Department(Base):
    """A department, with IDs assigned in Departments-sheet order (D5)."""

    __tablename__ = "department"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    long_name_en: Mapped[str] = mapped_column(Text, unique=True)
    long_name_fr: Mapped[str] = mapped_column(Text)
    short_name_en: Mapped[str | None] = mapped_column(Text)
    short_name_fr: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class DepartmentAlias(Base):
    """A reviewed misspelling of a department name (D6)."""

    __tablename__ = "department_alias"

    alias_normalized: Mapped[str] = mapped_column(Text, primary_key=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("department.id"))
    note: Mapped[str] = mapped_column(Text)


class ImportBatch(Base):
    """One run of the importer (D14)."""

    __tablename__ = "import_batch"

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    file_sha256: Mapped[str] = mapped_column(String(64), index=True)
    file_name: Mapped[str] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[BatchStatus] = mapped_column(_pg_enum(BatchStatus, "batch_status"))
    # Per-sheet read/accepted/rejected/warning counts, as in the import report.
    # Any: arbitrary JSON document.
    counts: Mapped[dict[str, Any]] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)


class WorkforceMonthly(Base):
    """One version of a source row: monthly headcount and FTE (D1, D16).

    Imports never delete or overwrite rows. A row is *current* while
    ``valid_to_batch_id`` is NULL; a later import that revises it, no longer
    contains it, or quarantines it closes it instead. Read current rows
    through ``workforce_current``.
    """

    __tablename__ = "workforce_monthly"
    __table_args__ = (
        # At most one current version per natural key; history may hold more.
        Index(
            "uq_workforce_monthly_current_key",
            "department_id",
            "period",
            "tenure",
            "source",
            unique=True,
            postgresql_where="valid_to_batch_id IS NULL",
        ),
        # Serves the FTE query, which only reads current versions.
        Index(
            "ix_workforce_monthly_current_department_id_source_period",
            "department_id",
            "source",
            "period",
            postgresql_where="valid_to_batch_id IS NULL",
        ),
        CheckConstraint("headcount >= 0", name="headcount_non_negative"),
        CheckConstraint("fte >= 0", name="fte_non_negative"),
        CheckConstraint("extract(day from period) = 1", name="period_first_of_month"),
        # FPS rows carry FTE by tenure; RCMP/CAF rows are headcount-only (D11).
        CheckConstraint(
            "(source = 'fps' AND fte IS NOT NULL AND tenure <> 'combined')"
            " OR (source <> 'fps' AND fte IS NULL AND tenure = 'combined')",
            name="source_shape",
        ),
        CheckConstraint(
            "(valid_to_batch_id IS NULL) = (closed_reason IS NULL)",
            name="closed_consistent",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("department.id"))
    period: Mapped[date] = mapped_column(Date)
    tenure: Mapped[Tenure] = mapped_column(_pg_enum(Tenure, "tenure"))
    source: Mapped[Source] = mapped_column(_pg_enum(Source, "source"))
    headcount: Mapped[int] = mapped_column(Integer)
    # Double precision keeps the source value exactly; see D4.
    fte: Mapped[float | None] = mapped_column(Double)
    # The batch that introduced this version.
    import_batch_id: Mapped[int] = mapped_column(ForeignKey("import_batch.id"))
    source_sheet: Mapped[str] = mapped_column(Text)
    source_row: Mapped[int] = mapped_column(Integer)
    # The batch that closed this version, and why; both NULL while current.
    valid_to_batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batch.id"))
    closed_reason: Mapped[ClosedReason | None] = mapped_column(
        _pg_enum(ClosedReason, "closed_reason")
    )


class ImportRejection(Base):
    """A quarantined source row (D8)."""

    __tablename__ = "import_rejection"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("import_batch.id"), index=True)
    sheet: Mapped[str] = mapped_column(Text)
    source_row: Mapped[int] = mapped_column(Integer)
    reason_code: Mapped[str] = mapped_column(Text)
    detail: Mapped[str] = mapped_column(Text)
    # Any: the raw cell values, keyed by header.
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB)


class ImportWarning(Base):
    """An accepted row, or sheet-level event, that needs review (D9)."""

    __tablename__ = "import_warning"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("import_batch.id"), index=True)
    sheet: Mapped[str] = mapped_column(Text)
    source_row: Mapped[int] = mapped_column(Integer)
    reason_code: Mapped[str] = mapped_column(Text)
    detail: Mapped[str] = mapped_column(Text)
    # Any: the raw cell values, keyed by header.
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB)


# The ``workforce_current`` view (migration 0003): current versions only. The
# API role can read this view but not the table, so the API cannot serve
# history by mistake. Kept out of ``Base.metadata`` because it is not a table
# Alembic should manage.
workforce_current = Table(
    "workforce_current",
    MetaData(),
    Column("id", BigInteger, primary_key=True),
    Column("department_id", Integer),
    Column("period", Date),
    Column[Tenure]("tenure", _pg_enum(Tenure, "tenure")),
    Column[Source]("source", _pg_enum(Source, "source")),
    Column("headcount", Integer),
    Column("fte", Double[float]()),
)
