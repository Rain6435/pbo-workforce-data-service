"""Declarative specifications of the source sheets.

Everything the importer knows about the workbook's layout lives here, so a
new source sheet is a new ``SheetSpec`` rather than new parsing code, and a
changed layout (renamed, added, or removed column) fails the import instead
of being misread.
"""

from dataclasses import dataclass
from enum import StrEnum

from pbo_workforce.db.tables import Source
from pbo_workforce.domain.period import YearMonth
from pbo_workforce.domain.tenure import FTE_TENURES, Tenure


class Measure(StrEnum):
    """Numeric columns a workforce sheet can carry."""

    HEADCOUNT = "headcount"
    FTE = "fte"


@dataclass(frozen=True)
class AnnualCadence:
    """The sheet held one yearly snapshot, taken in ``month``, before ``until``.

    Rows dated before ``until`` in any other month are accepted but flagged
    ``SUSPECT_DATE`` (D9): RCMP and CAF were annual March snapshots until
    March 2025, yet both start with a 201504 row repeating the next value.
    """

    month: int
    until: YearMonth


@dataclass(frozen=True)
class SheetSpec:
    """Layout and rules for one workforce sheet."""

    name: str
    header: tuple[str, ...]
    source: Source
    required_measures: tuple[Measure, ...]
    allowed_tenures: frozenset[Tenure]
    cadence: AnnualCadence | None = None


FPS = SheetSpec(
    name="Federal Public Service",
    header=("date", "tenure", "department", "headcount", "fte"),
    source=Source.FPS,
    required_measures=(Measure.HEADCOUNT, Measure.FTE),
    allowed_tenures=frozenset(FTE_TENURES),
)

_ANNUAL_MARCH_UNTIL_2025 = AnnualCadence(month=3, until=YearMonth(2025, 3))

RCMP = SheetSpec(
    name="RCMP",
    header=("date", "tenure", "department", "headcount"),
    source=Source.RCMP,
    required_measures=(Measure.HEADCOUNT,),
    allowed_tenures=frozenset({Tenure.COMBINED}),
    cadence=_ANNUAL_MARCH_UNTIL_2025,
)

CAF = SheetSpec(
    name="CAF",
    header=("date", "tenure", "department", "headcount"),
    source=Source.CAF,
    required_measures=(Measure.HEADCOUNT,),
    allowed_tenures=frozenset({Tenure.COMBINED}),
    cadence=_ANNUAL_MARCH_UNTIL_2025,
)

# Imported in this order; the report lists sheets in this order too.
WORKFORCE_SHEETS: tuple[SheetSpec, ...] = (FPS, RCMP, CAF)

DEPARTMENTS_SHEET = "Departments"
DEPARTMENTS_HEADER: tuple[str, ...] = (
    "long_name_en",
    "long_name_fr",
    "short_name_en",
    "short_name_fr",
)
