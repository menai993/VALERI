"""Bulk-load generated seed data into core.*/app.app_user (and reset for re-seeding)."""

from sqlalchemy import insert, text
from sqlalchemy.orm import Session

from valeri_api.auth.models import AppUser
from valeri_api.crm.models import Activity, Opportunity, OpportunityStageHistory, RevenueTarget
from valeri_api.domain.models import (
    Article,
    ArticleAlias,
    Category,
    Contact,
    Customer,
    CustomerRep,
    Invoice,
    InvoiceLine,
    LegalEntity,
    SalesRep,
)
from valeri_api.seed.types import SeedData

# FK-safe insert order: (model, SeedData attribute).
_INSERT_ORDER = [
    (LegalEntity, "legal_entities"),
    (SalesRep, "sales_reps"),
    (Category, "categories"),
    (Customer, "customers"),
    (Article, "articles"),
    (Contact, "contacts"),
    (CustomerRep, "customer_reps"),
    (ArticleAlias, "article_aliases"),
    (Invoice, "invoices"),
    (InvoiceLine, "invoice_lines"),
    (AppUser, "app_users"),
    (Opportunity, "opportunities"),
    (OpportunityStageHistory, "opportunity_stage_history"),
    (Activity, "activities"),
    (RevenueTarget, "revenue_targets"),
]

# Tables whose identity sequence must be advanced past the explicit seed IDs.
_SEQUENCE_TABLES = [
    "core.legal_entity",
    "core.sales_rep",
    "core.category",
    "core.customer",
    "core.article",
    "core.contact",
    "core.invoice",
    "core.invoice_line",
    "app.app_user",
    "app.opportunity",
    "app.opportunity_stage_history",
    "app.activity",
    # revenue_target has a TEXT primary key (period) — no identity sequence to advance.
]

_ALL_TABLES = [
    "app.revenue_target",
    "app.activity",
    "app.opportunity_stage_history",
    "app.opportunity",
    "app.app_user",
    "core.invoice_line",
    "core.invoice",
    "core.article_alias",
    "core.article",
    "core.category",
    "core.customer_rep",
    "core.sales_rep",
    "core.contact",
    "core.customer",
    "core.legal_entity",
]


def reset(session: Session) -> None:
    """Truncate all seeded tables (dev/test convenience for idempotent re-seeding)."""
    session.execute(text(f"TRUNCATE {', '.join(_ALL_TABLES)} RESTART IDENTITY CASCADE"))


def load(data: SeedData, session: Session) -> None:
    """Bulk-insert all generated rows (explicit IDs), then advance the sequences."""
    for model, attribute in _INSERT_ORDER:
        rows = getattr(data, attribute)
        if rows:
            session.execute(insert(model), rows)

    for table in _SEQUENCE_TABLES:
        session.execute(
            text(
                f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                f"(SELECT COALESCE(MAX(id), 1) FROM {table}))"  # noqa: S608
            )
        )
