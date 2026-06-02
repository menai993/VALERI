"""Create the core.* business graph tables.

M1: legal_entity, customer, contact, sales_rep, customer_rep, category,
article, article_alias, invoice, invoice_line — exactly per
docs/data-model.md (core graph section).

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "legal_entity",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("tax_id", sa.Text(), nullable=True, unique=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema="core",
    )

    op.create_table(
        "customer",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "legal_entity_id",
            sa.BigInteger(),
            sa.ForeignKey("core.legal_entity.id"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("segment", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'active'")),
        sa.Column("external_code", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema="core",
    )
    op.create_index("ix_customer_legal_entity", "customer", ["legal_entity_id"], schema="core")
    op.create_index("ix_customer_segment", "customer", ["segment"], schema="core")

    op.create_table(
        "contact",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "customer_id", sa.BigInteger(), sa.ForeignKey("core.customer.id"), nullable=False
        ),
        sa.Column("name", sa.Text(), nullable=True),  # PII
        sa.Column("email", sa.Text(), nullable=True),  # PII
        sa.Column("phone", sa.Text(), nullable=True),  # PII
        sa.Column("address", sa.Text(), nullable=True),  # PII
        schema="core",
    )
    op.create_index("ix_contact_customer", "contact", ["customer_id"], schema="core")

    op.create_table(
        "sales_rep",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=True),
        schema="core",
    )

    op.create_table(
        "customer_rep",
        sa.Column(
            "customer_id",
            sa.BigInteger(),
            sa.ForeignKey("core.customer.id"),
            primary_key=True,
        ),
        sa.Column(
            "sales_rep_id",
            sa.BigInteger(),
            sa.ForeignKey("core.sales_rep.id"),
            primary_key=True,
        ),
        sa.Column(
            "from_date",
            sa.Date(),
            primary_key=True,
            server_default=sa.func.current_date(),
        ),
        schema="core",
    )

    op.create_table(
        "category",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        schema="core",
    )

    op.create_table(
        "article",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("category_id", sa.BigInteger(), sa.ForeignKey("core.category.id")),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        schema="core",
    )
    op.create_index("ux_article_code", "article", ["code"], unique=True, schema="core")
    op.create_index("ix_article_category", "article", ["category_id"], schema="core")

    op.create_table(
        "article_alias",
        sa.Column("old_code", sa.Text(), primary_key=True),
        sa.Column(
            "new_article_id",
            sa.BigInteger(),
            sa.ForeignKey("core.article.id"),
            nullable=False,
        ),
        sa.Column(
            "mapped_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema="core",
    )

    op.create_table(
        "invoice",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "customer_id", sa.BigInteger(), sa.ForeignKey("core.customer.id"), nullable=False
        ),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("total", sa.Numeric(14, 2), nullable=False, server_default=sa.text("0")),
        schema="core",
    )
    op.create_index("ix_invoice_customer_date", "invoice", ["customer_id", "date"], schema="core")

    op.create_table(
        "invoice_line",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("invoice_id", sa.BigInteger(), sa.ForeignKey("core.invoice.id"), nullable=False),
        sa.Column("article_id", sa.BigInteger(), sa.ForeignKey("core.article.id"), nullable=False),
        sa.Column("qty", sa.Numeric(14, 3), nullable=False),
        sa.Column("unit_price", sa.Numeric(14, 4), nullable=False),
        sa.Column("line_total", sa.Numeric(14, 2), nullable=False),
        schema="core",
    )
    op.create_index("ix_line_invoice", "invoice_line", ["invoice_id"], schema="core")
    op.create_index("ix_line_article", "invoice_line", ["article_id"], schema="core")


def downgrade() -> None:
    # Drop in FK-safe reverse order.
    op.drop_table("invoice_line", schema="core")
    op.drop_table("invoice", schema="core")
    op.drop_table("article_alias", schema="core")
    op.drop_table("article", schema="core")
    op.drop_table("category", schema="core")
    op.drop_table("customer_rep", schema="core")
    op.drop_table("sales_rep", schema="core")
    op.drop_table("contact", schema="core")
    op.drop_table("customer", schema="core")
    op.drop_table("legal_entity", schema="core")
