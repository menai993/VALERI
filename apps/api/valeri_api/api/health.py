"""Health endpoint — proves the API process runs and the DB wiring works."""

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text

from valeri_api.db import get_engine

router = APIRouter()


class HealthResponse(BaseModel):
    """Status of the API process and its database dependency."""

    status: str
    db: str


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness/readiness probe. Always 200; the db field reports dependency state."""
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception:
        db_status = "unavailable"
    return HealthResponse(status="ok", db=db_status)
