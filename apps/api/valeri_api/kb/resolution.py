"""Server-side entity resolution (CI1, §8.1): deterministic, never the model.

A mentioned customer name is matched against core.customer using the confirmed
app.customer_alias table first, then pg_trgm similarity (+ a distinguishing
detail per candidate). The §8.2 decision matrix decides auto / clarify / none;
stakes are applied later in apply.py. The model never sees or picks an id.
"""

from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from valeri_api.kb.schemas import ResolutionCandidate, ResolutionResult
from valeri_api.rules.engine import load_rule_config

# Below this trgm similarity a row isn't even a candidate (noise floor).
_CANDIDATE_FLOOR = 0.15
# A unique auto-attach needs this much daylight over the runner-up (else: clarify).
_AUTO_GAP = 0.15
# A focus customer this similar wins ties (the entity currently under discussion).
_FOCUS_MIN = 0.30


def _candidate_rows(session: Session, name: str) -> list[ResolutionCandidate]:
    rows = session.execute(
        text(
            "SELECT c.id, c.name, c.segment, "
            "       similarity(c.name, :q) AS sim, "
            "       (SELECT max(i.date) FROM core.invoice i "
            "        WHERE i.customer_id = c.id) AS last_order "
            "FROM core.customer c "
            "WHERE similarity(c.name, :q) > :floor "
            "ORDER BY sim DESC, c.id "
            "LIMIT 5"
        ),
        {"q": name, "floor": _CANDIDATE_FLOOR},
    ).all()
    return [
        ResolutionCandidate(
            customer_id=row.id,
            name=row.name,
            similarity=float(row.sim),
            segment=row.segment,
            last_order=row.last_order,
        )
        for row in rows
    ]


def resolve_mention(
    session: Session,
    name: str,
    *,
    context_customer_id: int | None = None,
) -> ResolutionResult:
    """Resolve a mentioned customer name to an id, or decide to clarify / give up.

    decision='auto' (confident unique match, `customer_id` set) · 'clarify'
    (ambiguous or medium match) · 'none' (no reasonable candidate). The auto-attach
    similarity cutoff is the `kb.auto_attach_similarity` threshold (rule_config).
    """
    name = name.strip()
    config = load_rule_config(session, "kb")
    auto_sim = float(config["auto_attach_similarity"])

    # 1) A confirmed alias is a direct, learned hit — no ambiguity (§8.5).
    alias = session.execute(
        text("SELECT customer_id FROM app.customer_alias WHERE lower(alias) = lower(:n)"),
        {"n": name},
    ).first()
    if alias is not None:
        return ResolutionResult(
            mentioned_name=name,
            candidates=_lookup_one(session, alias.customer_id),
            decision="auto",
            customer_id=alias.customer_id,
            reason="alias",
        )

    # 2) Fuzzy candidates (pg_trgm), ranked.
    candidates = _candidate_rows(session, name)
    if not candidates:
        return ResolutionResult(
            mentioned_name=name, candidates=[], decision="none", reason="no_candidate"
        )

    top = candidates[0]
    second_sim = candidates[1].similarity if len(candidates) > 1 else 0.0

    # 3) Focus tiebreak: prefer the customer currently under discussion (§8.1).
    if context_customer_id is not None:
        focus = next((c for c in candidates if c.customer_id == context_customer_id), None)
        if focus is not None and focus.similarity >= _FOCUS_MIN:
            return ResolutionResult(
                mentioned_name=name,
                candidates=candidates,
                decision="auto",
                customer_id=focus.customer_id,
                reason="focus",
            )

    # 4) Confident unique match → auto; otherwise ambiguous/medium → clarify.
    if top.similarity >= auto_sim and (
        len(candidates) == 1 or top.similarity - second_sim >= _AUTO_GAP
    ):
        return ResolutionResult(
            mentioned_name=name,
            candidates=candidates,
            decision="auto",
            customer_id=top.customer_id,
            reason="unique_match",
        )
    return ResolutionResult(
        mentioned_name=name,
        candidates=candidates,
        decision="clarify",
        reason="ambiguous_or_medium",
    )


def _lookup_one(session: Session, customer_id: int) -> list[ResolutionCandidate]:
    """A single-candidate list for an already-known id (alias hit)."""
    row = session.execute(
        text(
            "SELECT c.id, c.name, c.segment, "
            "       (SELECT max(i.date) FROM core.invoice i "
            "        WHERE i.customer_id = c.id) AS last_order "
            "FROM core.customer c WHERE c.id = :id"
        ),
        {"id": customer_id},
    ).first()
    if row is None:
        return []
    return [
        ResolutionCandidate(
            customer_id=row.id,
            name=row.name,
            similarity=1.0,
            segment=row.segment,
            last_order=row.last_order,
        )
    ]


def conf_band_for(confidence: float | Decimal) -> str:
    """Map a 0–1 confidence to the conf_band enum (KB uses fixed cutoffs, not rule_config)."""
    value = float(confidence)
    if value >= 0.75:
        return "visoka"
    if value >= 0.5:
        return "srednja"
    return "niska"
