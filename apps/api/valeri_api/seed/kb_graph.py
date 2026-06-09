"""CI2 demo seed: confirmed KB relationships so the graph-aware rules fire.

Plants three confirmed (status='active') edges over the existing planted cases so a
fresh scan surfaces a group_risk, a behavioral_twin_warning, and a
referral_source_risk signal out of the box:

  • same_owner   between two declining customers   → group decline together
  • behavioral_twin between two sleeping customers  → twin early warning
  • referral     a sleeping referrer → an active customer → referral-source risk

Gated by SeedConfig.with_kb_graph (off for the shared test seed, on for the demo
CLI). The edges are 'stated' provenance — exactly what a confirmed CI1 capture
would produce.
"""

from decimal import Decimal

from valeri_api.seed.config import SeedConfig
from valeri_api.seed.types import PlantedPlan


def _edge(from_id: int, to_id: int, rel_type: str, note: str) -> dict:
    return {
        "from_customer_id": from_id,
        "to_customer_id": to_id,
        "rel_type": rel_type,
        "source": "stated",
        "source_message_id": None,
        "source_user_id": None,
        "evidence_text": note,
        "confidence": Decimal("0.900"),
        "conf_band": "visoka",
        "status": "active",
    }


def generate_client_relationships(
    plan: PlantedPlan, customers: list[dict], config: SeedConfig
) -> list[dict]:
    """Confirmed demo edges; empty unless config.with_kb_graph is on."""
    if not config.with_kb_graph:
        return []

    rels: list[dict] = []

    # Group risk: two declining objects under one (confirmed) owner.
    if len(plan.declines) >= 2:
        rels.append(
            _edge(plan.declines[0], plan.declines[1], "same_owner", "Demo: ista vlasnička grupa.")
        )

    # Behavioral twin: two sleeping customers flagged as twins.
    if len(plan.sleeping) >= 2:
        rels.append(
            _edge(
                plan.sleeping[0],
                plan.sleeping[1],
                "behavioral_twin",
                "Demo: ponašajni blizanci.",
            )
        )

    # Referral: a sleeping (quiet) referrer pointing at an otherwise-active customer.
    if len(plan.sleeping) >= 3:
        planted = (
            set(plan.declines)
            | set(plan.sleeping)
            | set(plan.seasonal_cafes)
            | set(plan.narrow_baskets)
            | set(plan.lost_hosts)
        )
        referred = next((c["id"] for c in customers if c["id"] not in planted), None)
        if referred is not None:
            rels.append(_edge(plan.sleeping[2], referred, "referral", "Demo: preporuka kupca."))

    return rels
