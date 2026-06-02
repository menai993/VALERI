"""Pydantic schemas for the ingest API (typed I/O per CLAUDE.md conventions)."""

import datetime

from pydantic import BaseModel


class ImportResult(BaseModel):
    """Response of POST /api/ingest/import."""

    import_id: int


class EntityStats(BaseModel):
    """Per-entity upsert counters."""

    created: int = 0
    updated: int = 0
    unchanged: int = 0


class LineStats(BaseModel):
    """Invoice-line counters (lines are replaced wholesale when their invoice changes)."""

    created: int = 0
    replaced: int = 0
    unchanged: int = 0


class DuplicateCode(BaseModel):
    code: str
    names: list[str]


class RenamedArticle(BaseModel):
    code: str
    old_name: str
    new_name: str


class CodeSwapCandidate(BaseModel):
    old_code: str
    new_code: str
    name: str
    already_mapped: bool


class MissingSegment(BaseModel):
    customer_code: str
    name: str


class OrphanLine(BaseModel):
    row_no: int
    broj_fakture: str | None
    sifra_artikla: str | None
    reason: str  # unknown_invoice | unknown_article


class QualityReport(BaseModel):
    """The data-quality report — all values produced by SQL, never by an LLM."""

    duplicate_customer_codes: list[DuplicateCode] = []
    duplicate_article_codes: list[DuplicateCode] = []
    renamed_articles: list[RenamedArticle] = []
    code_swap_candidates: list[CodeSwapCandidate] = []
    missing_segments: list[MissingSegment] = []
    orphan_lines: list[OrphanLine] = []


class ImportStats(BaseModel):
    kupci: EntityStats
    artikli: EntityStats
    fakture: EntityStats
    stavke: LineStats


class ImportReport(BaseModel):
    """Response of GET /api/ingest/report/{import_id}."""

    import_id: int
    status: str
    source: str
    started_at: datetime.datetime
    finished_at: datetime.datetime | None
    stats: ImportStats | None
    quality: QualityReport | None
