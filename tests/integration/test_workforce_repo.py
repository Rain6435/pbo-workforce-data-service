"""Quarterly FTE aggregation (D3) on a hand-computed example.

Department 1, Federal Public Service rows (FTE):

    month     indeterminate  term  casual  student
    2021-01        10          4
    2021-02        12                               <- no term row: term = 0
    2021-03   (no rows at all: not a reporting month; a CAF row is ignored)
    2021-04                    3     1.5
    2021-05         9
    2021-06         9                        0.5

Calendar quarters, mean over reporting months:

    2021 Q1 (Jan, Feb):      indeterminate 11, term 2, others 0
    2021 Q2 (Apr, May, Jun): indeterminate 6, term 1, casual 0.5,
                             student 0.5 / 3
"""

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from pbo_workforce.db.tables import (
    BatchStatus,
    ClosedReason,
    Department,
    ImportBatch,
    Source,
    WorkforceMonthly,
)
from pbo_workforce.domain.period import QuarterBasis
from pbo_workforce.domain.tenure import FTE_TENURES, Tenure
from pbo_workforce.repositories.workforce import QuarterFte, fte_per_quarter

IND, TERM, CAS, STU, MIS = (
    Tenure.INDETERMINATE,
    Tenure.TERM,
    Tenure.CASUAL,
    Tenure.STUDENT,
    Tenure.MISSING,
)

FPS_ROWS: list[tuple[date, Tenure, float]] = [
    (date(2021, 1, 1), IND, 10),
    (date(2021, 1, 1), TERM, 4),
    (date(2021, 2, 1), IND, 12),
    (date(2021, 4, 1), TERM, 3),
    (date(2021, 4, 1), CAS, 1.5),
    (date(2021, 5, 1), IND, 9),
    (date(2021, 6, 1), IND, 9),
    (date(2021, 6, 1), STU, 0.5),
]


@pytest.fixture
def seeded(session: Session) -> Session:
    now = datetime.now(UTC)
    batch = ImportBatch(
        file_sha256="0" * 64,
        file_name="test.xlsx",
        started_at=now,
        finished_at=now,
        status=BatchStatus.SUCCEEDED,
        counts={},
    )
    session.add_all(
        [
            batch,
            Department(id=1, long_name_en="Dept One", long_name_fr="Un"),
            Department(id=2, long_name_en="Dept Two", long_name_fr="Deux"),
        ]
    )
    session.flush()

    def row(dept: int, period: date, tenure: Tenure, fte: float | None) -> None:
        source = Source.FPS if fte is not None else Source.CAF
        session.add(
            WorkforceMonthly(
                department_id=dept,
                period=period,
                tenure=tenure,
                source=source,
                headcount=100,
                fte=fte,
                import_batch_id=batch.id,
                source_sheet="test",
                source_row=0,
            )
        )

    for period, tenure, fte in FPS_ROWS:
        row(1, period, tenure, fte)
    # Must not count: another department, and a non-FPS source.
    row(2, date(2021, 3, 1), IND, 999)
    row(2, date(2021, 7, 1), IND, 999)
    row(1, date(2021, 3, 1), Tenure.COMBINED, None)
    session.flush()
    return session


def fte(**values: float) -> dict[Tenure, float]:
    zeros = dict.fromkeys(FTE_TENURES, 0.0)
    return zeros | {Tenure(k): v for k, v in values.items()}


def rounded(quarters: list[QuarterFte]) -> list[QuarterFte]:
    """Compare averages without depending on the last bits of a float."""
    return [
        QuarterFte(q.year, q.quarter, {t: round(v, 12) for t, v in q.fte.items()})
        for q in quarters
    ]


def test_calendar_quarters_hand_computed(seeded: Session):
    result = fte_per_quarter(seeded, 1, QuarterBasis.CALENDAR)

    assert rounded(result) == [
        QuarterFte(2021, 1, fte(indeterminate=11, term=2)),
        QuarterFte(
            2021,
            2,
            fte(indeterminate=6, term=1, casual=0.5, student=round(0.5 / 3, 12)),
        ),
    ]


def test_fiscal_quarters(seeded: Session):
    # Jan-Mar 2021 are the last quarter of fiscal 2020-21 (year 2020).
    result = fte_per_quarter(seeded, 1, QuarterBasis.FISCAL)

    assert [(q.year, q.quarter) for q in result] == [(2020, 4), (2021, 1)]
    assert result[0].fte[IND] == 11


@pytest.mark.parametrize(
    ("basis", "year", "expected"),
    [
        (QuarterBasis.CALENDAR, 2021, [(2021, 1), (2021, 2)]),
        (QuarterBasis.CALENDAR, 2020, []),
        (QuarterBasis.FISCAL, 2020, [(2020, 4)]),
        (QuarterBasis.FISCAL, 2021, [(2021, 1)]),
    ],
)
def test_year_filter_uses_the_quarter_year(
    seeded: Session, basis: QuarterBasis, year: int, expected: list[tuple[int, int]]
):
    result = fte_per_quarter(seeded, 1, basis, year=year)
    assert [(q.year, q.quarter) for q in result] == expected


def test_tenure_filter_selects_columns_without_changing_reporting_months(
    seeded: Session,
):
    result = fte_per_quarter(seeded, 1, QuarterBasis.CALENDAR, tenures=[CAS])

    # Casual is averaged over all three Q2 reporting months, not just April.
    assert result == [
        QuarterFte(2021, 1, {CAS: 0.0}),
        QuarterFte(2021, 2, {CAS: 0.5}),
    ]


def test_tenure_order_follows_api_order(seeded: Session):
    result = fte_per_quarter(seeded, 1, QuarterBasis.CALENDAR, tenures=[MIS, IND])
    assert list(result[0].fte) == [IND, MIS]


def test_department_without_fps_rows_has_no_quarters(seeded: Session):
    seeded.add(Department(id=3, long_name_en="No rows", long_name_fr="Aucune"))
    assert fte_per_quarter(seeded, 3, QuarterBasis.CALENDAR) == []


def test_combined_tenure_is_refused(seeded: Session):
    with pytest.raises(ValueError, match="without FTE"):
        fte_per_quarter(seeded, 1, QuarterBasis.CALENDAR, tenures=[Tenure.COMBINED])


def test_closed_versions_are_ignored(seeded: Session):
    # D16: history stays in workforce_monthly but only current versions count.
    # A closed March row must neither add FTE nor make March a reporting month.
    batch_id = seeded.scalars(select(ImportBatch.id)).one()
    seeded.add(
        WorkforceMonthly(
            department_id=1,
            period=date(2021, 3, 1),
            tenure=IND,
            source=Source.FPS,
            headcount=100,
            fte=999.0,
            import_batch_id=batch_id,
            source_sheet="test",
            source_row=0,
            valid_to_batch_id=batch_id,
            closed_reason=ClosedReason.ABSENT,
        )
    )
    seeded.flush()

    result = fte_per_quarter(seeded, 1, QuarterBasis.CALENDAR, year=2021)

    assert rounded(result)[0] == QuarterFte(2021, 1, fte(indeterminate=11, term=2))
