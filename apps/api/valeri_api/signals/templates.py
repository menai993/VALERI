"""Deterministic Bosnian task templates (M5).

Pure string formatting of SQL-computed evidence values — nothing is calculated
here, and no LLM is involved. M6 replaces these bodies with LLM narration
(same numbers, richer phrasing).
"""

from typing import Any

FOOTER = "Brojke iz baze · SQL"

_TITLES = {
    "customer_decline": "Pad prometa: {customer_name}",
    "lost_article": "Izgubljen artikal kod kupca: {customer_name}",
    "lost_category": "Izgubljena kategorija kod kupca: {customer_name}",
    "sleeping_customer": "Uspavani kupac: {customer_name}",
    "narrow_basket": "Prilika za proširenje asortimana: {customer_name}",
}

_ACTIONS = {
    "customer_decline": (
        "Kontaktirati kupca, provjeriti razlog pada prometa i ponuditi akcijsku ponudu."
    ),
    "lost_article": (
        "Provjeriti zašto kupac više ne naručuje artikal; ponuditi zamjenu ili poseban popust."
    ),
    "lost_category": (
        "Razgovarati s kupcem o potrebama u ovoj kategoriji i pripremiti ciljanu ponudu."
    ),
    "sleeping_customer": (
        "Nazvati kupca, provjeriti situaciju i dogovoriti ponovnu narudžbu (win-back)."
    ),
    "narrow_basket": (
        "Predstaviti kupcu kategorije koje slični kupci redovno naručuju (cross-sell)."
    ),
}


def render_title(rule: str, context: dict[str, Any]) -> str:
    return _TITLES[rule].format(**context)


def render_action(rule: str) -> str:
    return _ACTIONS[rule]


def render_body(rule: str, evidence: dict[str, Any], context: dict[str, Any]) -> str:
    """Render the Bosnian body. Every number is an evidence value, inserted verbatim."""
    customer = context.get("customer_name", "nepoznat kupac")

    if rule == "customer_decline":
        body = (
            f"Promet kupca {customer} u zadnjih 60 dana iznosi {evidence['value']} KM, "
            f"dok je uobičajeni nivo {evidence['baseline']} KM "
            f"(promjena {evidence['delta_pct']}%). "
            f"Pad nije sezonski (provjereno poređenjem s istim periodom prošle godine)."
        )
    elif rule == "lost_article":
        body = (
            f"Kupac {customer} je redovno naručivao artikal "
            f"\"{evidence['article_name']}\" ({evidence['article_code']}) — "
            f"prosječno svakih {evidence['avg_interval_d']} dana, "
            f"ukupno {evidence['purchases_before_loss']} puta. "
            f"Zadnja narudžba: {evidence['last_seen']} (prije {evidence['gap_days']} dana). "
            f"Kupac i dalje naručuje ostale artikle."
        )
    elif rule == "lost_category":
        body = (
            f"Kupac {customer} više ne naručuje kategoriju \"{evidence['category_name']}\" — "
            f"zadnja kupovina {evidence['last_purchase']} (prije {evidence['gap_days']} dana), "
            f"a ranije je naručena {evidence['purchases_before']} puta. "
            f"Kupac je i dalje aktivan u drugim kategorijama."
        )
    elif rule == "sleeping_customer":
        body = (
            f"Kupac {customer} nije naručio ništa od {evidence['last_order_date']} "
            f"(prije {evidence['gap_days']} dana), iako je ranije naručivao prosječno svakih "
            f"{evidence['avg_order_interval_d']} dana "
            f"(ukupno {evidence['order_count']} narudžbi)."
        )
    elif rule == "narrow_basket":
        missing = ", ".join(category["name"] for category in evidence["missing_categories"])
        body = (
            f"Kupac {customer} naručuje iz svega {evidence['n_categories']} kategorije/a, "
            f"dok slični kupci (segment: {evidence['segment']}) redovno naručuju i: {missing}."
        )
    else:
        raise ValueError(f"No body template for rule {rule!r}")

    return f"{body}\n\n{FOOTER}"
