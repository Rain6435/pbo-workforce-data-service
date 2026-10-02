"""Command-line entry point for the importer (``pbo-import``)."""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from pbo_workforce.config import get_import_settings
from pbo_workforce.db.engine import make_engine
from pbo_workforce.ingest.load import KNOWN_FAILURES, run_import


def main(argv: Sequence[str] | None = None) -> int:
    """Run an import and print its report; returns the process exit code.

    Exit codes: 0 imported (or skipped as already imported), 1 import failed
    and nothing was written, 2 invalid arguments (argparse).
    """
    parser = argparse.ArgumentParser(
        prog="pbo-import",
        description="Import the workforce workbook into the database.",
    )
    parser.add_argument("path", type=Path, help="the .xlsx workbook to import")
    parser.add_argument(
        "--force",
        action="store_true",
        help="import even if this exact file was already imported",
    )
    parser.add_argument(
        "--report-json",
        type=Path,
        metavar="PATH",
        help="also write the full report, with every rejection, as JSON",
    )
    args = parser.parse_args(argv)
    path: Path = args.path
    report_json: Path | None = args.report_json

    # The importer's role: read/write on application tables, no DDL.
    engine = make_engine(get_import_settings().import_database_url)
    try:
        report = run_import(path, engine, force=args.force)
    except KNOWN_FAILURES as exception:
        print(f"Import failed, nothing was changed: {exception}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()

    print(report.to_text())
    if report_json is not None:
        report_json.write_text(
            json.dumps(report.to_json(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return 0 if report.reconciles else 1
