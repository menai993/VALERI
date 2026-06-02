"""Planted-case selection and the ground-truth manifest.

The planted cases shape invoice generation (they are not post-processed),
and the manifest records MEASURED values from the generated data so that
M3/M4 tests verify reality, not intent.
"""

import datetime
import random
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from valeri_api.seed.config import SeedConfig
from valeri_api.seed.types import CustomerBasket, PlantedPlan

# Segments eligible per planted case (chosen so the patterns are measurable:
# fast-cadence segments for declines/lost articles, wide-basket segments for
# narrow-basket peers, kafić for seasonality).
DECLINE_SEGMENTS = ("hotel", "restoran")
SEASONAL_SEGMENTS = ("kafić",)
SLEEPING_SEGMENTS = ("restoran", "klinika")
NARROW_SEGMENTS = ("hotel", "restoran", "klinika")
LOST_HOST_SEGMENTS = ("hotel", "restoran", "klinika")


def select_planted_customers(
    rng: random.Random, config: SeedConfig, customers: list[dict]
) -> PlantedPlan:
    """Pick which customers carry which planted pattern. All sets are disjoint."""
    by_segment: dict[str, list[int]] = defaultdict(list)
    for customer in customers:
        by_segment[customer["segment"]].append(customer["id"])

    used: set[int] = set()

    def pick(segments: tuple[str, ...], count: int) -> list[int]:
        pool = sorted(cid for seg in segments for cid in by_segment[seg] if cid not in used)
        chosen = sorted(rng.sample(pool, count))
        used.update(chosen)
        return chosen

    return PlantedPlan(
        declines=pick(DECLINE_SEGMENTS, config.n_declines),
        seasonal_cafes=pick(SEASONAL_SEGMENTS, config.n_seasonal_cafes),
        sleeping=pick(SLEEPING_SEGMENTS, config.n_sleeping),
        narrow_baskets=pick(NARROW_SEGMENTS, config.n_narrow_baskets),
        lost_hosts=pick(LOST_HOST_SEGMENTS, config.n_lost_articles),
    )


def select_lost_articles(
    rng: random.Random, plan: PlantedPlan, baskets: dict[int, CustomerBasket]
) -> None:
    """For each lost-article host, pick one regularly-bought article that will disappear.

    The chosen item gets a high inclusion probability so its pre-loss cadence
    is clearly regular. Code-swapped articles are excluded.
    """
    swapped_old_ids = {swap.old_article_id for swap in plan.code_swaps}

    for customer_id in plan.lost_hosts:
        basket = baskets[customer_id]
        candidates = [item for item in basket.items if item.article_id not in swapped_old_ids]
        item = rng.choice(candidates)
        item.inclusion_prob = 0.9  # regular, frequent purchases before the loss
        plan.lost_articles[customer_id] = item.article_id


# ── manifest ─────────────────────────────────────────────────────────────────


def _money(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def build_manifest(
    config: SeedConfig,
    plan: PlantedPlan,
    customers: list[dict],
    invoices: list[dict],
    invoice_lines: list[dict],
) -> dict:
    """Record measured values for every planted case (the ground truth for M3/M4)."""
    as_of = config.as_of
    days = datetime.timedelta
    customer_by_id = {c["id"]: c for c in customers}
    invoice_by_id = {i["id"]: i for i in invoices}

    invoices_by_customer: dict[int, list[dict]] = defaultdict(list)
    for invoice in invoices:
        invoices_by_customer[invoice["customer_id"]].append(invoice)

    def turnover(customer_id: int, start: datetime.date, end: datetime.date) -> Decimal:
        return sum(
            (
                inv["total"]
                for inv in invoices_by_customer[customer_id]
                if start < inv["date"] <= end
            ),
            Decimal("0"),
        )

    def purchase_dates(customer_id: int, article_id: int) -> list[datetime.date]:
        dates = {
            invoice_by_id[line["invoice_id"]]["date"]
            for line in invoice_lines
            if line["article_id"] == article_id
            and invoice_by_id[line["invoice_id"]]["customer_id"] == customer_id
        }
        return sorted(dates)

    manifest: dict = {
        "rng_seed": config.rng_seed,
        "as_of": as_of.isoformat(),
        "declines": [],
        "seasonal_cafes": [],
        "lost_articles": [],
        "code_swaps": [],
        "narrow_baskets": [],
        "sleeping": [],
    }

    for customer_id in plan.declines:
        last_60 = turnover(customer_id, as_of - days(60), as_of)
        baseline = turnover(customer_id, as_of - days(240), as_of - days(60)) / 3
        manifest["declines"].append(
            {
                "customer_id": customer_id,
                "external_code": customer_by_id[customer_id]["external_code"],
                "baseline_60d": _money(baseline),
                "last_60d": _money(last_60),
            }
        )

    for customer_id in plan.seasonal_cafes:
        last_60 = turnover(customer_id, as_of - days(60), as_of)
        same_window_last_year = turnover(customer_id, as_of - days(425), as_of - days(365))
        manifest["seasonal_cafes"].append(
            {
                "customer_id": customer_id,
                "external_code": customer_by_id[customer_id]["external_code"],
                "last_60d": _money(last_60),
                "same_window_last_year": _money(same_window_last_year),
            }
        )

    for customer_id in sorted(plan.lost_articles):
        article_id = plan.lost_articles[customer_id]
        dates = purchase_dates(customer_id, article_id)
        gaps = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
        cadence = sum(gaps) / len(gaps)
        manifest["lost_articles"].append(
            {
                "customer_id": customer_id,
                "article_id": article_id,
                "last_seen": dates[-1].isoformat(),
                "cadence_days": round(cadence, 1),
                "purchases_before_loss": len(dates),
            }
        )

    for swap in plan.code_swaps:
        manifest["code_swaps"].append(
            {
                "old_code": swap.old_code,
                "old_article_id": swap.old_article_id,
                "new_article_id": swap.new_article_id,
                "new_code": swap.new_code,
                "swap_date": swap.swap_date.isoformat(),
                "customer_ids": swap.customer_ids,
            }
        )

    for customer_id in plan.narrow_baskets:
        manifest["narrow_baskets"].append(
            {
                "customer_id": customer_id,
                "external_code": customer_by_id[customer_id]["external_code"],
                "segment": customer_by_id[customer_id]["segment"],
            }
        )

    for customer_id in plan.sleeping:
        dates = sorted(inv["date"] for inv in invoices_by_customer[customer_id])
        gaps = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
        manifest["sleeping"].append(
            {
                "customer_id": customer_id,
                "external_code": customer_by_id[customer_id]["external_code"],
                "last_order": dates[-1].isoformat(),
                "avg_interval_days": round(sum(gaps) / len(gaps), 1),
                "invoice_count": len(dates),
            }
        )

    return manifest
