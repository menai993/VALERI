"""Structure tests for the core.* domain models (M1, docs/data-model.md)."""

import datetime
from decimal import Decimal

import pytest
from sqlalchemy import Engine, Numeric, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

EXPECTED_TABLES = {
    "legal_entity",
    "customer",
    "contact",
    "sales_rep",
    "customer_rep",
    "category",
    "article",
    "article_alias",
    "invoice",
    "invoice_line",
}


def test_core_tables_exist(db_engine: Engine) -> None:
    """After alembic upgrade head, all ten core.* tables exist."""
    inspector = inspect(db_engine)
    tables = set(inspector.get_table_names(schema="core"))
    missing = EXPECTED_TABLES - tables
    assert not missing, f"missing core tables: {missing}"


def test_article_code_unique(db_session: Session) -> None:
    """article.code carries a unique constraint (ux_article_code)."""
    from valeri_api.domain.models import Article, Category

    category = Category(name="papir")
    db_session.add(category)
    db_session.flush()

    db_session.add(Article(category_id=category.id, code="DUP-001", name="Artikal A"))
    db_session.flush()

    db_session.add(Article(category_id=category.id, code="DUP-001", name="Artikal B"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_fk_integrity_enforced(db_session: Session) -> None:
    """A customer cannot reference a non-existent legal entity."""
    from valeri_api.domain.models import Customer

    db_session.add(Customer(legal_entity_id=999_999_999, name="Sirče d.o.o."))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_money_columns_are_numeric(db_engine: Engine, db_session: Session) -> None:
    """Money columns are NUMERIC with the spec'd precision and round-trip Decimal exactly."""
    from valeri_api.domain.models import (
        Article,
        Category,
        Customer,
        Invoice,
        InvoiceLine,
        LegalEntity,
    )

    inspector = inspect(db_engine)

    invoice_cols = {c["name"]: c["type"] for c in inspector.get_columns("invoice", schema="core")}
    line_cols = {c["name"]: c["type"] for c in inspector.get_columns("invoice_line", schema="core")}

    assert isinstance(invoice_cols["total"], Numeric)
    assert (invoice_cols["total"].precision, invoice_cols["total"].scale) == (14, 2)
    assert isinstance(line_cols["qty"], Numeric)
    assert (line_cols["qty"].precision, line_cols["qty"].scale) == (14, 3)
    assert isinstance(line_cols["unit_price"], Numeric)
    assert (line_cols["unit_price"].precision, line_cols["unit_price"].scale) == (14, 4)
    assert isinstance(line_cols["line_total"], Numeric)
    assert (line_cols["line_total"].precision, line_cols["line_total"].scale) == (14, 2)

    # Round-trip a precise Decimal through the ORM and back.
    entity = LegalEntity(name="Hotel Test d.o.o.", tax_id="4200000000001")
    db_session.add(entity)
    db_session.flush()
    customer = Customer(legal_entity_id=entity.id, name="Hotel Test", segment="hotel")
    category = Category(name="hemija")
    db_session.add_all([customer, category])
    db_session.flush()
    article = Article(category_id=category.id, code="HEM-001", name="Deterdžent 5L")
    db_session.add(article)
    db_session.flush()

    invoice = Invoice(
        customer_id=customer.id, date=datetime.date(2026, 1, 15), total=Decimal("123.45")
    )
    db_session.add(invoice)
    db_session.flush()
    line = InvoiceLine(
        invoice_id=invoice.id,
        article_id=article.id,
        qty=Decimal("3.000"),
        unit_price=Decimal("41.1500"),
        line_total=Decimal("123.45"),
    )
    db_session.add(line)
    db_session.flush()

    db_session.expire_all()
    reloaded = db_session.get(InvoiceLine, line.id)
    assert reloaded is not None
    assert reloaded.unit_price == Decimal("41.1500")
    assert reloaded.line_total == Decimal("123.45")
    assert isinstance(reloaded.line_total, Decimal)

    reloaded_invoice = db_session.get(Invoice, invoice.id)
    assert reloaded_invoice is not None
    assert reloaded_invoice.total == Decimal("123.45")


def test_customer_rep_composite_pk(db_session: Session) -> None:
    """customer_rep has a composite PK (customer_id, sales_rep_id, from_date)."""
    from valeri_api.domain.models import Customer, CustomerRep, LegalEntity, SalesRep

    entity = LegalEntity(name="Restoran Test d.o.o.")
    db_session.add(entity)
    db_session.flush()
    customer = Customer(legal_entity_id=entity.id, name="Restoran Test", segment="restoran")
    rep = SalesRep(name="Amir Testić", email="amir@example.com")
    db_session.add_all([customer, rep])
    db_session.flush()

    assignment_date = datetime.date(2026, 1, 1)
    db_session.add(
        CustomerRep(customer_id=customer.id, sales_rep_id=rep.id, from_date=assignment_date)
    )
    db_session.flush()

    # Same (customer, rep, from_date) → PK violation.
    db_session.add(
        CustomerRep(customer_id=customer.id, sales_rep_id=rep.id, from_date=assignment_date)
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
