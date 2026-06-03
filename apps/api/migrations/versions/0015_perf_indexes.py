"""Perf pass: an index for all-customer date-range aggregations (M14).

The dashboard revenue trend, the weekly report, and the customer-metrics baseline
all filter core.invoice by `date` across ALL customers (e.g. WHERE date > as_of - 60).
The existing composite ix_invoice_customer_date leads with customer_id, so it
cannot serve a date-only range scan — those queries seq-scan core.invoice, which
grows unboundedly with real data. A standalone btree on (date) backs them.

Evidence (EXPLAIN on the seed): the all-customer 60-day aggregation seq-scans
core.invoice; per-customer queries already use ix_invoice_customer_date and are
untouched. This is the only index the perf pass found missing.

Revision ID: 0015
Revises: 0014
Create Date: 2026-06-03
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_invoice_date", "invoice", ["date"], schema="core")


def downgrade() -> None:
    op.drop_index("ix_invoice_date", "invoice", schema="core")
