"""Tool: get_client_knowledge — the CONFIRMED KB about one customer (CI2).

Read-only, RBAC-checked, SQL-only. Returns the active profile summary, facts,
commercial events, and confirmed relationships — each carrying its evidence (the
source sentence) and confidence — so the investigation agent (or chat) can CITE
KB knowledge. Proposed/unconfirmed records are excluded; the model computes no
number here.
"""

from typing import Any

from pydantic import BaseModel
from sqlalchemy import text

from valeri_api.tools.base import ToolContext, ToolDefinition

ALL_ROLES = ("owner", "admin", "finance", "sales_rep")


class GetClientKnowledgeInput(BaseModel):
    customer_id: int


class KnowledgeFactOut(BaseModel):
    fact_type: str
    fact_key: str
    value: Any
    source: str
    confidence: str
    conf_band: str
    evidence: str | None


class KnowledgeEventOut(BaseModel):
    kind: str
    summary: str
    value: str | None
    occurred_on: Any | None
    source: str
    confidence: str
    evidence: str | None


class KnowledgeRelOut(BaseModel):
    rel_type: str
    other_customer_id: int
    other_name: str | None
    source: str
    confidence: str
    evidence: str | None


class GetClientKnowledgeOutput(BaseModel):
    customer_id: int
    customer_name: str | None
    profile_summary: str | None
    facts: list[KnowledgeFactOut]
    events: list[KnowledgeEventOut]
    relationships: list[KnowledgeRelOut]


def _run(tool_input: GetClientKnowledgeInput, context: ToolContext) -> GetClientKnowledgeOutput:
    context.assert_customer_visible(tool_input.customer_id)
    session = context.session
    cid = tool_input.customer_id

    name = session.execute(
        text("SELECT name FROM core.customer WHERE id = :id"), {"id": cid}
    ).scalar()
    summary = session.execute(
        text("SELECT summary FROM app.client_profile WHERE customer_id = :id"), {"id": cid}
    ).scalar()

    facts = session.execute(
        text(
            "SELECT fact_type, fact_key, value, source, confidence, conf_band, evidence_text "
            "FROM app.client_fact WHERE customer_id = :id AND status = 'active' ORDER BY id DESC"
        ),
        {"id": cid},
    ).mappings()
    events = session.execute(
        text(
            "SELECT kind, summary, value, occurred_on, source, confidence, evidence_text "
            "FROM app.commercial_event WHERE customer_id = :id AND status = 'active' "
            "ORDER BY occurred_on DESC NULLS LAST, id DESC"
        ),
        {"id": cid},
    ).mappings()
    # Confirmed (active) edges only, in either direction.
    rels = session.execute(
        text(
            "SELECT r.rel_type, r.source, r.confidence, r.evidence_text, "
            "  CASE WHEN r.from_customer_id = :id THEN r.to_customer_id "
            "       ELSE r.from_customer_id END AS other_id, "
            "  c.name AS other_name "
            "FROM app.client_relationship r "
            "JOIN core.customer c ON c.id = CASE WHEN r.from_customer_id = :id "
            "       THEN r.to_customer_id ELSE r.from_customer_id END "
            "WHERE r.status = 'active' "
            "  AND (r.from_customer_id = :id OR r.to_customer_id = :id) ORDER BY r.id DESC"
        ),
        {"id": cid},
    ).mappings()

    # RBAC fail-closed: a rep only sees edges whose other endpoint is also in scope
    # (don't disclose a related customer outside the rep's book).
    scope = context.visible_customers()
    rels = [r for r in rels if scope is None or r["other_id"] in scope]

    return GetClientKnowledgeOutput(
        customer_id=cid,
        customer_name=name,
        profile_summary=summary,
        facts=[
            KnowledgeFactOut(
                fact_type=f["fact_type"],
                fact_key=f["fact_key"],
                value=f["value"],
                source=f["source"],
                confidence=str(f["confidence"]),
                conf_band=f["conf_band"],
                evidence=f["evidence_text"],
            )
            for f in facts
        ],
        events=[
            KnowledgeEventOut(
                kind=e["kind"],
                summary=e["summary"],
                value=str(e["value"]) if e["value"] is not None else None,
                occurred_on=e["occurred_on"],
                source=e["source"],
                confidence=str(e["confidence"]),
                evidence=e["evidence_text"],
            )
            for e in events
        ],
        relationships=[
            KnowledgeRelOut(
                rel_type=r["rel_type"],
                other_customer_id=r["other_id"],
                other_name=r["other_name"],
                source=r["source"],
                confidence=str(r["confidence"]),
                evidence=r["evidence_text"],
            )
            for r in rels
        ],
    )


GET_CLIENT_KNOWLEDGE = ToolDefinition(
    name="get_client_knowledge",
    description=(
        "Potvrđeno znanje o kupcu iz baze znanja: sažetak profila, činjenice, poslovni "
        "događaji (npr. ugovori) i potvrđene veze s drugim kupcima — svako s dokazom "
        "(izvorna rečenica) i pouzdanošću. Samo za čitanje. Parametri: customer_id"
    ),
    input_schema=GetClientKnowledgeInput,
    output_schema=GetClientKnowledgeOutput,
    allowed_roles=ALL_ROLES,
    run=_run,
)
