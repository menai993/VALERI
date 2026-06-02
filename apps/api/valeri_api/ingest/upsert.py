"""Idempotent upsert from staging to core, matching by natural keys only.

Natural keys: legal entity = JIB (tax_id) · customer = external_code ·
category = name · article = code · invoice = external_no. Internal database
IDs never cross the import boundary. Re-importing identical data touches
zero core rows.
"""

import datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import insert, select, text
from sqlalchemy.orm import Session

from valeri_api.domain.models import (
    Article,
    Category,
    Customer,
    CustomerRep,
    Invoice,
    InvoiceLine,
    LegalEntity,
    SalesRep,
)
from valeri_api.ingest.models import StagingArtikal, StagingFaktura, StagingKupac, StagingStavka
from valeri_api.ingest.schemas import EntityStats, ImportStats, LineStats

_TRUE_VALUES = {"da", "true", "1", "yes"}


def upsert_to_core(session: Session, run_id: int) -> ImportStats:
    """Run the full staging → core upsert for one import run. Returns per-entity stats."""
    kupci_stats = _upsert_customers(session, run_id)
    artikli_stats = _upsert_articles(session, run_id)
    fakture_stats, stavke_stats = _upsert_invoices(session, run_id)
    return ImportStats(
        kupci=kupci_stats, artikli=artikli_stats, fakture=fakture_stats, stavke=stavke_stats
    )


# ── customers (legal entities, customers, reps) ──────────────────────────────


def _upsert_customers(session: Session, run_id: int) -> EntityStats:
    staged = session.scalars(
        select(StagingKupac)
        .where(StagingKupac.import_run_id == run_id)
        .order_by(StagingKupac.row_no)
    ).all()

    stats = EntityStats()

    # Legal entities by JIB.
    entities_by_tax_id = {
        entity.tax_id: entity for entity in session.scalars(select(LegalEntity)) if entity.tax_id
    }
    for row in staged:
        if not row.jib:
            continue
        existing = entities_by_tax_id.get(row.jib)
        if existing is None:
            entity = LegalEntity(name=row.naziv_pravnog_lica or row.naziv or "", tax_id=row.jib)
            session.add(entity)
            entities_by_tax_id[row.jib] = entity
        elif row.naziv_pravnog_lica and existing.name != row.naziv_pravnog_lica:
            existing.name = row.naziv_pravnog_lica
    session.flush()

    # Sales reps by name.
    reps_by_name = {rep.name: rep for rep in session.scalars(select(SalesRep))}
    for row in staged:
        if row.komercijalista and row.komercijalista not in reps_by_name:
            rep = SalesRep(name=row.komercijalista)
            session.add(rep)
            reps_by_name[row.komercijalista] = rep
    session.flush()

    # Customers by external code.
    customers_by_code = {
        customer.external_code: customer
        for customer in session.scalars(select(Customer))
        if customer.external_code
    }
    assigned_customer_ids = {
        assignment.customer_id for assignment in session.scalars(select(CustomerRep))
    }

    for row in staged:
        if not row.sifra:
            continue
        entity = entities_by_tax_id.get(row.jib) if row.jib else None
        existing = customers_by_code.get(row.sifra)

        if existing is None:
            if entity is None:
                # A customer without a resolvable legal entity gets its own entity.
                entity = LegalEntity(name=row.naziv or row.sifra)
                session.add(entity)
                session.flush()
            customer = Customer(
                legal_entity_id=entity.id,
                name=row.naziv or row.sifra,
                segment=row.segment or None,
                status=row.status or "active",
                external_code=row.sifra,
            )
            session.add(customer)
            session.flush()
            customers_by_code[row.sifra] = customer
            stats.created += 1
        else:
            changed = False
            if row.naziv and existing.name != row.naziv:
                existing.name = row.naziv
                changed = True
            if (row.segment or None) != existing.segment:
                existing.segment = row.segment or None
                changed = True
            if row.status and existing.status != row.status:
                existing.status = row.status
                changed = True
            if entity is not None and existing.legal_entity_id != entity.id:
                existing.legal_entity_id = entity.id
                changed = True
            stats.updated += 1 if changed else 0
            stats.unchanged += 0 if changed else 1
            customer = existing

        # Rep assignment: only created when the customer has none (never moved here).
        rep = reps_by_name.get(row.komercijalista) if row.komercijalista else None
        if rep is not None and customer.id not in assigned_customer_ids:
            session.add(
                CustomerRep(
                    customer_id=customer.id,
                    sales_rep_id=rep.id,
                    from_date=datetime.date.today(),
                )
            )
            assigned_customer_ids.add(customer.id)

    session.flush()
    return stats


# ── articles (categories, articles) ──────────────────────────────────────────


def _upsert_articles(session: Session, run_id: int) -> EntityStats:
    staged = session.scalars(
        select(StagingArtikal)
        .where(StagingArtikal.import_run_id == run_id)
        .order_by(StagingArtikal.row_no)
    ).all()

    stats = EntityStats()

    categories_by_name = {category.name: category for category in session.scalars(select(Category))}
    for row in staged:
        if row.kategorija and row.kategorija not in categories_by_name:
            category = Category(name=row.kategorija)
            session.add(category)
            categories_by_name[row.kategorija] = category
    session.flush()

    articles_by_code = {article.code: article for article in session.scalars(select(Article))}
    seen_codes: set[str] = set()

    for row in staged:
        if not row.sifra or row.sifra in seen_codes:
            continue  # duplicates within the export are flagged by the quality report
        seen_codes.add(row.sifra)

        category = categories_by_name.get(row.kategorija) if row.kategorija else None
        active = (row.aktivan or "").lower() in _TRUE_VALUES
        existing = articles_by_code.get(row.sifra)

        if existing is None:
            article = Article(
                category_id=category.id if category else None,
                code=row.sifra,
                name=row.naziv or row.sifra,
                active=active,
            )
            session.add(article)
            articles_by_code[row.sifra] = article
            stats.created += 1
        else:
            changed = False
            if row.naziv and existing.name != row.naziv:
                existing.name = row.naziv  # rename applied; the report flags it
                changed = True
            if category is not None and existing.category_id != category.id:
                existing.category_id = category.id
                changed = True
            if existing.active != active:
                existing.active = active
                changed = True
            stats.updated += 1 if changed else 0
            stats.unchanged += 0 if changed else 1

    session.flush()
    return stats


# ── invoices + lines ─────────────────────────────────────────────────────────


def _parse_decimal(value: str | None) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(value.replace(",", "."))
    except InvalidOperation:
        return None


def _parse_date(value: str | None) -> datetime.date | None:
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(value[:10])
    except ValueError:
        return None


def _upsert_invoices(session: Session, run_id: int) -> tuple[EntityStats, LineStats]:
    invoice_stats = EntityStats()
    line_stats = LineStats()

    customers_by_code = {
        customer.external_code: customer.id
        for customer in session.scalars(select(Customer))
        if customer.external_code
    }
    articles_by_code = {article.code: article.id for article in session.scalars(select(Article))}
    alias_to_article = {
        row.old_code: row.new_article_id
        for row in session.execute(text("SELECT old_code, new_article_id FROM core.article_alias"))
    }

    def resolve_article(code: str | None) -> int | None:
        if not code:
            return None
        return articles_by_code.get(code) or alias_to_article.get(code)

    # Existing invoices by external number.
    existing_invoices = {
        invoice.external_no: invoice
        for invoice in session.scalars(select(Invoice))
        if invoice.external_no
    }

    # Staged lines grouped by invoice number.
    staged_lines: dict[str, list[StagingStavka]] = {}
    for line in session.scalars(
        select(StagingStavka)
        .where(StagingStavka.import_run_id == run_id)
        .order_by(StagingStavka.row_no)
    ):
        if line.broj_fakture:
            staged_lines.setdefault(line.broj_fakture, []).append(line)

    staged_invoices = session.scalars(
        select(StagingFaktura)
        .where(StagingFaktura.import_run_id == run_id)
        .order_by(StagingFaktura.row_no)
    ).all()

    new_invoice_rows: list[dict] = []
    pending_lines: dict[str, list[dict]] = {}  # external_no -> line dicts (article resolved)

    for row in staged_invoices:
        external_no = row.broj_fakture
        customer_id = customers_by_code.get(row.sifra_kupca or "")
        invoice_date = _parse_date(row.datum)
        total = _parse_decimal(row.ukupno)
        if not external_no or customer_id is None or invoice_date is None or total is None:
            continue  # unresolvable rows are visible via the quality report / staging

        lines = [
            line_dict
            for line in staged_lines.get(external_no, [])
            if (line_dict := _build_line_dict(line, resolve_article(line.sifra_artikla)))
            is not None
        ]

        existing = existing_invoices.get(external_no)
        if existing is None:
            new_invoice_rows.append(
                {
                    "customer_id": customer_id,
                    "date": invoice_date,
                    "total": total,
                    "external_no": external_no,
                }
            )
            pending_lines[external_no] = lines
            invoice_stats.created += 1
            line_stats.created += len(lines)
        elif (
            existing.customer_id == customer_id
            and existing.date == invoice_date
            and existing.total == total
        ):
            invoice_stats.unchanged += 1
            line_stats.unchanged += len(lines)
        else:
            # The source changed this invoice: update the header, replace the lines.
            existing.customer_id = customer_id
            existing.date = invoice_date
            existing.total = total
            session.execute(
                text("DELETE FROM core.invoice_line WHERE invoice_id = :invoice_id"),
                {"invoice_id": existing.id},
            )
            for line_dict in lines:
                line_dict["invoice_id"] = existing.id
            if lines:
                session.execute(insert(InvoiceLine), lines)
            invoice_stats.updated += 1
            line_stats.replaced += len(lines)

    # Bulk-insert new invoices, then their lines (ids resolved via RETURNING).
    if new_invoice_rows:
        inserted = session.execute(
            insert(Invoice).returning(Invoice.id, Invoice.external_no), new_invoice_rows
        ).all()
        id_by_external_no = {row.external_no: row.id for row in inserted}

        all_line_rows: list[dict] = []
        for external_no, lines in pending_lines.items():
            invoice_id = id_by_external_no[external_no]
            for line_dict in lines:
                line_dict["invoice_id"] = invoice_id
                all_line_rows.append(line_dict)
        if all_line_rows:
            session.execute(insert(InvoiceLine), all_line_rows)

    session.flush()
    return invoice_stats, line_stats


def _build_line_dict(line: StagingStavka, article_id: int | None) -> dict | None:
    qty = _parse_decimal(line.kolicina)
    unit_price = _parse_decimal(line.cijena)
    line_total = _parse_decimal(line.iznos)
    if article_id is None or qty is None or unit_price is None or line_total is None:
        return None  # orphan/unparseable lines are flagged by the quality report
    return {
        "article_id": article_id,
        "qty": qty,
        "unit_price": unit_price,
        "line_total": line_total,
    }
