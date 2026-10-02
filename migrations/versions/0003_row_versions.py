"""Row versions: imports close rows instead of deleting them (D16).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-01

* ``workforce_monthly`` gains ``valid_to_batch_id`` and ``closed_reason``. A row
  is current while both are NULL; an import that revises a row, no longer
  contains it, or quarantines it closes it.
* The natural-key unique constraint and the FTE index become partial indexes
  over current rows only, so history can hold several versions per key and the
  FTE query does not slow down as history grows.
* The view ``workforce_current`` exposes current rows. ``pbo_api`` may read the
  view and no longer the table, so the API cannot serve history by mistake.

Downgrading deletes closed versions: the original unique constraint cannot
hold more than one row per key.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CLOSED_REASON = postgresql.ENUM(
    "revised", "absent", "rejected", name="closed_reason", create_type=False
)
_CURRENT = "valid_to_batch_id IS NULL"
_KEY = ["department_id", "period", "tenure", "source"]


def upgrade() -> None:
    """Add version columns, partial indexes, and the current-rows view."""
    _CLOSED_REASON.create(op.get_bind())
    op.add_column(
        "workforce_monthly",
        sa.Column(
            "valid_to_batch_id",
            sa.Integer(),
            sa.ForeignKey(
                "import_batch.id",
                name="fk_workforce_monthly_valid_to_batch_id_import_batch",
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "workforce_monthly",
        sa.Column[str]("closed_reason", _CLOSED_REASON, nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_workforce_monthly_closed_consistent"),
        "workforce_monthly",
        "(valid_to_batch_id IS NULL) = (closed_reason IS NULL)",
    )

    op.drop_constraint(
        "uq_workforce_monthly_department_id_period_tenure_source",
        "workforce_monthly",
        type_="unique",
    )
    op.create_index(
        "uq_workforce_monthly_current_key",
        "workforce_monthly",
        _KEY,
        unique=True,
        postgresql_where=sa.text(_CURRENT),
    )
    op.drop_index(
        "ix_workforce_monthly_department_id_source_period", "workforce_monthly"
    )
    op.create_index(
        "ix_workforce_monthly_current_department_id_source_period",
        "workforce_monthly",
        ["department_id", "source", "period"],
        postgresql_where=sa.text(_CURRENT),
    )

    op.execute(
        "CREATE VIEW workforce_current AS"
        " SELECT id, department_id, period, tenure, source, headcount, fte,"
        " import_batch_id, source_sheet, source_row"
        " FROM workforce_monthly WHERE valid_to_batch_id IS NULL"
    )
    # The view runs with its owner's privileges, so pbo_api needs no access
    # to the table itself.
    op.execute("REVOKE SELECT ON workforce_monthly FROM pbo_api")
    op.execute("GRANT SELECT ON workforce_current TO pbo_api")


def downgrade() -> None:
    """Restore 0002's schema; closed versions are deleted."""
    op.execute("REVOKE SELECT ON workforce_current FROM pbo_api")
    op.execute("GRANT SELECT ON workforce_monthly TO pbo_api")
    op.execute("DROP VIEW workforce_current")

    op.execute("DELETE FROM workforce_monthly WHERE valid_to_batch_id IS NOT NULL")
    op.drop_index(
        "ix_workforce_monthly_current_department_id_source_period",
        "workforce_monthly",
    )
    op.create_index(
        "ix_workforce_monthly_department_id_source_period",
        "workforce_monthly",
        ["department_id", "source", "period"],
    )
    op.drop_index("uq_workforce_monthly_current_key", "workforce_monthly")
    op.create_unique_constraint(
        "uq_workforce_monthly_department_id_period_tenure_source",
        "workforce_monthly",
        _KEY,
    )
    op.drop_constraint(
        op.f("ck_workforce_monthly_closed_consistent"), "workforce_monthly"
    )
    op.drop_column("workforce_monthly", "closed_reason")
    op.drop_column("workforce_monthly", "valid_to_batch_id")
    _CLOSED_REASON.drop(op.get_bind())
