"""Mini-fixture builder for per-rule detection tests.

Each rule's labeled cases (true_positive / must_not_fire / low_confidence_borderline)
are expressed as small order scenarios; this builder turns them into a clean core
graph + recomputed metrics so the rule SQL runs against real tables.

Article catalog used by all cases:
  articles 1-3 → category 1 "papir"
  articles 4-6 → category 2 "hemija"
  articles 7-9 → category 3 "dispenzeri"
"""

import datetime
from decimal import Decimal

from sqlalchemy import insert, text
from sqlalchemy.orm import Session

from valeri_api.domain.models import (
    Article,
    ArticleAlias,
    Category,
    Customer,
    CustomerRep,
    Invoice,
    InvoiceLine,
    LegalEntity,
    SalesRep,
)
from valeri_api.metrics.recompute import recompute_all
from valeri_api.seed.loader import reset

AS_OF = datetime.date(2026, 6, 1)

CATEGORIES = [
    {"id": 1, "name": "papir"},
    {"id": 2, "name": "hemija"},
    {"id": 3, "name": "dispenzeri"},
]
ARTICLES = [
    {
        "id": n,
        "category_id": (n - 1) // 3 + 1,
        "code": f"RT-{n:03d}",
        "name": f"Artikal {n}",
        "active": True,
    }
    for n in range(1, 10)
]


def setup_detection_fixture(
    session: Session,
    customers: list[dict],
    aliases: list[dict] | None = None,
    as_of: datetime.date = AS_OF,
) -> None:
    """Build a clean core graph from order scenarios and recompute metrics.

    customers: [{"id": int, "segment": str, "orders": [(days_ago, [(article_id, "amount")])]}]
    aliases:   [{"old_code": "RT-002", "new_article_id": 3}]  (code-swap rows)
    """
    reset(session)

    session.execute(
        insert(LegalEntity),
        [{"id": 1, "name": "Test Grupa d.o.o.", "tax_id": "9980000000001"}],
    )
    session.execute(insert(SalesRep), [{"id": 1, "name": "Rep Test"}])
    session.execute(insert(Category), CATEGORIES)
    session.execute(insert(Article), ARTICLES)

    customer_rows = [
        {
            "id": customer["id"],
            "legal_entity_id": 1,
            "name": f"Kupac {customer['id']}",
            "segment": customer["segment"],
            "status": customer.get("status", "active"),
            "external_code": f"RT-K{customer['id']:03d}",
        }
        for customer in customers
    ]
    session.execute(insert(Customer), customer_rows)
    session.execute(
        insert(CustomerRep),
        [
            {"customer_id": c["id"], "sales_rep_id": 1, "from_date": datetime.date(2024, 1, 1)}
            for c in customers
        ],
    )

    if aliases:
        session.execute(insert(ArticleAlias), aliases)

    invoice_rows: list[dict] = []
    line_rows: list[dict] = []
    invoice_id = 0
    line_id = 0
    for customer in customers:
        for days_ago, lines in customer["orders"]:
            invoice_id += 1
            order_date = as_of - datetime.timedelta(days=days_ago)
            total = sum(Decimal(amount) for _, amount in lines)
            invoice_rows.append(
                {
                    "id": invoice_id,
                    "customer_id": customer["id"],
                    "date": order_date,
                    "total": total,
                    "external_no": f"RT-FK-{invoice_id:05d}",
                }
            )
            for article_id, amount in lines:
                line_id += 1
                line_rows.append(
                    {
                        "id": line_id,
                        "invoice_id": invoice_id,
                        "article_id": article_id,
                        "qty": Decimal("1.000"),
                        "unit_price": Decimal(amount),
                        "line_total": Decimal(amount),
                    }
                )

    if invoice_rows:
        session.execute(insert(Invoice), invoice_rows)
        session.execute(insert(InvoiceLine), line_rows)

    for table in (
        "legal_entity",
        "sales_rep",
        "category",
        "customer",
        "article",
        "invoice",
        "invoice_line",
    ):
        session.execute(
            text(
                f"SELECT setval(pg_get_serial_sequence('core.{table}', 'id'), "
                f"(SELECT COALESCE(MAX(id), 1) FROM core.{table}))"  # noqa: S608
            )
        )

    recompute_all(session, as_of=as_of)
    session.flush()


def monthly_orders(amount: str, months: int, start_days_ago: int, step_days: int = 30) -> list:
    """Helper: N orders of a fixed amount on article 1, every `step_days`, oldest first."""
    return [
        (start_days_ago - month * step_days, [(1, amount)])
        for month in range(months)
        if start_days_ago - month * step_days >= 0
    ]
