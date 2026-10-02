"""Workforce queries, including quarterly FTE aggregation (D3).

FTE values are ``float`` throughout: they are stored as double precision
(D4) and PostgreSQL's ``avg`` over double precision returns double precision.
Rounding for display happens in the API layer.

Queries read the ``workforce_current`` view, so only current versions of rows
are used (D16); history stays in the table, which the API role cannot read.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import Integer, cast, extract, func, select
from sqlalchemy.orm import Session

from pbo_workforce.db.tables import Source, workforce_current
from pbo_workforce.domain.period import (
    QuarterBasis,
    quarter_offset_months,
    year_bounds,
)
from pbo_workforce.domain.tenure import FTE_TENURES, Tenure


@dataclass(frozen=True)
class QuarterFte:
    """Mean monthly FTE per tenure for one quarter."""

    year: int
    quarter: int
    fte: dict[Tenure, float]


def fte_per_quarter(
    session: Session,
    department_id: int,
    basis: QuarterBasis,
    year: int | None = None,
    tenures: Sequence[Tenure] = FTE_TENURES,
) -> list[QuarterFte]:
    """Quarterly FTE for one department, ordered by year and quarter (D15).

    D3, in two steps:

    1. ``monthly``: one row per month in which the department reported any
       accepted Federal Public Service row, with that month's FTE for each
       requested tenure. A tenure with no row that month counts as 0: the
       department reported, and had no employees of that tenure.
    2. Average those monthly values per quarter. Months with no rows at all
       are not in ``monthly``, so they are excluded from the mean, and a
       quarter with no reporting months produces no row.

    The tenure filter only selects columns; it never changes which months
    count as reporting months. RCMP and CAF have no FTE (D11), so only the
    ``fps`` source is read and those departments return an empty list.
    """
    unknown = set(tenures) - set(FTE_TENURES)
    if unknown:
        raise ValueError(f"tenures without FTE: {sorted(unknown)}")
    selected = [t for t in FTE_TENURES if t in set(tenures)]

    row = workforce_current.c
    monthly_filters = [row.department_id == department_id, row.source == Source.FPS]
    if year is not None:
        # A range on the stored month keeps the (department_id, source,
        # period) index usable; year_bounds applies the quarter basis.
        first, last = year_bounds(year, basis)
        monthly_filters.append(row.period.between(first.first_day(), last.first_day()))
    monthly = (
        select(
            row.period,
            *(
                func.coalesce(func.sum(row.fte).filter(row.tenure == t), 0.0).label(t)
                for t in selected
            ),
        )
        .where(*monthly_filters)
        .group_by(row.period)
        .cte("monthly")
    )

    # Shift each month back to the start of the basis year, then take the
    # calendar year and quarter of the shifted date.
    shifted = monthly.c.period - func.make_interval(0, quarter_offset_months(basis))
    quarter_year = cast(extract("year", shifted), Integer).label("year")
    quarter = cast(extract("quarter", shifted), Integer).label("quarter")
    query = (
        select(
            quarter_year,
            quarter,
            *(func.avg(monthly.c[t]).label(t) for t in selected),
        )
        .group_by(quarter_year, quarter)
        .order_by(quarter_year, quarter)
    )

    return [
        QuarterFte(
            year=int(result["year"]),
            quarter=int(result["quarter"]),
            fte={t: float(result[t]) for t in selected},
        )
        for result in session.execute(query).mappings()
    ]
