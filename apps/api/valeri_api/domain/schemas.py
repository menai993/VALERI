"""Pydantic v2 read schemas for the core business graph (one per model)."""

import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class _Read(BaseModel):
    """Base for ORM-backed read schemas."""

    model_config = ConfigDict(from_attributes=True)


class LegalEntityRead(_Read):
    id: int
    name: str
    tax_id: str | None
    created_at: datetime.datetime


class CustomerRead(_Read):
    id: int
    legal_entity_id: int
    name: str
    segment: str | None
    status: str
    external_code: str | None
    created_at: datetime.datetime


class ContactRead(_Read):
    """Contact identity is PII — never include in any LLM payload (principle 6)."""

    id: int
    customer_id: int
    name: str | None
    email: str | None
    phone: str | None
    address: str | None


class SalesRepRead(_Read):
    id: int
    name: str
    email: str | None


class CustomerRepRead(_Read):
    customer_id: int
    sales_rep_id: int
    from_date: datetime.date


class CategoryRead(_Read):
    id: int
    name: str


class ArticleRead(_Read):
    id: int
    category_id: int | None
    code: str
    name: str
    active: bool


class ArticleAliasRead(_Read):
    old_code: str
    new_article_id: int
    mapped_at: datetime.datetime


class InvoiceRead(_Read):
    id: int
    customer_id: int
    date: datetime.date
    total: Decimal


class InvoiceLineRead(_Read):
    id: int
    invoice_id: int
    article_id: int
    qty: Decimal
    unit_price: Decimal
    line_total: Decimal
