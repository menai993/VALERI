"""Basket assignment and cadence-based invoice generation over ~18 months."""

import datetime
import random
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from valeri_api.seed.articles import CATEGORY_ORDER
from valeri_api.seed.config import SEGMENT_PROFILES, SeedConfig
from valeri_api.seed.types import BasketItem, CustomerBasket, PlantedPlan

# Narrow-basket customers only ever buy from these categories.
NARROW_CATEGORIES = ("papir", "hemija")


def seasonal_low_months(as_of: datetime.date) -> frozenset[int]:
    """The 4 calendar months ending with as_of's month — the planted 'low season'.

    Defined relative to as_of so the seasonal pattern is always 'currently in
    low season' no matter when the seed is generated, and repeats every year.
    """
    return frozenset(((as_of.month - 1 - i) % 12) + 1 for i in range(4))


def _make_item(
    rng: random.Random, article: dict, prices: dict[int, Decimal], qty_scale: float
) -> BasketItem:
    base_qty = rng.randint(2, 8)
    return BasketItem(
        article_id=article["id"],
        typical_qty=max(2, round(base_qty * qty_scale)),
        inclusion_prob=rng.uniform(0.45, 0.75),
        unit_price=prices[article["id"]],
    )


def build_baskets(
    rng: random.Random,
    config: SeedConfig,
    customers: list[dict],
    articles: list[dict],
    prices: dict[int, Decimal],
    plan: PlantedPlan,
) -> dict[int, CustomerBasket]:
    """Assign every customer a basket (segment-weighted articles) and a cadence."""
    category_name_by_id = {i + 1: name for i, name in enumerate(CATEGORY_ORDER)}
    articles_by_category: dict[str, list[dict]] = defaultdict(list)
    for article in articles:
        articles_by_category[category_name_by_id[article["category_id"]]].append(article)

    narrow_set = set(plan.narrow_baskets)
    seasonal_set = set(plan.seasonal_cafes)
    baskets: dict[int, CustomerBasket] = {}

    for customer in customers:
        profile = SEGMENT_PROFILES[customer["segment"]]
        customer_id = customer["id"]

        if customer_id in narrow_set:
            category_names = [name for name in NARROW_CATEGORIES if name in profile.categories]
            basket_size = rng.randint(4, 6)
        else:
            category_names = list(profile.categories)
            basket_size = rng.randint(*profile.basket_size)

        # At least one article per category (full coverage), then fill randomly.
        items: list[BasketItem] = []
        chosen_ids: set[int] = set()
        for name in category_names:
            article = rng.choice(articles_by_category[name])
            if article["id"] not in chosen_ids:
                chosen_ids.add(article["id"])
                items.append(_make_item(rng, article, prices, profile.qty_scale))

        pool = [
            article
            for name in category_names
            for article in articles_by_category[name]
            if article["id"] not in chosen_ids
        ]
        n_fill = max(0, basket_size - len(items))
        for article in rng.sample(pool, min(n_fill, len(pool))):
            chosen_ids.add(article["id"])
            items.append(_make_item(rng, article, prices, profile.qty_scale))

        items.sort(key=lambda item: item.article_id)

        if customer_id in seasonal_set:
            cadence = config.seasonal_cadence_days
        else:
            cadence = rng.randint(*profile.cadence_days)

        baskets[customer_id] = CustomerBasket(
            customer_id=customer_id, items=items, cadence_days=cadence
        )

    return baskets


def generate_invoices(
    rng: random.Random,
    config: SeedConfig,
    customers: list[dict],
    baskets: dict[int, CustomerBasket],
    plan: PlantedPlan,
) -> tuple[list[dict], list[dict]]:
    """Walk each customer's cadence over the history window and emit invoices+lines.

    Consults the planted plan: decline dampening, seasonal yearly pattern,
    lost-article cutoff, code swaps, sleeping cutoff. Invoice totals always
    equal the sum of their lines, to the cent.
    """
    as_of = config.as_of
    start = as_of - datetime.timedelta(days=config.history_days)
    low_months = seasonal_low_months(as_of)

    decline_set = set(plan.declines)
    seasonal_set = set(plan.seasonal_cafes)
    sleeping_set = set(plan.sleeping)
    swap_by_old = {swap.old_article_id: swap for swap in plan.code_swaps}

    decline_start = as_of - datetime.timedelta(days=config.decline_window_days)
    lost_cutoff = as_of - datetime.timedelta(days=config.lost_article_gap_days)
    sleeping_cutoff = as_of - datetime.timedelta(days=config.sleeping_gap_days)

    # Generated per customer first, then re-numbered in chronological order.
    raw_invoices: list[dict] = []
    raw_lines_by_invoice: list[list[dict]] = []

    for customer in customers:
        customer_id = customer["id"]
        basket = baskets[customer_id]
        lost_article_id = plan.lost_articles.get(customer_id)

        current = start + datetime.timedelta(days=rng.randint(0, basket.cadence_days))
        while current <= as_of:
            if customer_id in sleeping_set and current > sleeping_cutoff:
                break

            qty_factor = 1.0
            if customer_id in seasonal_set and current.month in low_months:
                qty_factor *= config.seasonal_low_factor
            if customer_id in decline_set and current > decline_start:
                qty_factor *= config.decline_qty_factor

            lines: list[dict] = []
            for item in basket.items:
                article_id = item.article_id
                if article_id == lost_article_id and current > lost_cutoff:
                    continue
                swap = swap_by_old.get(article_id)
                if swap is not None and current > swap.swap_date:
                    article_id = swap.new_article_id

                if rng.random() >= item.inclusion_prob:
                    continue

                qty_value = max(1, round(item.typical_qty * qty_factor * rng.uniform(0.7, 1.3)))
                qty = Decimal(qty_value)
                line_total = (qty * item.unit_price).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
                lines.append(
                    {
                        "article_id": article_id,
                        "qty": qty.quantize(Decimal("0.001")),
                        "unit_price": item.unit_price,
                        "line_total": line_total,
                    }
                )

            if lines:
                total = sum((line["line_total"] for line in lines), Decimal("0"))
                raw_invoices.append({"customer_id": customer_id, "date": current, "total": total})
                raw_lines_by_invoice.append(lines)

            current += datetime.timedelta(days=basket.cadence_days + rng.randint(-3, 3))

    # Re-number chronologically so IDs resemble a real ERP sequence.
    order = sorted(
        range(len(raw_invoices)),
        key=lambda idx: (raw_invoices[idx]["date"], raw_invoices[idx]["customer_id"]),
    )

    invoices: list[dict] = []
    invoice_lines: list[dict] = []
    line_id = 0
    for invoice_id, idx in enumerate(order, start=1):
        invoice = raw_invoices[idx]
        invoices.append(
            {
                "id": invoice_id,
                "customer_id": invoice["customer_id"],
                "date": invoice["date"],
                "total": invoice["total"],
                # Source-ERP invoice number (broj fakture) — the natural key
                # the M2 import matches on.
                "external_no": f"FK-{invoice['date'].year}-{invoice_id:06d}",
            }
        )
        for line in raw_lines_by_invoice[idx]:
            line_id += 1
            invoice_lines.append(
                {
                    "id": line_id,
                    "invoice_id": invoice_id,
                    "article_id": line["article_id"],
                    "qty": line["qty"],
                    "unit_price": line["unit_price"],
                    "line_total": line["line_total"],
                }
            )

    return invoices, invoice_lines
