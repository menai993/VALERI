"""Import pipeline orchestration: read → staging → quality → upsert → finalize.

The whole pipeline runs in the caller's transaction: any failure rolls back
everything (no partial imports, ever). The caller commits on success.
"""

import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from valeri_api.ingest.models import ImportRun
from valeri_api.ingest.quality import build_quality_report
from valeri_api.ingest.readers import read_table
from valeri_api.ingest.staging import create_import_run, load_to_staging
from valeri_api.ingest.upsert import upsert_to_core

REQUIRED_FILES = ("kupci", "artikli", "fakture", "stavke")


def run_import(
    session: Session,
    files: dict[str, Path],
    source: str,
    recompute_metrics: bool = True,
) -> ImportRun:
    """Run a full import of one export (4 files). Returns the finalized ImportRun.

    Raises on any error; the caller is responsible for rollback/commit.
    """
    missing = [name for name in REQUIRED_FILES if name not in files]
    if missing:
        raise ValueError(f"Missing export files: {', '.join(missing)}")

    run = create_import_run(session, source)

    # 1. Read the raw files (CSV/XLSX) and keep them in staging for traceability.
    tables = {name: read_table(files[name]) for name in REQUIRED_FILES}
    load_to_staging(session, run.id, tables)
    session.flush()

    # 2. Data-quality report — BEFORE the upsert, while diffs are still visible.
    quality = build_quality_report(session, run.id)

    # 3. Idempotent upsert into core by natural keys.
    stats = upsert_to_core(session, run.id)

    # 4. Derived metrics: the data they derive from may have just changed (M3).
    if recompute_metrics:
        from valeri_api.metrics.recompute import recompute_all

        recompute_all(session)

    # 5. Finalize the run.
    run.stats = stats.model_dump(mode="json")
    run.report = quality.model_dump(mode="json")
    run.status = "completed"
    run.finished_at = datetime.datetime.now(tz=datetime.UTC)
    session.flush()

    return run


def files_from_directory(directory: Path) -> dict[str, Path]:
    """Resolve the 4 export files inside a directory (csv or xlsx, csv preferred)."""
    files: dict[str, Path] = {}
    for name in REQUIRED_FILES:
        for extension in (".csv", ".xlsx", ".xlsm"):
            candidate = directory / f"{name}{extension}"
            if candidate.is_file():
                files[name] = candidate
                break
    return files
