"""Ingest CLI: import an ERP export directory into VALERI.

Usage (from apps/api):
    python -m valeri_api.ingest /path/to/export-dir
    python -m valeri_api.ingest --kupci k.csv --artikli a.csv --fakture f.csv --stavke s.csv
"""

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy.orm import Session

from valeri_api.db import get_engine
from valeri_api.ingest.pipeline import files_from_directory, run_import


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m valeri_api.ingest",
        description="Import an ERP export (kupci/artikli/fakture/stavke) into VALERI.",
    )
    parser.add_argument(
        "directory",
        type=Path,
        nargs="?",
        default=None,
        help="directory containing kupci/artikli/fakture/stavke (.csv or .xlsx)",
    )
    parser.add_argument("--kupci", type=Path, help="customers file")
    parser.add_argument("--artikli", type=Path, help="articles file")
    parser.add_argument("--fakture", type=Path, help="invoice headers file")
    parser.add_argument("--stavke", type=Path, help="invoice lines file")
    args = parser.parse_args(argv)

    if args.directory is not None:
        files = files_from_directory(args.directory)
    else:
        files = {
            name: path
            for name, path in (
                ("kupci", args.kupci),
                ("artikli", args.artikli),
                ("fakture", args.fakture),
                ("stavke", args.stavke),
            )
            if path is not None
        }

    if len(files) != 4:
        parser.error(
            "expected a directory with kupci/artikli/fakture/stavke files, "
            "or all four --kupci/--artikli/--fakture/--stavke paths"
        )

    engine = get_engine()
    with Session(engine) as session:
        try:
            run = run_import(session, files, source="cli")
            # Capture values before commit (commit expires ORM attributes).
            run_id, stats, quality = run.id, run.stats, run.report or {}
            session.commit()
        except Exception as error:  # noqa: BLE001 - CLI boundary: report and exit non-zero
            session.rollback()
            print(f"Import FAILED (nothing was changed): {error}", file=sys.stderr)
            return 1

    print(f"Import #{run_id} completed.")
    print(f"Stats: {json.dumps(stats, ensure_ascii=False)}")

    issue_counts = {key: len(value) for key, value in quality.items() if value}
    if issue_counts:
        print(f"Quality findings: {json.dumps(issue_counts, ensure_ascii=False)}")
        print(f"Full report: GET /api/ingest/report/{run_id}")
    else:
        print("Quality findings: none.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
