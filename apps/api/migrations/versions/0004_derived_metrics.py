"""Derived metric tables (recomputed by SQL, never by the LLM).

M3: core.customer_metrics, core.cust_article_cadence, core.segment_basket —
exactly per docs/data-model.md (derived metrics section).

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "customer_metrics",
        sa.Column(
            "customer_id",
            sa.BigInteger(),
            sa.ForeignKey("core.customer.id"),
            primary_key=True,
        ),
        sa.Column("turnover_60d", sa.Numeric(14, 2), nullable=True),
        sa.Column("turnover_6m_avg_60d", sa.Numeric(14, 2), nullable=True),
        sa.Column("last_order_date", sa.Date(), nullable=True),
        sa.Column("avg_order_interval_d", sa.Numeric(8, 2), nullable=True),
        sa.Column("segment", sa.Text(), nullable=True),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema="core",
    )

    op.create_table(
        "cust_article_cadence",
        sa.Column(
            "customer_id",
            sa.BigInteger(),
            sa.ForeignKey("core.customer.id"),
            primary_key=True,
        ),
        sa.Column(
            "article_id",
            sa.BigInteger(),
            sa.ForeignKey("core.article.id"),
            primary_key=True,
        ),
        sa.Column("avg_interval_d", sa.Numeric(8, 2), nullable=True),
        sa.Column("last_seen", sa.Date(), nullable=True),
        schema="core",
    )

    op.create_table(
        "segment_basket",
        sa.Column("segment", sa.Text(), primary_key=True),
        sa.Column(
            "category_id",
            sa.BigInteger(),
            sa.ForeignKey("core.category.id"),
            primary_key=True,
        ),
        sa.Column("prevalence", sa.Numeric(5, 4), nullable=True),
        schema="core",
    )


def downgrade() -> None:
    op.drop_table("segment_basket", schema="core")
    op.drop_table("cust_article_cadence", schema="core")
    op.drop_table("customer_metrics", schema="core")
