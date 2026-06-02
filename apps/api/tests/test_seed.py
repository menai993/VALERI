"""Seed integrity, planted-case, and determinism tests (M1).

The seed is the ground truth for every later milestone (metrics M3, rules M4),
so these tests verify — with direct SQL against the loaded data — that every
planted case actually exhibits the pattern it claims to plant.
"""

import datetime

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

TEST_RNG_SEED = 20260601


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def seed_data():
    """Generate the seed once, in memory, with fixed parameters."""
    from valeri_api.seed.config import SeedConfig
    from valeri_api.seed.generate import generate

    config = SeedConfig(rng_seed=TEST_RNG_SEED, as_of=datetime.date.today())
    return generate(config)


@pytest.fixture(scope="session")
def seeded_db(db_engine: Engine, seed_data) -> Engine:
    """Load the generated seed into the test database (once per session)."""
    from valeri_api.seed.loader import load, reset

    with Session(db_engine) as session:
        reset(session)
        load(seed_data, session)
        session.commit()
    return db_engine


# ── helpers ──────────────────────────────────────────────────────────────────


def _turnover(conn, customer_id: int, start: datetime.date, end: datetime.date) -> float:
    """Customer turnover in (start, end] — direct SQL, the source of truth."""
    value = conn.execute(
        text(
            "SELECT COALESCE(SUM(total), 0) FROM core.invoice "
            "WHERE customer_id = :cid AND date > :start AND date <= :end"
        ),
        {"cid": customer_id, "start": start, "end": end},
    ).scalar()
    return float(value)


def _window_vs_baseline(conn, customer_id: int, as_of: datetime.date) -> float:
    """Last-60-days turnover vs the preceding 6-month baseline (normalised to 60d)."""
    days = datetime.timedelta
    last_60 = _turnover(conn, customer_id, as_of - days(60), as_of)
    baseline_total = _turnover(conn, customer_id, as_of - days(240), as_of - days(60))
    assert baseline_total > 0, f"customer {customer_id} has no baseline turnover"
    return last_60 / (baseline_total / 3)


def _year_over_year(conn, customer_id: int, as_of: datetime.date) -> float:
    """Last-60-days turnover vs the same 60-day window one year earlier."""
    days = datetime.timedelta
    current = _turnover(conn, customer_id, as_of - days(60), as_of)
    last_year = _turnover(conn, customer_id, as_of - days(425), as_of - days(365))
    assert last_year > 0, f"customer {customer_id} has no turnover in last year's window"
    return current / last_year


# ── tests ────────────────────────────────────────────────────────────────────


def test_seed_volumes(seeded_db: Engine, seed_data) -> None:
    """Volumes match the spec: ~80 customers, ~120 articles, 7 categories, 4 reps,
    5 multi-object legal entities, ≥17 months of invoices."""
    with seeded_db.connect() as conn:
        counts = {
            table: conn.execute(text(f"SELECT COUNT(*) FROM core.{table}")).scalar()  # noqa: S608
            for table in (
                "legal_entity",
                "customer",
                "contact",
                "sales_rep",
                "category",
                "article",
                "invoice",
                "invoice_line",
            )
        }
        assert 75 <= counts["customer"] <= 85, counts
        assert 115 <= counts["article"] <= 125, counts
        assert counts["category"] == 7
        assert counts["sales_rep"] == 4
        assert counts["contact"] >= counts["customer"]
        assert counts["invoice"] > 1000
        assert counts["invoice_line"] > 5000

        # Exactly 5 hotel groups with 2-3 objects each.
        multi_object = conn.execute(
            text(
                "SELECT COUNT(*) FROM (SELECT legal_entity_id FROM core.customer "
                "GROUP BY legal_entity_id HAVING COUNT(*) BETWEEN 2 AND 3) AS multi"
            )
        ).scalar()
        assert multi_object == 5

        # Invoice history spans at least 17 months.
        min_date, max_date = conn.execute(
            text("SELECT MIN(date), MAX(date) FROM core.invoice")
        ).one()
        assert (max_date - min_date).days >= 510

        # All five segments are present.
        segments = {
            row[0]
            for row in conn.execute(
                text("SELECT DISTINCT segment FROM core.customer WHERE segment IS NOT NULL")
            )
        }
        assert segments == {"hotel", "restoran", "kafić", "klinika", "škola"}


def test_invoice_totals_match_lines(seeded_db: Engine) -> None:
    """Every invoice total equals the sum of its line totals, to the cent (SQL check)."""
    with seeded_db.connect() as conn:
        mismatches = conn.execute(
            text(
                "SELECT i.id, i.total, COALESCE(SUM(l.line_total), 0) AS line_sum "
                "FROM core.invoice i "
                "LEFT JOIN core.invoice_line l ON l.invoice_id = i.id "
                "GROUP BY i.id, i.total "
                "HAVING i.total <> COALESCE(SUM(l.line_total), 0)"
            )
        ).all()
        assert mismatches == [], f"{len(mismatches)} invoices whose total != sum(lines)"


def test_every_customer_has_current_rep(seeded_db: Engine) -> None:
    """Every customer has exactly one effective rep assignment."""
    with seeded_db.connect() as conn:
        without_rep = conn.execute(
            text(
                "SELECT c.id FROM core.customer c "
                "LEFT JOIN core.customer_rep cr ON cr.customer_id = c.id "
                "WHERE cr.customer_id IS NULL"
            )
        ).all()
        assert without_rep == []

        multiple = conn.execute(
            text(
                "SELECT customer_id FROM core.customer_rep "
                "GROUP BY customer_id HAVING COUNT(*) > 1"
            )
        ).all()
        assert multiple == []


def test_planted_cases_match_manifest(seeded_db: Engine, seed_data) -> None:
    """Each planted case verifiably exhibits its pattern in the loaded data."""
    manifest = seed_data.manifest
    as_of = datetime.date.fromisoformat(manifest["as_of"])

    assert len(manifest["declines"]) == 3
    assert len(manifest["seasonal_cafes"]) == 2
    assert len(manifest["lost_articles"]) == 4
    assert len(manifest["code_swaps"]) == 2
    assert len(manifest["narrow_baskets"]) == 3
    assert len(manifest["sleeping"]) == 3

    with seeded_db.connect() as conn:
        # 1. Real declines: low vs baseline AND low vs same window last year.
        for case in manifest["declines"]:
            cid = case["customer_id"]
            ratio = _window_vs_baseline(conn, cid, as_of)
            yoy = _year_over_year(conn, cid, as_of)
            assert 0.30 <= ratio <= 0.65, f"decline {cid}: baseline ratio {ratio:.2f}"
            assert yoy <= 0.70, f"decline {cid}: yoy ratio {yoy:.2f} (should be a real drop)"

        # 2. Seasonal cafés: look declining vs baseline, but normal vs last year.
        for case in manifest["seasonal_cafes"]:
            cid = case["customer_id"]
            ratio = _window_vs_baseline(conn, cid, as_of)
            yoy = _year_over_year(conn, cid, as_of)
            assert ratio <= 0.75, f"seasonal café {cid}: baseline ratio {ratio:.2f}"
            assert (
                0.70 <= yoy <= 1.40
            ), f"seasonal café {cid}: yoy ratio {yoy:.2f} (should be normal)"

        # 3. Lost articles: regular cadence, then a gap ≥ 3× cadence, customer still active.
        for case in manifest["lost_articles"]:
            cid, aid = case["customer_id"], case["article_id"]
            last_seen = conn.execute(
                text(
                    "SELECT MAX(i.date) FROM core.invoice i "
                    "JOIN core.invoice_line l ON l.invoice_id = i.id "
                    "WHERE i.customer_id = :cid AND l.article_id = :aid"
                ),
                {"cid": cid, "aid": aid},
            ).scalar()
            assert last_seen is not None
            gap_days = (as_of - last_seen).days
            assert (
                gap_days >= 3 * case["cadence_days"]
            ), f"lost article {cid}/{aid}: gap {gap_days}d"

            # The customer kept ordering other things after losing this article.
            invoices_after = conn.execute(
                text(
                    "SELECT COUNT(*) FROM core.invoice "
                    "WHERE customer_id = :cid AND date > :last_seen"
                ),
                {"cid": cid, "last_seen": last_seen},
            ).scalar()
            assert invoices_after >= 3, f"lost article {cid}/{aid}: customer not active after"

        # 4. Code swaps: alias exists, old article inactive and quiet, new article took over.
        for case in manifest["code_swaps"]:
            old_code = case["old_code"]
            new_id = case["new_article_id"]
            alias_row = conn.execute(
                text("SELECT new_article_id FROM core.article_alias WHERE old_code = :oc"),
                {"oc": old_code},
            ).scalar()
            assert alias_row == new_id

            old_active, old_id = conn.execute(
                text("SELECT active, id FROM core.article WHERE code = :oc"), {"oc": old_code}
            ).one()
            assert old_active is False

            swap_date = datetime.date.fromisoformat(case["swap_date"])
            old_lines_after = conn.execute(
                text(
                    "SELECT COUNT(*) FROM core.invoice_line l "
                    "JOIN core.invoice i ON i.id = l.invoice_id "
                    "WHERE l.article_id = :aid AND i.date > :swap"
                ),
                {"aid": old_id, "swap": swap_date},
            ).scalar()
            assert old_lines_after == 0, f"old article {old_code} still sold after swap"

            for cid in case["customer_ids"]:
                new_lines = conn.execute(
                    text(
                        "SELECT COUNT(*) FROM core.invoice_line l "
                        "JOIN core.invoice i ON i.id = l.invoice_id "
                        "WHERE l.article_id = :aid AND i.customer_id = :cid AND i.date > :swap"
                    ),
                    {"aid": new_id, "cid": cid, "swap": swap_date},
                ).scalar()
                assert new_lines > 0, f"customer {cid} did not continue buying under new code"

        # 5. Narrow baskets: ≤2 categories while segment peers typically buy ≥4.
        for case in manifest["narrow_baskets"]:
            cid = case["customer_id"]
            n_categories = conn.execute(
                text(
                    "SELECT COUNT(DISTINCT a.category_id) FROM core.invoice_line l "
                    "JOIN core.invoice i ON i.id = l.invoice_id "
                    "JOIN core.article a ON a.id = l.article_id "
                    "WHERE i.customer_id = :cid"
                ),
                {"cid": cid},
            ).scalar()
            assert n_categories <= 2, f"narrow basket {cid}: buys {n_categories} categories"

            segment = conn.execute(
                text("SELECT segment FROM core.customer WHERE id = :cid"), {"cid": cid}
            ).scalar()
            peer_avg = conn.execute(
                text(
                    "SELECT AVG(cat_count) FROM ("
                    "  SELECT i.customer_id, COUNT(DISTINCT a.category_id) AS cat_count "
                    "  FROM core.invoice_line l "
                    "  JOIN core.invoice i ON i.id = l.invoice_id "
                    "  JOIN core.article a ON a.id = l.article_id "
                    "  JOIN core.customer c ON c.id = i.customer_id "
                    "  WHERE c.segment = :seg AND i.customer_id <> :cid "
                    "  GROUP BY i.customer_id) AS peers"
                ),
                {"seg": segment, "cid": cid},
            ).scalar()
            assert float(peer_avg) >= 4.0, f"narrow basket {cid}: peers only buy {peer_avg}"

        # 6. Sleeping customers: long gap, regular history before, still active.
        for case in manifest["sleeping"]:
            cid = case["customer_id"]
            last_order, n_invoices = conn.execute(
                text("SELECT MAX(date), COUNT(*) FROM core.invoice WHERE customer_id = :cid"),
                {"cid": cid},
            ).one()
            gap = (as_of - last_order).days
            assert gap >= 75, f"sleeping {cid}: gap only {gap}d"
            assert gap >= 3 * case["avg_interval_days"], f"sleeping {cid}: gap {gap}d too short"
            assert n_invoices >= 12, f"sleeping {cid}: only {n_invoices} historic invoices"

            status = conn.execute(
                text("SELECT status FROM core.customer WHERE id = :cid"), {"cid": cid}
            ).scalar()
            assert status == "active"


def test_seed_deterministic(seed_data) -> None:
    """Generating twice with the same (rng_seed, as_of) yields identical output."""
    from valeri_api.seed.config import SeedConfig
    from valeri_api.seed.generate import generate

    config = SeedConfig(
        rng_seed=TEST_RNG_SEED, as_of=datetime.date.fromisoformat(seed_data.manifest["as_of"])
    )
    second = generate(config)

    assert seed_data.manifest == second.manifest
    for table in (
        "legal_entities",
        "customers",
        "contacts",
        "sales_reps",
        "customer_reps",
        "categories",
        "articles",
        "article_aliases",
        "invoices",
        "invoice_lines",
    ):
        first_rows = getattr(seed_data, table)
        second_rows = getattr(second, table)
        assert first_rows == second_rows, f"{table} differs between runs"
