"""Golden fixture for the M3 metric layer.

Handcrafted dataset with HAND-COMPUTED expected values. Every number below was
calculated by hand from the invoice literals; the golden tests assert that the
SQL recompute produces exactly these values. If a metric definition changes,
these expectations must be recomputed by hand — never copied from SQL output.

Reference date (fixed): AS_OF = 2026-06-01
  60-day window   : (2026-04-02, 2026-06-01]   ... as_of - 60d  = 2026-04-02
  baseline window : (2025-10-04, 2026-04-02]   ... as_of - 240d = 2025-10-04
  (half-open intervals: the start date is excluded, the end date is included)

Customers:
  C1 Hotel Alfa (hotel)        — full history, boundary invoices on both window edges
  C2 Restoran Beta (restoran)  — two invoices on the SAME day (distinct-date rule)
  C3 Kafić Gama (kafić)        — single old invoice (zero 60d turnover, NULL interval)
  C4 Škola Delta (škola)       — no invoices at all (row must still exist)
  C5 Restoran Epsilon (restoran) — papir only (makes restoran×hemija prevalence 1/2)
"""

import datetime
from decimal import Decimal

from sqlalchemy import insert, text
from sqlalchemy.orm import Session

AS_OF = datetime.date(2026, 6, 1)

D = Decimal
date = datetime.date

LEGAL_ENTITIES = [{"id": 1, "name": "Test Holding d.o.o.", "tax_id": "9990000000001"}]

CUSTOMERS = [
    {"id": 1, "legal_entity_id": 1, "name": "Hotel Alfa", "segment": "hotel", "status": "active", "external_code": "TST-0001"},
    {"id": 2, "legal_entity_id": 1, "name": "Restoran Beta", "segment": "restoran", "status": "active", "external_code": "TST-0002"},
    {"id": 3, "legal_entity_id": 1, "name": "Kafić Gama", "segment": "kafić", "status": "active", "external_code": "TST-0003"},
    {"id": 4, "legal_entity_id": 1, "name": "Škola Delta", "segment": "škola", "status": "active", "external_code": "TST-0004"},
    {"id": 5, "legal_entity_id": 1, "name": "Restoran Epsilon", "segment": "restoran", "status": "active", "external_code": "TST-0005"},
]

SALES_REPS = [{"id": 1, "name": "Test Rep", "email": "rep@example.com"}]

CUSTOMER_REPS = [
    {"customer_id": c["id"], "sales_rep_id": 1, "from_date": date(2025, 1, 1)} for c in CUSTOMERS
]

CATEGORIES = [{"id": 1, "name": "papir"}, {"id": 2, "name": "hemija"}]

ARTICLES = [
    {"id": 1, "category_id": 1, "code": "TST-A1", "name": "Papir A", "active": True},
    {"id": 2, "category_id": 1, "code": "TST-A2", "name": "Papir B", "active": True},
    {"id": 3, "category_id": 2, "code": "TST-A3", "name": "Hemija C", "active": True},
    {"id": 4, "category_id": 2, "code": "TST-A4", "name": "Hemija D", "active": True},
]

# Unit prices: A1 = 10.00, A2 = 20.00, A3 = 5.50, A4 = 100.00.
# Each invoice's total equals the sum of its lines (computed by hand below).

INVOICES = [
    # ── C1 Hotel Alfa ── 60-day window: (2026-04-02, 2026-06-01] ──────────────
    {"id": 1, "customer_id": 1, "date": date(2026, 4, 12), "total": D("210.00"), "external_no": "TST-FK-0001"},
    {"id": 2, "customer_id": 1, "date": date(2026, 5, 12), "total": D("150.00"), "external_no": "TST-FK-0002"},
    # boundary: exactly AS_OF → included in the 60d window
    {"id": 3, "customer_id": 1, "date": date(2026, 6, 1), "total": D("40.00"), "external_no": "TST-FK-0003"},
    # ── C1 baseline window: (2025-10-04, 2026-04-02] ──────────────────────────
    # boundary: exactly as_of-60d → in the BASELINE, not the 60d window
    {"id": 4, "customer_id": 1, "date": date(2026, 4, 2), "total": D("100.00"), "external_no": "TST-FK-0004"},
    {"id": 5, "customer_id": 1, "date": date(2026, 3, 12), "total": D("100.00"), "external_no": "TST-FK-0005"},
    {"id": 6, "customer_id": 1, "date": date(2026, 2, 12), "total": D("200.00"), "external_no": "TST-FK-0006"},
    {"id": 7, "customer_id": 1, "date": date(2026, 1, 12), "total": D("200.00"), "external_no": "TST-FK-0007"},
    {"id": 8, "customer_id": 1, "date": date(2025, 12, 12), "total": D("100.00"), "external_no": "TST-FK-0008"},
    {"id": 9, "customer_id": 1, "date": date(2025, 11, 12), "total": D("500.00"), "external_no": "TST-FK-0009"},
    # boundary: exactly as_of-240d → OUTSIDE both windows (still counts for
    # last_order_date / intervals, which use all history)
    {"id": 10, "customer_id": 1, "date": date(2025, 10, 4), "total": D("990.00"), "external_no": "TST-FK-0010"},
    # ── C2 Restoran Beta ───────────────────────────────────────────────────────
    {"id": 11, "customer_id": 2, "date": date(2026, 5, 15), "total": D("40.00"), "external_no": "TST-FK-0011"},
    # same calendar day as invoice 11 (distinct-date rule for intervals)
    {"id": 12, "customer_id": 2, "date": date(2026, 5, 15), "total": D("22.00"), "external_no": "TST-FK-0012"},
    {"id": 13, "customer_id": 2, "date": date(2026, 4, 15), "total": D("60.00"), "external_no": "TST-FK-0013"},
    {"id": 14, "customer_id": 2, "date": date(2026, 1, 15), "total": D("255.00"), "external_no": "TST-FK-0014"},
    {"id": 15, "customer_id": 2, "date": date(2025, 12, 15), "total": D("40.00"), "external_no": "TST-FK-0015"},
    # ── C3 Kafić Gama: single invoice, in the baseline window ────────────────
    {"id": 16, "customer_id": 3, "date": date(2026, 1, 20), "total": D("10.00"), "external_no": "TST-FK-0016"},
    # ── C5 Restoran Epsilon: single invoice in the 60d window, papir only ────
    {"id": 17, "customer_id": 5, "date": date(2026, 5, 20), "total": D("30.00"), "external_no": "TST-FK-0017"},
]

INVOICE_LINES = [
    # C1 / invoice 1 (2026-04-12): A1 10×10.00 + A3 20×5.50 = 100.00 + 110.00 = 210.00
    {"id": 1, "invoice_id": 1, "article_id": 1, "qty": D("10.000"), "unit_price": D("10.0000"), "line_total": D("100.00")},
    {"id": 2, "invoice_id": 1, "article_id": 3, "qty": D("20.000"), "unit_price": D("5.5000"), "line_total": D("110.00")},
    # C1 / invoice 2 (2026-05-12): A1 15×10.00 = 150.00
    {"id": 3, "invoice_id": 2, "article_id": 1, "qty": D("15.000"), "unit_price": D("10.0000"), "line_total": D("150.00")},
    # C1 / invoice 3 (2026-06-01): A1 4×10.00 = 40.00
    {"id": 4, "invoice_id": 3, "article_id": 1, "qty": D("4.000"), "unit_price": D("10.0000"), "line_total": D("40.00")},
    # C1 / invoice 4 (2026-04-02): A2 5×20.00 = 100.00
    {"id": 5, "invoice_id": 4, "article_id": 2, "qty": D("5.000"), "unit_price": D("20.0000"), "line_total": D("100.00")},
    # C1 / invoice 5 (2026-03-12): A1 10×10.00 = 100.00
    {"id": 6, "invoice_id": 5, "article_id": 1, "qty": D("10.000"), "unit_price": D("10.0000"), "line_total": D("100.00")},
    # C1 / invoice 6 (2026-02-12): A1 20×10.00 = 200.00
    {"id": 7, "invoice_id": 6, "article_id": 1, "qty": D("20.000"), "unit_price": D("10.0000"), "line_total": D("200.00")},
    # C1 / invoice 7 (2026-01-12): A2 10×20.00 = 200.00
    {"id": 8, "invoice_id": 7, "article_id": 2, "qty": D("10.000"), "unit_price": D("20.0000"), "line_total": D("200.00")},
    # C1 / invoice 8 (2025-12-12): A4 1×100.00 = 100.00
    {"id": 9, "invoice_id": 8, "article_id": 4, "qty": D("1.000"), "unit_price": D("100.0000"), "line_total": D("100.00")},
    # C1 / invoice 9 (2025-11-12): A1 50×10.00 = 500.00
    {"id": 10, "invoice_id": 9, "article_id": 1, "qty": D("50.000"), "unit_price": D("10.0000"), "line_total": D("500.00")},
    # C1 / invoice 10 (2025-10-04): A1 99×10.00 = 990.00
    {"id": 11, "invoice_id": 10, "article_id": 1, "qty": D("99.000"), "unit_price": D("10.0000"), "line_total": D("990.00")},
    # C2 / invoice 11 (2026-05-15): A2 2×20.00 = 40.00
    {"id": 12, "invoice_id": 11, "article_id": 2, "qty": D("2.000"), "unit_price": D("20.0000"), "line_total": D("40.00")},
    # C2 / invoice 12 (2026-05-15): A3 4×5.50 = 22.00
    {"id": 13, "invoice_id": 12, "article_id": 3, "qty": D("4.000"), "unit_price": D("5.5000"), "line_total": D("22.00")},
    # C2 / invoice 13 (2026-04-15): A2 3×20.00 = 60.00
    {"id": 14, "invoice_id": 13, "article_id": 2, "qty": D("3.000"), "unit_price": D("20.0000"), "line_total": D("60.00")},
    # C2 / invoice 14 (2026-01-15): A2 10×20.00 + A3 10×5.50 = 200.00 + 55.00 = 255.00
    {"id": 15, "invoice_id": 14, "article_id": 2, "qty": D("10.000"), "unit_price": D("20.0000"), "line_total": D("200.00")},
    {"id": 16, "invoice_id": 14, "article_id": 3, "qty": D("10.000"), "unit_price": D("5.5000"), "line_total": D("55.00")},
    # C2 / invoice 15 (2025-12-15): A2 2×20.00 = 40.00
    {"id": 17, "invoice_id": 15, "article_id": 2, "qty": D("2.000"), "unit_price": D("20.0000"), "line_total": D("40.00")},
    # C3 / invoice 16 (2026-01-20): A1 1×10.00 = 10.00
    {"id": 18, "invoice_id": 16, "article_id": 1, "qty": D("1.000"), "unit_price": D("10.0000"), "line_total": D("10.00")},
    # C5 / invoice 17 (2026-05-20): A1 3×10.00 = 30.00
    {"id": 19, "invoice_id": 17, "article_id": 1, "qty": D("3.000"), "unit_price": D("10.0000"), "line_total": D("30.00")},
]


# ── HAND-COMPUTED EXPECTED VALUES ────────────────────────────────────────────
#
# C1 turnover_60d        = 210 + 150 + 40                       = 400.00
#    (invoice 4 on 2026-04-02 is the boundary → baseline, NOT 60d)
# C1 baseline            = 100 + 100 + 200 + 200 + 100 + 500    = 1200.00 → /3 = 400.00
#    (invoice 10 on 2025-10-04 is the boundary → outside baseline)
# C1 intervals: distinct dates 2025-10-04 … 2026-06-01, gaps
#    39+30+31+31+28+21+10+30+20 = 240 over 9 gaps               = 26.666… → 26.67
#
# C2 turnover_60d        = 40 + 22 + 60                          = 122.00
# C2 baseline            = 255 + 40 = 295.00 → /3                = 98.333… → 98.33
# C2 intervals: distinct dates 2025-12-15, 2026-01-15, 2026-04-15, 2026-05-15
#    gaps 31 + 90 + 30 = 151 over 3                              = 50.333… → 50.33
#
# C3 turnover_60d = 0.00; baseline = 10.00/3                     = 3.33
#    single distinct date → interval NULL
#
# C4 no invoices: turnover 0.00 / 0.00, dates NULL, interval NULL
#
# C5 turnover_60d = 30.00; baseline = 0.00; single date → interval NULL

EXPECTED_CUSTOMER_METRICS = {
    1: {
        "turnover_60d": D("400.00"),
        "turnover_6m_avg_60d": D("400.00"),
        "last_order_date": date(2026, 6, 1),
        "avg_order_interval_d": D("26.67"),
        "segment": "hotel",
    },
    2: {
        "turnover_60d": D("122.00"),
        "turnover_6m_avg_60d": D("98.33"),
        "last_order_date": date(2026, 5, 15),
        "avg_order_interval_d": D("50.33"),
        "segment": "restoran",
    },
    3: {
        "turnover_60d": D("0.00"),
        "turnover_6m_avg_60d": D("3.33"),
        "last_order_date": date(2026, 1, 20),
        "avg_order_interval_d": None,
        "segment": "kafić",
    },
    4: {
        "turnover_60d": D("0.00"),
        "turnover_6m_avg_60d": D("0.00"),
        "last_order_date": None,
        "avg_order_interval_d": None,
        "segment": "škola",
    },
    5: {
        "turnover_60d": D("30.00"),
        "turnover_6m_avg_60d": D("0.00"),
        "last_order_date": date(2026, 5, 20),
        "avg_order_interval_d": None,
        "segment": "restoran",
    },
}

# (customer_id, article_id) → expected cadence row.
#
# C1×A1: purchase dates 2025-10-04, 2025-11-12, 2026-02-12, 2026-03-12,
#        2026-04-12, 2026-05-12, 2026-06-01 → gaps 39+92+28+31+30+20 = 240 / 6 = 40.00
# C1×A2: 2026-01-12, 2026-04-02 → gap 80 / 1                                  = 80.00
# C1×A3: single purchase (2026-04-12)                                          → NULL
# C1×A4: single purchase (2025-12-12)                                          → NULL
# C2×A2: 2025-12-15, 2026-01-15, 2026-04-15, 2026-05-15 → 31+90+30 = 151 / 3  = 50.33
# C2×A3: 2026-01-15, 2026-05-15 → gap 120 / 1                                  = 120.00
# C3×A1: single purchase (2026-01-20)                                          → NULL
# C5×A1: single purchase (2026-05-20)                                          → NULL

EXPECTED_CADENCE = {
    (1, 1): {"avg_interval_d": D("40.00"), "last_seen": date(2026, 6, 1)},
    (1, 2): {"avg_interval_d": D("80.00"), "last_seen": date(2026, 4, 2)},
    (1, 3): {"avg_interval_d": None, "last_seen": date(2026, 4, 12)},
    (1, 4): {"avg_interval_d": None, "last_seen": date(2025, 12, 12)},
    (2, 2): {"avg_interval_d": D("50.33"), "last_seen": date(2026, 5, 15)},
    (2, 3): {"avg_interval_d": D("120.00"), "last_seen": date(2026, 5, 15)},
    (3, 1): {"avg_interval_d": None, "last_seen": date(2026, 1, 20)},
    (5, 1): {"avg_interval_d": None, "last_seen": date(2026, 5, 20)},
}

# (segment, category_id) → prevalence.
#
# Customers with ≥1 invoice: hotel {C1}, restoran {C2, C5}, kafić {C3}; škola none.
# hotel × papir   : C1 bought A1/A2 (papir)            → 1/1 = 1.0000
# hotel × hemija  : C1 bought A3/A4 (hemija)           → 1/1 = 1.0000
# restoran × papir: C2 bought A2, C5 bought A1         → 2/2 = 1.0000
# restoran × hemija: only C2 bought A3                 → 1/2 = 0.5000
# kafić × papir   : C3 bought A1                       → 1/1 = 1.0000
# (kafić × hemija and all škola combinations: prevalence 0 → no row)

EXPECTED_SEGMENT_BASKET = {
    ("hotel", 1): D("1.0000"),
    ("hotel", 2): D("1.0000"),
    ("restoran", 1): D("1.0000"),
    ("restoran", 2): D("0.5000"),
    ("kafić", 1): D("1.0000"),
}

# Total company turnover inside the 60d window (for the semantic-layer test):
# 400.00 (C1) + 122.00 (C2) + 0.00 (C3) + 0.00 (C4) + 30.00 (C5) = 552.00
EXPECTED_TOTAL_TURNOVER_60D = D("552.00")


def load_fixture(session: Session) -> None:
    """Reset core.* and load the golden fixture (explicit IDs)."""
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
    from valeri_api.seed.loader import reset

    reset(session)
    session.execute(insert(LegalEntity), LEGAL_ENTITIES)
    session.execute(insert(SalesRep), SALES_REPS)
    session.execute(insert(Category), CATEGORIES)
    session.execute(insert(Customer), CUSTOMERS)
    session.execute(insert(Article), ARTICLES)
    session.execute(insert(CustomerRep), CUSTOMER_REPS)
    session.execute(insert(Invoice), INVOICES)
    session.execute(insert(InvoiceLine), INVOICE_LINES)
    # Advance sequences past the explicit IDs.
    for table in ("legal_entity", "sales_rep", "category", "customer", "article", "invoice", "invoice_line"):
        session.execute(
            text(
                f"SELECT setval(pg_get_serial_sequence('core.{table}', 'id'), "
                f"(SELECT COALESCE(MAX(id), 1) FROM core.{table}))"  # noqa: S608
            )
        )
    session.flush()
