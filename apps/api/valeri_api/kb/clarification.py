"""Clarification questions (CI1, §8.3): ask ONE short, specific question instead
of guessing — for entity ambiguity, but also reference/merge/value/conflict.

Asking is non-blocking: the record is stored 'proposed' and the question waits in
the review queue. Answering (kb/service.py) writes a reversible decision and may
write a customer_alias.
"""

import datetime
from typing import Any

from sqlalchemy.orm import Session

from valeri_api.kb.models import Clarification
from valeri_api.kb.schemas import ResolutionResult


def _format_detail(segment: str | None, last_order: datetime.date | None) -> str:
    bits = []
    if segment:
        bits.append(segment)
    if last_order:
        bits.append(f"zadnja narudžba {last_order.strftime('%d.%m.%Y')}.")
    return f" ({', '.join(bits)})" if bits else ""


def build_entity_options(resolution: ResolutionResult) -> list[dict[str, Any]]:
    """Tappable options: link to each candidate, pick another, or create a prospect."""
    options: list[dict[str, Any]] = [
        {
            "label": f"Da, {c.name}",
            "action": "link",
            "customer_id": c.customer_id,
        }
        for c in resolution.candidates
    ]
    options.append({"label": "Nije — drugi kupac", "action": "pick_other"})
    options.append(
        {"label": f"Novi kupac „{resolution.mentioned_name}“", "action": "create_prospect"}
    )
    return options


def build_entity_question(resolution: ResolutionResult) -> str:
    """The Bosnian 'da li ste mislili… / novi kupac?' question (§8.6)."""
    name = resolution.mentioned_name
    if resolution.candidates:
        top = resolution.candidates[0]
        detail = _format_detail(top.segment, top.last_order)
        return f"Da li „{name}“ znači kupca {top.name}{detail}, ili je to novi kupac?"
    return f"„{name}“ — je li to novi kupac?"


def raise_clarification(
    session: Session,
    *,
    kind: str,
    question: str,
    options: list[dict[str, Any]],
    target_record_ref: str,
) -> Clarification:
    """Persist a pending clarification (it shows in the review queue, never blocks)."""
    clarification = Clarification(
        kind=kind,
        question=question,
        options=options,
        target_record_ref=target_record_ref,
        status="pending",
    )
    session.add(clarification)
    session.flush()
    return clarification
