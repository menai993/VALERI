"""SQLAlchemy models for the core.* business graph (docs/data-model.md, M1).

Schema: core. Money is NUMERIC (Decimal in Python) — never float. PII columns
are marked; they must be masked before any LLM call (principle 6, from M6).
"""

import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from valeri_api.db import Base


class LegalEntity(Base):
    """A legal entity (firm); one entity can own several customer objects."""

    __tablename__ = "legal_entity"
    __table_args__ = {"schema": "core"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    tax_id: Mapped[str | None] = mapped_column(Text, unique=True)  # JIB/PDV
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    customers: Mapped[list["Customer"]] = relationship(back_populates="legal_entity")


class Customer(Base):
    """An object/location (hotel, restoran, kafić, klinika, škola); many per legal entity."""

    __tablename__ = "customer"
    __table_args__ = (
        Index("ix_customer_legal_entity", "legal_entity_id"),
        Index("ix_customer_segment", "segment"),
        {"schema": "core"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    legal_entity_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("core.legal_entity.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    segment: Mapped[str | None] = mapped_column(Text)  # hotel/restoran/kafić/klinika/škola
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'active'")
    )  # active/inactive/closed
    external_code: Mapped[str | None] = mapped_column(Text)  # code in the source ERP
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    legal_entity: Mapped[LegalEntity] = relationship(back_populates="customers")
    contacts: Mapped[list["Contact"]] = relationship(back_populates="customer")
    invoices: Mapped[list["Invoice"]] = relationship(back_populates="customer")
    rep_assignments: Mapped[list["CustomerRep"]] = relationship(back_populates="customer")


class Contact(Base):
    """A contact person at a customer. All identity columns are PII."""

    __tablename__ = "contact"
    __table_args__ = (
        Index("ix_contact_customer", "customer_id"),
        {"schema": "core"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    customer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("core.customer.id"), nullable=False
    )
    name: Mapped[str | None] = mapped_column(Text)  # PII
    email: Mapped[str | None] = mapped_column(Text)  # PII
    phone: Mapped[str | None] = mapped_column(Text)  # PII
    address: Mapped[str | None] = mapped_column(Text)  # PII

    customer: Mapped[Customer] = relationship(back_populates="contacts")


class SalesRep(Base):
    """A sales representative (komercijalista)."""

    __tablename__ = "sales_rep"
    __table_args__ = {"schema": "core"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str | None] = mapped_column(Text)

    customer_assignments: Mapped[list["CustomerRep"]] = relationship(back_populates="sales_rep")


class CustomerRep(Base):
    """Assignment of a customer to a sales rep, effective from a date."""

    __tablename__ = "customer_rep"
    __table_args__ = {"schema": "core"}

    customer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("core.customer.id"), primary_key=True
    )
    sales_rep_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("core.sales_rep.id"), primary_key=True
    )
    from_date: Mapped[datetime.date] = mapped_column(
        Date, primary_key=True, server_default=func.current_date()
    )

    customer: Mapped[Customer] = relationship(back_populates="rep_assignments")
    sales_rep: Mapped[SalesRep] = relationship(back_populates="customer_assignments")


class Category(Base):
    """An article category (papir, hemija, dispenzeri, …)."""

    __tablename__ = "category"
    __table_args__ = {"schema": "core"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)

    articles: Mapped[list["Article"]] = relationship(back_populates="category")


class Article(Base):
    """A sellable article."""

    __tablename__ = "article"
    __table_args__ = (
        Index("ux_article_code", "code", unique=True),
        Index("ix_article_category", "category_id"),
        {"schema": "core"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    category_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("core.category.id"))
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    category: Mapped[Category | None] = relationship(back_populates="articles")
    aliases: Mapped[list["ArticleAlias"]] = relationship(back_populates="new_article")
    lines: Mapped[list["InvoiceLine"]] = relationship(back_populates="article")


class ArticleAlias(Base):
    """Code-swap mapping: an old article code now sold under a new article."""

    __tablename__ = "article_alias"
    __table_args__ = {"schema": "core"}

    old_code: Mapped[str] = mapped_column(Text, primary_key=True)
    new_article_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("core.article.id"), nullable=False
    )
    mapped_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    new_article: Mapped[Article] = relationship(back_populates="aliases")


class Invoice(Base):
    """A customer invoice (header). total always equals the sum of its lines."""

    __tablename__ = "invoice"
    __table_args__ = (
        Index("ix_invoice_customer_date", "customer_id", "date"),
        {"schema": "core"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    customer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("core.customer.id"), nullable=False
    )
    date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, server_default=text("0"))
    # Invoice number in the source ERP (broj fakture) — the natural key for
    # idempotent imports (M2, spec decision D1).
    external_no: Mapped[str | None] = mapped_column(Text)

    customer: Mapped[Customer] = relationship(back_populates="invoices")
    lines: Mapped[list["InvoiceLine"]] = relationship(back_populates="invoice")


class InvoiceLine(Base):
    """A line on an invoice: article, quantity, unit price, line total."""

    __tablename__ = "invoice_line"
    __table_args__ = (
        Index("ix_line_invoice", "invoice_id"),
        Index("ix_line_article", "article_id"),
        {"schema": "core"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    invoice_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("core.invoice.id"), nullable=False
    )
    article_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("core.article.id"), nullable=False
    )
    qty: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    invoice: Mapped[Invoice] = relationship(back_populates="lines")
    article: Mapped[Article] = relationship(back_populates="lines")
