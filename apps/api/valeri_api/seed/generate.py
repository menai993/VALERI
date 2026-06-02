"""Seed orchestrator: wires the generation modules together in a fixed order."""

import random

from valeri_api.seed.articles import generate_articles, generate_categories, select_code_swaps
from valeri_api.seed.config import SeedConfig
from valeri_api.seed.entities import generate_contacts, generate_entities, generate_reps
from valeri_api.seed.invoices import build_baskets, generate_invoices
from valeri_api.seed.planted import (
    build_manifest,
    select_lost_articles,
    select_planted_customers,
)
from valeri_api.seed.types import SeedData


def generate(config: SeedConfig) -> SeedData:
    """Generate the full synthetic dataset, deterministically for a given config."""
    rng = random.Random(config.rng_seed)

    # 1. Catalog.
    categories = generate_categories()
    articles, prices = generate_articles(rng, categories)

    # 2. Business graph.
    legal_entities, customers = generate_entities(rng, config)
    contacts = generate_contacts(rng, customers)
    rep_from_date = config.as_of.replace(day=1).replace(
        year=config.as_of.year - 2
    )  # reps assigned well before the history window
    sales_reps, customer_reps = generate_reps(rng, config, customers, rep_from_date)

    # 3. Planted plan → baskets → code swaps → lost articles.
    plan = select_planted_customers(rng, config, customers)
    baskets = build_baskets(rng, config, customers, articles, prices, plan)
    new_articles, article_aliases = select_code_swaps(rng, config, articles, prices, baskets, plan)
    articles = articles + new_articles
    select_lost_articles(rng, plan, baskets)

    # 4. Invoices.
    invoices, invoice_lines = generate_invoices(rng, config, customers, baskets, plan)

    # 5. Ground-truth manifest (measured from the generated data).
    manifest = build_manifest(config, plan, customers, invoices, invoice_lines)

    return SeedData(
        legal_entities=legal_entities,
        customers=customers,
        contacts=contacts,
        sales_reps=sales_reps,
        customer_reps=customer_reps,
        categories=categories,
        articles=articles,
        article_aliases=article_aliases,
        invoices=invoices,
        invoice_lines=invoice_lines,
        manifest=manifest,
    )
