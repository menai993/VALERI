"""Category, article, and code-swap generation."""

import datetime
import random
from collections import defaultdict
from decimal import Decimal

from valeri_api.seed.config import SeedConfig
from valeri_api.seed.names import ARTICLE_NAMES
from valeri_api.seed.types import CodeSwap, CustomerBasket, PlantedPlan

# Unit price ranges per category in KM (min, max).
PRICE_RANGES: dict[str, tuple[int, int]] = {
    "papir": (3, 45),
    "hemija": (4, 60),
    "dispenzeri": (25, 180),
    "rukavice": (8, 35),
    "kozmetika": (5, 40),
    "tekstil": (10, 80),
    "oprema": (30, 400),
}

CATEGORY_ORDER = ["papir", "hemija", "dispenzeri", "rukavice", "kozmetika", "tekstil", "oprema"]


def generate_categories() -> list[dict]:
    """The 7 fixed categories, IDs 1..7."""
    return [{"id": i + 1, "name": name} for i, name in enumerate(CATEGORY_ORDER)]


def generate_articles(
    rng: random.Random, categories: list[dict]
) -> tuple[list[dict], dict[int, Decimal]]:
    """All articles with stable codes and a deterministic base price per article."""
    category_id_by_name = {c["name"]: c["id"] for c in categories}
    articles: list[dict] = []
    prices: dict[int, Decimal] = {}

    article_id = 0
    for category_name in CATEGORY_ORDER:
        low, high = PRICE_RANGES[category_name]
        for article_name in ARTICLE_NAMES[category_name]:
            article_id += 1
            articles.append(
                {
                    "id": article_id,
                    "category_id": category_id_by_name[category_name],
                    "code": f"ART-{article_id:04d}",
                    "name": article_name,
                    "active": True,
                }
            )
            # Price with .x0 cents so totals stay tidy but non-trivial.
            price = Decimal(rng.randint(low * 10, high * 10)) / Decimal(10)
            prices[article_id] = price.quantize(Decimal("0.0001"))

    return articles, prices


def select_code_swaps(
    rng: random.Random,
    config: SeedConfig,
    articles: list[dict],
    prices: dict[int, Decimal],
    baskets: dict[int, CustomerBasket],
    plan: PlantedPlan,
) -> tuple[list[dict], list[dict]]:
    """Plant the code swaps: old article retired, new article + alias created.

    Picks articles bought by at least two non-planted customers so the
    "purchases continue under the new code" pattern is clearly visible.
    Returns (new_article_rows, alias_rows) and fills plan.code_swaps.
    """
    planted_customers = set(
        plan.declines + plan.seasonal_cafes + plan.sleeping + plan.narrow_baskets + plan.lost_hosts
    )

    buyers_by_article: dict[int, list[int]] = defaultdict(list)
    for customer_id in sorted(baskets):
        if customer_id in planted_customers:
            continue
        for item in baskets[customer_id].items:
            buyers_by_article[item.article_id].append(customer_id)

    candidates = sorted(aid for aid, buyers in buyers_by_article.items() if len(buyers) >= 2)
    chosen = sorted(rng.sample(candidates, config.n_code_swaps))

    article_by_id = {a["id"]: a for a in articles}
    swap_date = config.as_of - datetime.timedelta(days=config.code_swap_days_before)
    mapped_at = datetime.datetime.combine(swap_date, datetime.time(8, 0), tzinfo=datetime.UTC)

    new_articles: list[dict] = []
    aliases: list[dict] = []
    next_id = max(article_by_id) + 1

    for old_id in chosen:
        old = article_by_id[old_id]
        new_id = next_id
        next_id += 1
        new_code = f"ART-{new_id:04d}"

        new_articles.append(
            {
                "id": new_id,
                "category_id": old["category_id"],
                "code": new_code,
                "name": old["name"],
                "active": True,
            }
        )
        old["active"] = False  # the old code is retired in the catalog
        prices[new_id] = prices[old_id]

        aliases.append({"old_code": old["code"], "new_article_id": new_id, "mapped_at": mapped_at})
        plan.code_swaps.append(
            CodeSwap(
                old_article_id=old_id,
                old_code=old["code"],
                new_article_id=new_id,
                new_code=new_code,
                swap_date=swap_date,
                customer_ids=sorted(buyers_by_article[old_id]),
            )
        )

    return new_articles, aliases
