"""Learned rules + decisions API (M10) — per docs/api-spec.md.

RBAC (spec D5): apply/undo/edit-scope = owner/admin; list/detail/decisions
feed = owner/admin/finance. Every mutation goes through the applier, which
writes the append-only reversible app.decision.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from valeri_api.audit.models import DECISION_KINDS
from valeri_api.auth.deps import require_roles
from valeri_api.auth.models import AppUser
from valeri_api.db import get_session
from valeri_api.selfconfig.applier import (
    InvalidRuleState,
    RuleNotFound,
    apply_rule,
    edit_scope,
    undo_rule,
)
from valeri_api.selfconfig.schemas import (
    ApplyRequest,
    ApplyResponse,
    DecisionListResponse,
    DecisionRead,
    LearnedRuleDetailResponse,
    LearnedRuleListResponse,
    LearnedRuleRead,
    ScopePatchRequest,
    SuppressionHitRead,
)

router = APIRouter()

# Read access includes finance; mutations are owner/admin only (D5).
Reader = Annotated[AppUser, Depends(require_roles("owner", "admin", "finance"))]
Mutator = Annotated[AppUser, Depends(require_roles("owner", "admin"))]

_RULE_SELECT = """
SELECT lr.id, lr.source_signal_id, lr.source_message_id, lr.domain, lr.rule_type,
       lr.scope, lr.description, lr.effect_estimate, lr.status, lr.autonomy,
       lr.created_by, lr.created_at, lr.expires_at,
       (SELECT COUNT(*) FROM app.suppression_hit h WHERE h.learned_rule_id = lr.id)
           AS suppression_count
FROM app.learned_rule lr
"""


def _not_found(message: str) -> HTTPException:
    return HTTPException(status_code=404, detail={"code": "not_found", "message": message})


def _conflict(message: str) -> HTTPException:
    return HTTPException(status_code=409, detail={"code": "conflict", "message": message})


# ── apply (the one-tap confirm) ───────────────────────────────────────────────


@router.post("/rules/apply", response_model=ApplyResponse)
def apply_pending_rule(
    body: ApplyRequest,
    session: Annotated[Session, Depends(get_session)],
    user: Mutator,
) -> ApplyResponse:
    """Activate a pending_confirm rule; writes the reversible decision."""
    try:
        response = apply_rule(session, body.learned_rule_id, user)
    except RuleNotFound as error:
        raise _not_found(str(error)) from error
    except InvalidRuleState as error:
        raise _conflict(str(error)) from error
    session.commit()
    return response


# ── learned rules ─────────────────────────────────────────────────────────────


@router.get("/learned-rules", response_model=LearnedRuleListResponse)
def list_learned_rules(
    session: Annotated[Session, Depends(get_session)],
    _user: Reader,
    status: str | None = None,
) -> LearnedRuleListResponse:
    """Every learned rule with its origin, SQL-counted effect, status and autonomy."""
    rows = session.execute(
        text(
            _RULE_SELECT
            + " WHERE (CAST(:status AS text) IS NULL OR lr.status::text = :status)"
            + " ORDER BY lr.id DESC"
        ),
        {"status": status},
    ).mappings()
    return LearnedRuleListResponse(items=[LearnedRuleRead(**dict(row)) for row in rows])


@router.get("/learned-rules/{rule_id}", response_model=LearnedRuleDetailResponse)
def get_learned_rule(
    rule_id: int,
    session: Annotated[Session, Depends(get_session)],
    _user: Reader,
) -> LearnedRuleDetailResponse:
    """One rule + its suppression hits + the decisions that touched it."""
    rule = (
        session.execute(text(_RULE_SELECT + " WHERE lr.id = :id"), {"id": rule_id})
        .mappings()
        .one_or_none()
    )
    if rule is None:
        raise _not_found(f"Naučeno pravilo {rule_id} ne postoji")

    hits = session.execute(
        text(
            "SELECT id, learned_rule_id, signal_id, suppressed_at "
            "FROM app.suppression_hit WHERE learned_rule_id = :id ORDER BY id DESC"
        ),
        {"id": rule_id},
    ).mappings()
    decisions = session.execute(
        text(
            "SELECT id, kind, actor, summary, payload, reversible, reverted_decision_id, "
            "created_at FROM app.decision "
            "WHERE (payload->>'learned_rule_id')::bigint = :id ORDER BY id"
        ),
        {"id": rule_id},
    ).mappings()

    return LearnedRuleDetailResponse(
        rule=LearnedRuleRead(**dict(rule)),
        hits=[SuppressionHitRead(**dict(hit)) for hit in hits],
        decisions=[DecisionRead(**dict(decision)) for decision in decisions],
    )


@router.patch("/learned-rules/{rule_id}/scope", response_model=ApplyResponse)
def patch_rule_scope(
    rule_id: int,
    body: ScopePatchRequest,
    session: Annotated[Session, Depends(get_session)],
    user: Mutator,
) -> ApplyResponse:
    """Edit a rule's scope; the decision records old + new."""
    try:
        response = edit_scope(session, rule_id, body.scope, user)
    except RuleNotFound as error:
        raise _not_found(str(error)) from error
    except InvalidRuleState as error:
        raise _conflict(str(error)) from error
    session.commit()
    return response


@router.post("/learned-rules/{rule_id}/undo", response_model=ApplyResponse)
def undo_learned_rule(
    rule_id: int,
    session: Annotated[Session, Depends(get_session)],
    user: Mutator,
) -> ApplyResponse:
    """Revert a rule (status='reverted') + write the undo decision."""
    try:
        response = undo_rule(session, rule_id, user)
    except RuleNotFound as error:
        raise _not_found(str(error)) from error
    except InvalidRuleState as error:
        raise _conflict(str(error)) from error
    session.commit()
    return response


# ── the decision feed ─────────────────────────────────────────────────────────


@router.get("/audit/decisions", response_model=DecisionListResponse)
def list_decisions(
    session: Annotated[Session, Depends(get_session)],
    _user: Reader,
    kind: str | None = None,
    limit: int = 100,
) -> DecisionListResponse:
    """The append-only decision feed ("show the decision on the platform")."""
    if kind is not None and kind not in DECISION_KINDS:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_kind", "message": f"Nepoznata vrsta odluke: {kind}"},
        )
    rows = session.execute(
        text(
            "SELECT id, kind, actor, summary, payload, reversible, reverted_decision_id, "
            "created_at FROM app.decision "
            "WHERE (CAST(:kind AS text) IS NULL OR kind::text = :kind) "
            "ORDER BY id DESC LIMIT :limit"
        ),
        {"kind": kind, "limit": max(1, min(limit, 500))},
    ).mappings()
    return DecisionListResponse(items=[DecisionRead(**dict(row)) for row in rows])
