"""Shared data structures passed between the seed generation modules."""

import datetime
from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class BasketItem:
    """One article a customer buys regularly."""

    article_id: int
    typical_qty: int
    inclusion_prob: float
    unit_price: Decimal


@dataclass
class CustomerBasket:
    """What and how often a customer orders."""

    customer_id: int
    items: list[BasketItem]
    cadence_days: int


@dataclass
class CodeSwap:
    """An article whose code changed; purchases continue under the new article."""

    old_article_id: int
    old_code: str
    new_article_id: int
    new_code: str
    swap_date: datetime.date
    customer_ids: list[int]  # normal customers who keep buying under the new code


@dataclass
class PlantedPlan:
    """Which customers/articles carry which planted pattern. All sets are disjoint."""

    declines: list[int] = field(default_factory=list)
    seasonal_cafes: list[int] = field(default_factory=list)
    sleeping: list[int] = field(default_factory=list)
    narrow_baskets: list[int] = field(default_factory=list)
    lost_hosts: list[int] = field(default_factory=list)
    lost_articles: dict[int, int] = field(default_factory=dict)  # customer_id -> article_id
    code_swaps: list[CodeSwap] = field(default_factory=list)


@dataclass
class SeedData:
    """Everything the seed generates: one list of row-dicts per table + the manifest."""

    legal_entities: list[dict]
    customers: list[dict]
    contacts: list[dict]
    sales_reps: list[dict]
    customer_reps: list[dict]
    categories: list[dict]
    articles: list[dict]
    article_aliases: list[dict]
    invoices: list[dict]
    invoice_lines: list[dict]
    manifest: dict
    # M8: application logins (app.app_user) — owner/admin/finance + one per rep.
    app_users: list[dict] = field(default_factory=list)
    # C-CRM1: demo opportunities + their initial stage history (Phase-2 CRM).
    opportunities: list[dict] = field(default_factory=list)
    opportunity_stage_history: list[dict] = field(default_factory=list)
    # C-CRM2: demo rep activities + the company monthly revenue plan.
    activities: list[dict] = field(default_factory=list)
    revenue_targets: list[dict] = field(default_factory=list)
    # CI2: confirmed KB relationships for the graph-aware rules (demo only; see config).
    client_relationships: list[dict] = field(default_factory=list)
