"""Capability A — the M1 acceptance test.

A sampled customer enumerates its legal entity, sibling objects, last-12-months
invoices, and assigned rep correctly, with no invented relationships: everything
the ORM returns must equal direct SQL against the seeded data.
"""

import datetime
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, selectinload


@pytest.fixture
def sampled_customer_ids(seed_data) -> list[int]:
    """One hotel-group object + one standalone customer, deterministically chosen.

    Planted customers are excluded so the samples show normal behaviour.
    """
    manifest = seed_data.manifest
    planted: set[int] = set()
    for key in ("declines", "seasonal_cafes", "narrow_baskets", "sleeping", "lost_articles"):
        planted.update(case["customer_id"] for case in manifest[key])

    hotel_object = next(
        c["id"] for c in seed_data.customers if c["segment"] == "hotel" and c["id"] not in planted
    )
    standalone = next(
        c["id"] for c in seed_data.customers if c["segment"] != "hotel" and c["id"] not in planted
    )
    return [hotel_object, standalone]


@pytest.mark.usefixtures("seeded_db")
def test_sampled_customer_enumeration(
    db_engine: Engine, seed_data, sampled_customer_ids: list[int]
) -> None:
    from valeri_api.domain.models import Customer

    as_of = datetime.date.fromisoformat(seed_data.manifest["as_of"])
    twelve_months_ago = as_of - datetime.timedelta(days=365)

    seeded_customer_by_id = {c["id"]: c for c in seed_data.customers}
    seeded_entity_by_id = {e["id"]: e for e in seed_data.legal_entities}
    seeded_rep_by_customer = {a["customer_id"]: a["sales_rep_id"] for a in seed_data.customer_reps}

    with Session(db_engine) as session:
        for customer_id in sampled_customer_ids:
            customer = session.get(
                Customer,
                customer_id,
                options=[
                    selectinload(Customer.legal_entity),
                    selectinload(Customer.rep_assignments),
                ],
            )
            assert customer is not None
            seeded_customer = seeded_customer_by_id[customer_id]

            # ── Legal entity matches the seed exactly ────────────────────────
            seeded_entity = seeded_entity_by_id[seeded_customer["legal_entity_id"]]
            assert customer.legal_entity.id == seeded_entity["id"]
            assert customer.legal_entity.name == seeded_entity["name"]
            assert customer.legal_entity.tax_id == seeded_entity["tax_id"]

            # ── Sibling objects: exactly the seeded set, nothing invented ────
            orm_sibling_ids = {c.id for c in customer.legal_entity.customers}
            seeded_sibling_ids = {
                c["id"] for c in seed_data.customers if c["legal_entity_id"] == seeded_entity["id"]
            }
            assert orm_sibling_ids == seeded_sibling_ids

            sql_sibling_ids = {
                row[0]
                for row in session.execute(
                    text("SELECT id FROM core.customer WHERE legal_entity_id = :le"),
                    {"le": seeded_entity["id"]},
                )
            }
            assert orm_sibling_ids == sql_sibling_ids

            # ── Last-12-months invoices: ORM == direct SQL (ids, count, sum) ─
            orm_invoices = [
                inv for inv in customer.invoices if twelve_months_ago < inv.date <= as_of
            ]
            orm_ids = sorted(inv.id for inv in orm_invoices)
            orm_total = sum((inv.total for inv in orm_invoices), Decimal("0"))

            sql_rows = session.execute(
                text(
                    "SELECT id, total FROM core.invoice "
                    "WHERE customer_id = :cid AND date > :start AND date <= :end "
                    "ORDER BY id"
                ),
                {"cid": customer_id, "start": twelve_months_ago, "end": as_of},
            ).all()
            sql_ids = [row[0] for row in sql_rows]
            sql_total = sum((row[1] for row in sql_rows), Decimal("0"))

            assert orm_ids == sql_ids, "ORM invoice set differs from SQL"
            assert orm_total == sql_total, "ORM invoice sum differs from SQL (to the cent)"
            assert len(orm_invoices) > 0, "sampled customer has no invoices in the last 12 months"

            # ── Assigned rep matches the seeded assignment ───────────────────
            assert len(customer.rep_assignments) == 1
            assignment = customer.rep_assignments[0]
            assert assignment.sales_rep_id == seeded_rep_by_customer[customer_id]

            sql_rep = session.execute(
                text(
                    "SELECT sales_rep_id FROM core.customer_rep "
                    "WHERE customer_id = :cid ORDER BY from_date DESC LIMIT 1"
                ),
                {"cid": customer_id},
            ).scalar()
            assert assignment.sales_rep_id == sql_rep

            # ── No invented relationships: every FK target exists in the seed ─
            assert customer.legal_entity_id in seeded_entity_by_id
            seeded_article_ids = {a["id"] for a in seed_data.articles}
            seeded_invoice_ids = {i["id"] for i in seed_data.invoices}
            for invoice in orm_invoices:
                assert invoice.id in seeded_invoice_ids
                for line in invoice.lines:
                    assert line.article_id in seeded_article_ids
