"""DI1a: document ingestion → knowledge base (born-digital).

Adds the document tables per docs/document-intelligence.md §4 (document,
document_page, document_extraction) and their enums; extends client_fact /
commercial_event with document+page provenance (additive, nullable). No OCR /
pgvector here (DI1b / DI2). Documents add context; they never overwrite ERP
numbers (enforced in the pipeline, not the schema).

Revision ID: 0023
Revises: 0022
Create Date: 2026-06-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_ENUMS = {
    "doc_type": (
        "invoice",
        "contract",
        "price_list",
        "delivery_note",
        "offer",
        "statement",
        "other",
    ),
    "doc_source": ("upload", "scan", "email"),
    "doc_status": (
        "uploaded",
        "parsing",
        "ocr",
        "extracting",
        "needs_review",
        "processed",
        "failed",
    ),
}


def upgrade() -> None:
    for name, values in _NEW_ENUMS.items():
        labels = ", ".join(f"'{v}'" for v in values)
        op.execute(f"CREATE TYPE {name} AS ENUM ({labels})")

    op.create_table(
        "document",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("legal_entity_id", sa.BigInteger, sa.ForeignKey("core.legal_entity.id")),
        sa.Column("filename", sa.Text, nullable=False),
        sa.Column("mime_type", sa.Text, nullable=False),
        sa.Column("doc_type", sa.Enum(*_NEW_ENUMS["doc_type"], name="doc_type", create_type=False)),
        sa.Column(
            "source",
            sa.Enum(*_NEW_ENUMS["doc_source"], name="doc_source", create_type=False),
            nullable=False,
            server_default="upload",
        ),
        sa.Column("is_scanned", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("ocr_confidence", sa.Numeric(4, 3)),
        sa.Column("file_path", sa.Text, nullable=False),  # object-storage key
        sa.Column("sha256", sa.Text, unique=True),
        sa.Column("uploaded_by", sa.BigInteger),
        sa.Column(
            "status",
            sa.Enum(*_NEW_ENUMS["doc_status"], name="doc_status", create_type=False),
            nullable=False,
            server_default="uploaded",
        ),
        sa.Column("error", sa.Text),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        schema="app",
    )

    op.create_table(
        "document_page",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column(
            "document_id", sa.BigInteger, sa.ForeignKey("app.document.id"), nullable=False
        ),
        sa.Column("page_no", sa.Integer, nullable=False),
        sa.Column("text", sa.Text),
        sa.Column("ocr_confidence", sa.Numeric(4, 3)),
        sa.Column("image_ref", sa.Text),
        sa.Column("layout", JSONB),
        schema="app",
    )
    op.create_index("ix_docpage_doc", "document_page", ["document_id"], schema="app")

    op.create_table(
        "document_extraction",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column(
            "document_id", sa.BigInteger, sa.ForeignKey("app.document.id"), nullable=False
        ),
        sa.Column("page_no", sa.Integer),
        sa.Column("extracted", JSONB, nullable=False),
        sa.Column("model", sa.Text),
        sa.Column("confidence", sa.Numeric(4, 3)),
        sa.Column(
            "status",
            sa.Enum("proposed", "active", "superseded", "rejected", name="kb_status", create_type=False),
            nullable=False,
            server_default="proposed",
        ),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        schema="app",
    )

    # KB provenance: a document-sourced fact/event points back to its document + page.
    for table in ("client_fact", "commercial_event"):
        op.add_column(
            table,
            sa.Column("source_document_id", sa.BigInteger, sa.ForeignKey("app.document.id")),
            schema="app",
        )
        op.add_column(table, sa.Column("source_page", sa.Integer), schema="app")


def downgrade() -> None:
    for table in ("client_fact", "commercial_event"):
        op.drop_column(table, "source_page", schema="app")
        op.drop_column(table, "source_document_id", schema="app")
    op.drop_table("document_extraction", schema="app")
    op.drop_index("ix_docpage_doc", table_name="document_page", schema="app")
    op.drop_table("document_page", schema="app")
    op.drop_table("document", schema="app")
    for name in _NEW_ENUMS:
        op.execute(f"DROP TYPE {name}")
