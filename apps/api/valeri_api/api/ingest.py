"""Ingest API: trigger an import and fetch its data-quality report (M2).

POST /api/ingest/import   — multipart upload (kupci/artikli/fakture/stavke)
                            or a form field `path` pointing to a server-side
                            directory with the export files.
GET  /api/ingest/report/{import_id}

RBAC (M8): admin only — importing data is an administrative operation.
"""

import datetime
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from valeri_api.auth.deps import require_roles
from valeri_api.db import get_session
from valeri_api.ingest.models import ImportRun
from valeri_api.ingest.pipeline import files_from_directory, run_import
from valeri_api.ingest.schemas import ImportReport, ImportResult

router = APIRouter(dependencies=[Depends(require_roles("admin"))])


class ImportRunSummary(BaseModel):
    import_id: int
    source: str
    status: str
    started_at: datetime.datetime
    finished_at: datetime.datetime | None
    stats: dict | None


class ImportRunList(BaseModel):
    items: list[ImportRunSummary]


@router.post("/ingest/import", status_code=201, response_model=ImportResult)
def import_export(
    session: Annotated[Session, Depends(get_session)],
    kupci: Annotated[UploadFile | None, File()] = None,
    artikli: Annotated[UploadFile | None, File()] = None,
    fakture: Annotated[UploadFile | None, File()] = None,
    stavke: Annotated[UploadFile | None, File()] = None,
    path: Annotated[str | None, Form()] = None,
) -> ImportResult:
    """Import an ERP export. Synchronous; any failure rolls back everything."""
    uploads = {"kupci": kupci, "artikli": artikli, "fakture": fakture, "stavke": stavke}

    if path is not None:
        directory = Path(path)
        if not directory.is_dir():
            raise HTTPException(
                status_code=400,
                detail={"code": "invalid_path", "message": f"Not a directory: {path}"},
            )
        files = files_from_directory(directory)
        return _run(session, files, source=f"path:{path}")

    provided = {name: upload for name, upload in uploads.items() if upload is not None}
    if len(provided) != 4:
        missing = sorted(set(uploads) - set(provided))
        raise HTTPException(
            status_code=422,
            detail={
                "code": "missing_files",
                "message": f"Upload all four export files; missing: {', '.join(missing)}",
            },
        )

    # Persist uploads to a temp dir so the readers can work with real paths.
    with tempfile.TemporaryDirectory(prefix="valeri-import-") as temp_dir:
        files = {}
        for name, upload in provided.items():
            suffix = Path(upload.filename or f"{name}.csv").suffix or ".csv"
            target = Path(temp_dir) / f"{name}{suffix}"
            target.write_bytes(upload.file.read())
            files[name] = target
        return _run(session, files, source="api")


def _run(session: Session, files: dict[str, Path], source: str) -> ImportResult:
    try:
        run = run_import(session, files, source=source)
        run_id = run.id
        session.commit()
    except (ValueError, KeyError) as error:
        session.rollback()
        raise HTTPException(
            status_code=400,
            detail={"code": "import_failed", "message": str(error)},
        ) from error
    return ImportResult(import_id=run_id)


@router.get("/ingest/imports", response_model=ImportRunList)
def list_imports(
    session: Annotated[Session, Depends(get_session)],
    limit: int = 50,
) -> ImportRunList:
    """Past import runs, newest first (the import history)."""
    limit = max(1, min(limit, 200))
    runs = session.scalars(
        select(ImportRun).order_by(ImportRun.id.desc()).limit(limit)
    ).all()
    return ImportRunList(
        items=[
            ImportRunSummary(
                import_id=run.id,
                source=run.source,
                status=run.status,
                started_at=run.started_at,
                finished_at=run.finished_at,
                stats=run.stats,
            )
            for run in runs
        ]
    )


@router.get("/ingest/report/{import_id}", response_model=ImportReport)
def get_report(import_id: int, session: Annotated[Session, Depends(get_session)]) -> ImportReport:
    """Fetch the stats + data-quality report of a finished import."""
    run = session.get(ImportRun, import_id)
    if run is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": f"Import {import_id} not found"},
        )
    return ImportReport(
        import_id=run.id,
        status=run.status,
        source=run.source,
        started_at=run.started_at,
        finished_at=run.finished_at,
        stats=run.stats,
        quality=run.report,
    )
