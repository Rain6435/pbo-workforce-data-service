"""Department queries."""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from pbo_workforce.db.tables import Department


def list_departments(session: Session) -> Sequence[Department]:
    """All departments, ordered by ID (D15) so output is deterministic."""
    return session.scalars(select(Department).order_by(Department.id)).all()


def get_department(session: Session, department_id: int) -> Department | None:
    """The department with ``department_id``, or ``None``."""
    return session.get(Department, department_id)
