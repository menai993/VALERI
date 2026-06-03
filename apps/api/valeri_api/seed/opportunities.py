"""Demo opportunities for the Phase-2 CRM seed (C-CRM1).

A dozen opportunities spread across all stages, linked to seeded customers + their
reps, each with an initial stage_history row. Deterministic (driven by the seed RNG)
so the Prilike screen, the dashboard block, and the tests all see stable data.
"""

import datetime
from decimal import Decimal
from random import Random

# (stage, value, optional explicit probability) templates — spread across the pipeline.
_TEMPLATES = [
    ("lead", "3200.00", None),
    ("lead", "1500.00", None),
    ("qualified", "8400.00", None),
    ("qualified", "5600.00", "0.4000"),
    ("proposal", "12000.00", None),
    ("proposal", "7300.00", None),
    ("negotiation", "21000.00", "0.8000"),
    ("negotiation", "9800.00", None),
    ("won", "15400.00", None),
    ("won", "6200.00", None),
    ("lost", "4100.00", None),
    ("lost", "11200.00", None),
]

_SOURCES = ["referral", "inbound", "outbound", "event"]
_TITLES = [
    "Godišnji ugovor — higijena",
    "Proširenje na dispenzere",
    "Nova lokacija — papir + hemija",
    "Sezonska narudžba — kozmetika",
    "Win-back ponuda",
    "Okvirni ugovor — rukavice",
]


def generate_opportunities(
    rng: Random,
    customers: list[dict],
    customer_reps: list[dict],
    as_of: datetime.date,
) -> tuple[list[dict], list[dict]]:
    """Return (opportunities, stage_history) row-dicts with explicit ids."""
    # Map each customer to its (latest) rep, for owner_rep_id.
    rep_by_customer: dict[int, int] = {}
    for assignment in sorted(customer_reps, key=lambda a: a["from_date"]):
        rep_by_customer[assignment["customer_id"]] = assignment["sales_rep_id"]

    # Pick distinct customers (cycle if fewer than templates).
    chosen = rng.sample(customers, min(len(_TEMPLATES), len(customers)))

    opportunities: list[dict] = []
    stage_history: list[dict] = []
    for index, template in enumerate(_TEMPLATES):
        customer = chosen[index % len(chosen)]
        stage, value, probability = template
        opp_id = index + 1
        opportunities.append(
            {
                "id": opp_id,
                "customer_id": customer["id"],
                "title": rng.choice(_TITLES),
                "value": Decimal(value),
                "probability": Decimal(probability) if probability else None,
                "stage": stage,
                "source": rng.choice(_SOURCES),
                "expected_close": as_of + datetime.timedelta(days=rng.randint(10, 120)),
                "owner_rep_id": rep_by_customer.get(customer["id"]),
            }
        )
        stage_history.append({"id": opp_id, "opportunity_id": opp_id, "stage": stage})

    return opportunities, stage_history
