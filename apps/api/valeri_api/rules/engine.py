"""Shared rule-engine plumbing: config, signal drafts, suppression, dedup, insert.

Numbers (values, ratios, confidence scores) are computed in each rule's SQL;
this module only loads thresholds, packages rows, and writes app.signal.
"""

import datetime
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


def find_suppression(draft: SignalDraft, suppressions: list[dict[str, Any]]) -> int | None:
    """Return the learned_rule id that suppresses this draft, or None.

    Supported scope shapes (docs/data-model.md):
      {"kind": "entity", "entity_type": "customer"|"article", "entity_id": N, "rule": "..."?}
      {"kind": "category", "category": "...", "rule": "..."?}   (matched via evidence)
      {"kind": "once", "rule": "...", "customer_id": N?, "article_id": N?}
    A scope without "rule" applies to every rule.
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
            evidence_category = draft.evidence.get("category_name") or draft.evidence.get("segment")
            if evidence_category == scope.get("category"):
                return suppression["id"]
        elif kind == "once":
            if scope.get("customer_id") == draft.customer_id and (
                scope.get("article_id") is None or scope.get("article_id") == draft.article_id
            ):
                return suppression["id"]
    return None


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
    """Write drafts to app.signal, applying suppression + dedup. Returns counters."""
    from valeri_api.audit.serialization import jsonable

    suppressions = suppressions if suppressions is not None else load_active_suppressions(session)
    existing_keys = existing_keys if existing_keys is not None else open_signal_keys(session)

    outcome = InsertOutcome()
    rows: list[dict[str, Any]] = []

    for draft in drafts:
        if draft.dedup_key() in existing_keys:
            outcome.deduplicated += 1
            continue
        if find_suppression(draft, suppressions) is not None:
            outcome.suppressed += 1
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
        from valeri_api.rules.models import Signal

        session.execute(insert(Signal), rows)
        session.flush()

    return outcome
