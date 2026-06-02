"""Bulk-load generated seed data into core.* (and reset for re-seeding)."""

from sqlalchemy import insert, text
from sqlalchemy.orm import Session

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
]

# Tables whose identity sequence must be advanced past the explicit seed IDs.
_SEQUENCE_TABLES = [
    "legal_entity",
    "sales_rep",
    "category",
    "customer",
    "article",
    "contact",
    "invoice",
    "invoice_line",
]

_ALL_TABLES = [
    "invoice_line",
    "invoice",
    "article_alias",
    "article",
    "category",
    "customer_rep",
    "sales_rep",
    "contact",
    "customer",
    "legal_entity",
]


def reset(session: Session) -> None:
    """Truncate all core.* tables (dev/test convenience for idempotent re-seeding)."""
    tables = ", ".join(f"core.{table}" for table in _ALL_TABLES)
    session.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


def load(data: SeedData, session: Session) -> None:
    """Bulk-insert all generated rows (explicit IDs), then advance the sequences."""
    for model, attribute in _INSERT_ORDER:
        rows = getattr(data, attribute)
        if rows:
            session.execute(insert(model), rows)

    for table in _SEQUENCE_TABLES:
        session.execute(
            text(
                f"SELECT setval(pg_get_serial_sequence('core.{table}', 'id'), "
                f"(SELECT COALESCE(MAX(id), 1) FROM core.{table}))"  # noqa: S608
            )
        )
