"""SQLAlchemy models for uploaded documents (DI1a).

document → document_page (extracted/OCR'd text per page) → document_extraction
(candidate fields/facts before they land in the KB). Originals live in object
storage (MinIO); `file_path` is the storage key, never raw bytes in the DB.
"""

import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, Numeric, Text, func
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from valeri_api.db import Base

# ── enums (created in migration 0021) ──────────────────────────────────────────

DOC_TYPES = (
    "invoice",
    "contract",
    "price_list",
    "delivery_note",
    "offer",
    "statement",
    "other",
)
DOC_SOURCES = ("upload", "scan", "email")
DOC_STATUSES = (
    "uploaded",
    "parsing",
    "ocr",
    "extracting",
    "needs_review",
    "processed",
    "failed",
)

doc_type_enum = ENUM(*DOC_TYPES, name="doc_type", create_type=False)
doc_source_enum = ENUM(*DOC_SOURCES, name="doc_source", create_type=False)
doc_status_enum = ENUM(*DOC_STATUSES, name="doc_status", create_type=False)
kb_status_enum = ENUM(
    "proposed", "active", "superseded", "rejected", name="kb_status", create_type=False
)


class Document(Base):
    """One uploaded file; the original is stored in object storage by `file_path` key."""

    __tablename__ = "document"
    __table_args__ = {"schema": "app"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    legal_entity_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("core.legal_entity.id")
    )
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    doc_type: Mapped[str | None] = mapped_column(doc_type_enum)
    source: Mapped[str] = mapped_column(doc_source_enum, nullable=False, server_default="upload")
    is_scanned: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    ocr_confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str | None] = mapped_column(Text, unique=True)
    uploaded_by: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(doc_status_enum, nullable=False, server_default="uploaded")
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DocumentPage(Base):
    """Extracted (born-digital) or OCR'd (DI1b) text for one page of a document."""

    __tablename__ = "document_page"
    __table_args__ = {"schema": "app"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("app.document.id"), nullable=False
    )
    page_no: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str | None] = mapped_column(Text)
    ocr_confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    image_ref: Mapped[str | None] = mapped_column(Text)
    layout: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class DocumentExtraction(Base):
    """One extraction pass over a document (provenance/debug; candidates before KB write)."""

    __tablename__ = "document_extraction"
    __table_args__ = {"schema": "app"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("app.document.id"), nullable=False
    )
    page_no: Mapped[int | None] = mapped_column(Integer)
    extracted: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    model: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    status: Mapped[str] = mapped_column(kb_status_enum, nullable=False, server_default="proposed")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
