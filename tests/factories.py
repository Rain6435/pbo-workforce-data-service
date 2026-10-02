"""Build small .xlsx workbooks in code, so each import rule is tested alone.

``build_workbook`` writes the four source sheets with the real headers;
tests pass only the rows (and, for drift tests, the headers) they care about.
"""

from collections.abc import Mapping, Sequence
from pathlib import Path

from openpyxl import Workbook

from pbo_workforce.ingest.sources import (
    CAF,
    DEPARTMENTS_HEADER,
    DEPARTMENTS_SHEET,
    FPS,
    RCMP,
)

type Row = Sequence[object]

ASC = (
    "Accessibility Standards Canada",
    "Normes d\u2019accessibilité Canada",
    "ASC",
    "NAC",
)
PCO = ("Privy Council Office", "Bureau du Conseil privé", "PCO", "BCP")
CFIA = (
    "Canadian Food Inspection Agency",
    "Agence canadienne d\u2019inspection des aliments",
    "CFIA",
    "ACIA",
)
RCMP_MEMBERS = (
    "Royal Canadian Mounted Police - Members",
    "Gendarmerie royale du Canada - Membres",
    None,
    None,
)
CAF_DEPT = ("Canadian Armed Forces", "Forces armées canadiennes", "CAF", "FAC")

DEFAULT_DEPARTMENTS: tuple[Row, ...] = (ASC, PCO, CFIA, RCMP_MEMBERS, CAF_DEPT)


def build_workbook(
    path: Path,
    *,
    departments: Sequence[Row] = DEFAULT_DEPARTMENTS,
    fps: Sequence[Row] = (),
    rcmp: Sequence[Row] = (),
    caf: Sequence[Row] = (),
    headers: Mapping[str, Row] | None = None,
    omit_sheets: Sequence[str] = (),
) -> Path:
    """Write a workbook with the four source sheets to ``path``.

    ``headers`` overrides a sheet's header row by sheet name; ``omit_sheets``
    leaves sheets out. Rows are written as given (no header).
    """
    sheets: dict[str, tuple[Row, Sequence[Row]]] = {
        FPS.name: (FPS.header, fps),
        RCMP.name: (RCMP.header, rcmp),
        CAF.name: (CAF.header, caf),
        DEPARTMENTS_SHEET: (DEPARTMENTS_HEADER, departments),
    }
    workbook = Workbook()
    default_sheet = workbook.active
    if default_sheet is not None:
        workbook.remove(default_sheet)
    for name, (header, rows) in sheets.items():
        if name in omit_sheets:
            continue
        worksheet = workbook.create_sheet(name)
        worksheet.append(list((headers or {}).get(name, header)))
        for row in rows:
            worksheet.append(list(row))
    workbook.save(path)
    return path
