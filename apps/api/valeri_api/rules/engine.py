"""Shared rule-engine plumbing: config, signal drafts, suppression, dedup, insert.

Numbers (values, ratios, confidence scores) are computed in each rule's SQL;
this module only loads thresholds, packages rows, and writes app.signal.
"""

import datetime
import json
from decimal import Decimal
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import insert, text
from sqlalchemy.orm import Session

GLOBAL_RULE = "global"


# ── thresholds ────────────────────────────────────────────────────────────────


def load_rule_config(session: Session, rule: str) -> dict[str, Any]:
    """Load a rule's thresholds from app.rule_config (never hard-coded)."""
    rows = session.execute(
        text("SELECT param, value FROM app.rule_config WHERE rule = :rule"),
        {"rule": rule},
    ).all()
    if not rows:
        raise LookupError(f"No app.rule_config entries for rule {rule!r}")
    return {row.param: row.value for row in rows}


# ── signal drafts ─────────────────────────────────────────────────────────────


class SignalDraft(BaseModel):
    """A detection result before it becomes an app.signal row."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    rule: str
    customer_id: int | None = None
    article_id: int | None = None
    evidence: dict[str, Any]
    confidence: Decimal = Field(ge=0, le=1)
    register: str = "analiza"

    def dedup_key(self) -> tuple[str, int | None, int | None, str | None]:
        # category_id discriminates signals that share (rule, customer, article=None),
        # e.g. two lost categories of the same customer.
        category = self.evidence.get("category_id")
        return (
            self.rule,
            self.customer_id,
            self.article_id,
            str(category) if category is not None else None,
        )


class Rule(Protocol):
    """Every rule module exposes RULE_NAME and detect()."""

    RULE_NAME: str

    @staticmethod
    def detect(session: Session, as_of: datetime.date) -> list[SignalDraft]: ...


def conf_band(session: Session, confidence: Decimal) -> str:
    """Map a confidence score to its band using the global thresholds."""
    config = load_rule_config(session, GLOBAL_RULE)
    if confidence >= Decimal(str(config["conf_band_high"])):
        return "visoka"
    if confidence >= Decimal(str(config["conf_band_mid"])):
        return "srednja"
    return "niska"


# ── learned-rule consultation (the M4 hook; learned rules are written in M10) ─


def load_active_suppressions(session: Session) -> list[dict[str, Any]]:
    """Active, non-expired learned rules of type 'suppress' (scope JSONB rows)."""
    rows = session.execute(
        text(
            "SELECT id, rule_type, scope FROM app.learned_rule "
            "WHERE status = 'active' AND rule_type = 'suppress' "
            "AND (expires_at IS NULL OR expires_at > now())"
        )
    ).all()
    return [{"id": row.id, "scope": row.scope} for row in rows]


def find_suppression(
    draft: SignalDraft,
    suppressions: list[dict[str, Any]],
    customer_segments: dict[int, str | None] | None = None,
) -> int | None:
    """Return the learned_rule id that suppresses this draft, or None.

    Supported scope shapes (docs/data-model.md):
      {"kind": "entity", "entity_type": "customer"|"article", "entity_id": N, "rule": "..."?}
      {"kind": "category", "category": "...", "rule": "..."?}
      {"kind": "once", "rule": "...", "customer_id": N?, "article_id": N?}
    A scope without "rule" applies to every rule.

    A category scope means "this whole group" — it matches the draft's evidence
    category (product categories, e.g. lost_category) OR the customer's segment
    (segment scopes, e.g. "kafić"); `customer_segments` is the id→segment map
    insert_signals loads for the drafts being processed (M11 fix).
    """
    for suppression in suppressions:
        scope = suppression["scope"]
        scoped_rule = scope.get("rule")
        if scoped_rule is not None and scoped_rule != draft.rule:
            continue

        kind = scope.get("kind")
        if kind == "entity":
            entity_type = scope.get("entity_type")
            entity_id = scope.get("entity_id")
            if entity_type == "customer" and draft.customer_id == entity_id:
                return suppression["id"]
            if entity_type == "article" and draft.article_id == entity_id:
                return suppression["id"]
        elif kind == "category":
            scoped_category = scope.get("category")
            evidence_category = draft.evidence.get("category_name") or draft.evidence.get("segment")
            customer_segment = (customer_segments or {}).get(draft.customer_id)
            if scoped_category is not None and scoped_category in (
                evidence_category,
                customer_segment,
            ):
                return suppression["id"]
        elif kind == "once":
            if scope.get("customer_id") == draft.customer_id and (
                scope.get("article_id") is None or scope.get("article_id") == draft.article_id
            ):
                return suppression["id"]
    return None


def load_customer_segments(session: Session, drafts: list[SignalDraft]) -> dict[int, str | None]:
    """The id→segment map for the drafts' customers (one query; category-scope matching)."""
    customer_ids = sorted({d.customer_id for d in drafts if d.customer_id is not None})
    if not customer_ids:
        return {}
    rows = session.execute(
        text("SELECT id, segment FROM core.customer WHERE id = ANY(:ids)"),
        {"ids": customer_ids},
    ).all()
    return {row.id: row.segment for row in rows}


# ── dedup + insert ────────────────────────────────────────────────────────────


def open_signal_keys(session: Session) -> set[tuple[str, int | None, int | None, str | None]]:
    """Keys of signals that are still open (new/tasked) — re-detection is a duplicate."""
    rows = session.execute(
        text(
            "SELECT rule, customer_id, article_id, evidence->>'category_id' AS category "
            "FROM app.signal WHERE status IN ('new', 'tasked')"
        )
    ).all()
    return {(row.rule, row.customer_id, row.article_id, row.category) for row in rows}


def suppressed_signal_keys(
    session: Session,
) -> dict[tuple[str, int | None, int | None, str | None], int]:
    """Keys → ids of persisted suppressed signals (M10).

    A re-detected suppressed pattern isn't duplicated; the recurrence is recorded
    as another suppression_hit on the existing suppressed signal.
    """
    rows = session.execute(
        text(
            "SELECT id, rule, customer_id, article_id, evidence->>'category_id' AS category "
            "FROM app.signal WHERE status = 'suppressed'"
        )
    ).all()
    return {(row.rule, row.customer_id, row.article_id, row.category): row.id for row in rows}


class InsertOutcome(BaseModel):
    """What happened to one rule's drafts during a scan."""

    inserted: int = 0
    suppressed: int = 0
    deduplicated: int = 0


def insert_signals(
    session: Session,
    drafts: list[SignalDraft],
    suppressions: list[dict[str, Any]] | None = None,
    existing_keys: set[tuple[str, int | None, int | None, str | None]] | None = None,
) -> InsertOutcome:
    """Write drafts to app.signal, applying suppression + dedup. Returns counters.

    M10: suppressed drafts are PERSISTED (status='suppressed', evidence kept) and
    every suppression writes an app.suppression_hit row — the raw material for the
    over-suppression auditor. Repeat detections of an already-suppressed pattern
    add hits to the existing suppressed signal instead of duplicating it.
    """
    from valeri_api.audit.serialization import jsonable
    from valeri_api.rules.models import Signal, SuppressionHit

    suppressions = suppressions if suppressions is not None else load_active_suppressions(session)
    existing_keys = existing_keys if existing_keys is not None else open_signal_keys(session)
    suppressed_keys = suppressed_signal_keys(session)
    # Customer segments are only needed when category scopes could match (M11 fix).
    customer_segments = load_customer_segments(session, drafts) if suppressions else {}

    outcome = InsertOutcome()
    rows: list[dict[str, Any]] = []

    for draft in drafts:
        if draft.dedup_key() in existing_keys:
            outcome.deduplicated += 1
            continue

        suppressing_rule_id = find_suppression(draft, suppressions, customer_segments)
        if suppressing_rule_id is not None:
            outcome.suppressed += 1
            existing_suppressed_id = suppressed_keys.get(draft.dedup_key())
            if existing_suppressed_id is None:
                # Persist the suppressed signal (evidence preserved, no task ever).
                suppressed_signal = Signal(
                    rule=draft.rule,
                    customer_id=draft.customer_id,
                    article_id=draft.article_id,
                    evidence=jsonable(draft.evidence),
                    confidence=draft.confidence,
                    conf_band=conf_band(session, draft.confidence),
                    register=draft.register,
                    status="suppressed",
                )
                session.add(suppressed_signal)
                session.flush()
                existing_suppressed_id = suppressed_signal.id
                suppressed_keys[draft.dedup_key()] = existing_suppressed_id
            else:
                # M11: refresh the stored evidence to the CURRENT detection — the
                # over-suppression auditor compares this against the rule's source
                # signal (the state the owner dismissed) to detect drift.
                session.execute(
                    text(
                        "UPDATE app.signal SET evidence = CAST(:evidence AS jsonb), "
                        "confidence = :confidence, conf_band = :band WHERE id = :id"
                    ),
                    {
                        "evidence": json.dumps(jsonable(draft.evidence)),
                        "confidence": draft.confidence,
                        "band": conf_band(session, draft.confidence),
                        "id": existing_suppressed_id,
                    },
                )

            # APPEND-ONLY: one hit per suppression event (incl. recurrences).
            session.add(
                SuppressionHit(
                    learned_rule_id=suppressing_rule_id, signal_id=existing_suppressed_id
                )
            )
            continue

        rows.append(
            {
                "rule": draft.rule,
                "customer_id": draft.customer_id,
                "article_id": draft.article_id,
                "evidence": jsonable(draft.evidence),
                "confidence": draft.confidence,
                "conf_band": conf_band(session, draft.confidence),
                "register": draft.register,
                "status": "new",
            }
        )
        existing_keys.add(draft.dedup_key())
        outcome.inserted += 1

    if rows:
        session.execute(insert(Signal), rows)
    session.flush()

    return outcome
