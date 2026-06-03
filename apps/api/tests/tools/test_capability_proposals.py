"""CSA Phase 3a: capability-proposal lifecycle (create → approve → queryable → undo).

Trust-critical: an approved metric must equal direct SQL, every state change must
write a reversible decision, and unsafe SQL must never activate.
"""

import datetime
from decimal import Decimal

import pytest
from sqlalchemy import text

from valeri_api.capabilities.applier import (
    InvalidProposalState,
    approve_proposal,
    create_proposal,
    reject_proposal,
    undo_proposal,
)
from valeri_api.capabilities.schemas import ProposalCreate, ProposalParam
from valeri_api.semantic.proposal_safety import UnsafeMetricSQL
from valeri_api.semantic.query_builder import run_metric
from valeri_api.semantic.registry import available_metrics, resolve_metric

_TODAY = datetime.date.today()
_FROM = _TODAY - datetime.timedelta(days=365)

_GOOD_SQL = (
    "SELECT CAST(DATE_TRUNC('month', i.date) AS date) AS month, COUNT(*) AS broj "
    "FROM core.invoice i "
    "WHERE i.date > :from_date AND i.date <= :to_date "
    "GROUP BY 1 ORDER BY 1"
)


def _good_proposal(name: str = "invoice_count_by_month") -> ProposalCreate:
    return ProposalCreate(
        name=name,
        description="Broj faktura po mjesecima za period",
        entity="company",
        grain="series",
        params=[
            ProposalParam(name="from_date", type="date", required=True),
            ProposalParam(name="to_date", type="date", required=True),
        ],
        sql=_GOOD_SQL,
    )


def _decisions_for(session, proposal_id: int) -> list:
    return session.execute(
        text(
            "SELECT kind, reversible FROM app.decision "
            "WHERE (payload->>'capability_proposal_id')::bigint = :id ORDER BY id"
        ),
        {"id": proposal_id},
    ).all()


def test_full_lifecycle_approved_metric_equals_sql(owner_context) -> None:
    session, user = owner_context.session, owner_context.user

    proposal = create_proposal(session, _good_proposal(), user)
    assert proposal.status == "proposed"
    # Inert before approval: not in the vocabulary, not runnable.
    assert resolve_metric(session, proposal.name) is None

    approve_proposal(session, proposal.id, user)
    session.flush()

    # Now it's a first-class metric: in the overlay AND queryable.
    assert proposal.name in available_metrics(session)
    result = run_metric(session, proposal.name, {"from_date": _FROM, "to_date": _TODAY})
    by_month = {row["month"]: row["broj"] for row in result.rows}

    # Equals direct SQL (the number contract for overlay metrics).
    direct = session.execute(
        text(
            "SELECT CAST(DATE_TRUNC('month', i.date) AS date) AS month, COUNT(*) AS broj "
            "FROM core.invoice i WHERE i.date > :a AND i.date <= :b GROUP BY 1"
        ),
        {"a": _FROM, "b": _TODAY},
    ).all()
    assert by_month == {row.month: row.broj for row in direct}
    assert by_month  # the seed has invoices in range

    # Approval wrote a reversible decision.
    decisions = _decisions_for(session, proposal.id)
    assert ("approval", True) in [(k, r) for k, r in decisions]


def test_undo_deactivates_and_removes_from_overlay(owner_context) -> None:
    session, user = owner_context.session, owner_context.user
    proposal = create_proposal(session, _good_proposal("avg_lines_per_invoice_x"), user)
    approve_proposal(session, proposal.id, user)
    session.flush()
    assert proposal.name in available_metrics(session)

    undo_proposal(session, proposal.id, user)
    session.flush()
    assert proposal.status == "reverted"
    assert proposal.name not in available_metrics(session)  # gone from the overlay
    assert resolve_metric(session, proposal.name) is None
    kinds = [k for k, _r in _decisions_for(session, proposal.id)]
    assert "approval" in kinds and "undo" in kinds  # both logged, append-only


def test_reject_keeps_it_inert(owner_context) -> None:
    session, user = owner_context.session, owner_context.user
    proposal = create_proposal(session, _good_proposal("rejected_metric_x"), user)
    reject_proposal(session, proposal.id, user)
    session.flush()
    assert proposal.status == "rejected"
    assert proposal.name not in available_metrics(session)
    assert ("rejection", False) in _decisions_for(session, proposal.id)


def test_unsafe_sql_rejected_at_creation(owner_context) -> None:
    session, user = owner_context.session, owner_context.user
    bad = _good_proposal("evil_x")
    bad.sql = "DELETE FROM core.invoice"
    with pytest.raises(UnsafeMetricSQL):
        create_proposal(session, bad, user)


def test_invalid_query_rejected_at_approval(owner_context) -> None:
    """Passes the static check but fails EXPLAIN at approval → never activates."""
    session, user = owner_context.session, owner_context.user
    sneaky = _good_proposal("sneaky_x")
    # Static-valid SELECT over an allowed table, but references a non-existent column.
    sneaky.sql = "SELECT nepostojeca_kolona FROM core.invoice WHERE id = :id"
    sneaky.params = [ProposalParam(name="id", type="integer", required=True)]
    proposal = create_proposal(session, sneaky, user)  # static check passes
    with pytest.raises(UnsafeMetricSQL):
        approve_proposal(session, proposal.id, user)
    session.flush()
    assert proposal.status == "proposed"  # stayed inert
    assert resolve_metric(session, proposal.name) is None


def test_cannot_approve_twice(owner_context) -> None:
    session, user = owner_context.session, owner_context.user
    proposal = create_proposal(session, _good_proposal("once_x"), user)
    approve_proposal(session, proposal.id, user)
    session.flush()
    with pytest.raises(InvalidProposalState):
        approve_proposal(session, proposal.id, user)
