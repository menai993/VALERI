"""Staging tables for ERP imports + core.invoice.external_no.

M2: staging.import_run (one row per import, carries stats + the data-quality
report), staging.kupci/artikli/fakture/stavke (raw export rows, kept for
traceability), and the natural key core.invoice.external_no for idempotent
invoice upserts (spec m2-ingest, decision D1).

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── staging.import_run ────────────────────────────────────────────────────
    op.create_table(
        "import_run",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'running'")),
        sa.Column("stats", JSONB(), nullable=True),
        sa.Column("report", JSONB(), nullable=True),
        schema="staging",
    )

    # ── raw export rows (all payload columns TEXT, kept per run) ─────────────
    raw_tables = {
        "kupci": [
            "sifra",
            "naziv",
            "jib",
            "naziv_pravnog_lica",
            "segment",
            "status",
            "komercijalista",
        ],
        "artikli": ["sifra", "naziv", "kategorija", "aktivan"],
        "fakture": ["broj_fakture", "sifra_kupca", "datum", "ukupno"],
        "stavke": ["broj_fakture", "sifra_artikla", "kolicina", "cijena", "iznos"],
    }
    for table_name, payload_columns in raw_tables.items():
        op.create_table(
            table_name,
            sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
            sa.Column(
                "import_run_id",
                sa.BigInteger(),
                sa.ForeignKey("staging.import_run.id"),
                nullable=False,
            ),
            sa.Column("row_no", sa.Integer(), nullable=False),
            *[sa.Column(column, sa.Text(), nullable=True) for column in payload_columns],
            schema="staging",
        )
        op.create_index(
            f"ix_staging_{table_name}_run", table_name, ["import_run_id"], schema="staging"
        )

    # ── core.invoice.external_no (natural key for idempotent imports) ────────
    op.add_column("invoice", sa.Column("external_no", sa.Text(), nullable=True), schema="core")
    op.create_index(
        "ux_invoice_external_no",
        "invoice",
        ["external_no"],
        unique=True,
        schema="core",
        postgresql_where=sa.text("external_no IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ux_invoice_external_no", table_name="invoice", schema="core")
    op.drop_column("invoice", "external_no", schema="core")

    for table_name in ("stavke", "fakture", "artikli", "kupci"):
        op.drop_index(f"ix_staging_{table_name}_run", table_name=table_name, schema="staging")
        op.drop_table(table_name, schema="staging")
    op.drop_table("import_run", schema="staging")
