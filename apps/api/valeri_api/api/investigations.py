"""Investigations API (M13) — per docs/api-spec.md.

RBAC (spec D4): create + resume = owner/admin; view = owner/admin/finance.
The API never runs the agent inline — POST returns 202 and the worker picks the
queued investigation up; resume runs the continuation (it is a user-blocking
decision, so it executes in-request).
"""

import asyncio
import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from valeri_api.auth.deps import require_roles
from valeri_api.auth.models import AppUser
from valeri_api.db import get_session
from valeri_api.investigation.models import Investigation, InvestigationStep
from valeri_api.investigation.runner import (
    FeatureCapReached,
    InvalidInvestigationState,
    InvestigationNotFound,
    create_investigation,
    pending_actions,
    resume_investigation,
)
from valeri_api.investigation.schemas import (
    InvestigationCreate,
    InvestigationCreated,
    InvestigationDetail,
    InvestigationListResponse,
    InvestigationRead,
    InvestigationStepRead,
    ResumeRequest,
    ResumeResponse,
)

router = APIRouter()

# Spec D4: owner/admin start and decide; finance may also read.
Creator = Annotated[AppUser, Depends(require_roles("owner", "admin"))]
Reader = Annotated[AppUser, Depends(require_roles("owner", "admin", "finance"))]

VALID_STATUSES = ("queued", "running", "needs_input", "done", "failed")


def _not_found(investigation_id: int) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={"code": "not_found", "message": f"Istraga {investigation_id} ne postoji"},
    )


# ── create (async — the worker runs it) ───────────────────────────────────────


@router.post("/investigations", status_code=202, response_model=InvestigationCreated)
def create(
    body: InvestigationCreate,
    session: Annotated[Session, Depends(get_session)],
    user: Creator,
) -> InvestigationCreated:
    """Queue an investigation; the worker picks it up (202, never blocks).

    P3: refuses with 429 feature_capped when the investigation daily cap is hit.
    """
    try:
        investigation = create_investigation(
            session, body.question, user, signal_id=body.signal_id, trigger="user"
        )
    except FeatureCapReached as capped:
        raise HTTPException(
            status_code=429,
            detail={"code": "feature_capped", "message": str(capped)},
        ) from capped
    session.commit()
    return InvestigationCreated(investigation_id=investigation.id, status=investigation.status)


# ── list / detail ─────────────────────────────────────────────────────────────


@router.get("/investigations", response_model=InvestigationListResponse)
def list_investigations(
    session: Annotated[Session, Depends(get_session)],
    _user: Reader,
    status: str | None = None,
) -> InvestigationListResponse:
    """All investigations, newest first, optionally filtered by status."""
    if status is not None and status not in VALID_STATUSES:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_status", "message": f"Nepoznat status: {status}"},
        )
    query = session.query(Investigation).order_by(Investigation.id.desc())
    if status is not None:
        query = query.filter(Investigation.status == status)
    items = [InvestigationRead.model_validate(row) for row in query.limit(100)]
    return InvestigationListResponse(items=items)


@router.get("/investigations/{investigation_id}", response_model=InvestigationDetail)
def get_investigation(
    investigation_id: int,
    session: Annotated[Session, Depends(get_session)],
    _user: Reader,
) -> InvestigationDetail:
    """One investigation: status + report + the full step trace + pending HITL actions."""
    investigation = session.get(Investigation, investigation_id)
    if investigation is None:
        raise _not_found(investigation_id)

    steps = (
        session.query(InvestigationStep)
        .filter(InvestigationStep.investigation_id == investigation_id)
        .order_by(InvestigationStep.step_no)
        .all()
    )
    pending = (
        pending_actions(session, investigation_id) if investigation.status == "needs_input" else []
    )
    return InvestigationDetail(
        investigation=InvestigationRead.model_validate(investigation),
        report=investigation.report,
        steps=[InvestigationStepRead.model_validate(step) for step in steps],
        pending_actions=pending,
    )


# ── resume (the HITL decision) ────────────────────────────────────────────────


@router.post("/investigations/{investigation_id}/resume", response_model=ResumeResponse)
def resume(
    investigation_id: int,
    body: ResumeRequest,
    session: Annotated[Session, Depends(get_session)],
    _user: Creator,
) -> ResumeResponse:
    """Approve/reject the agent's proposed actions and continue to the final report."""
    # The runner manages its own sessions/transactions; release the request session first.
    session.close()
    try:
        investigation = resume_investigation(investigation_id, body.decision)
    except InvestigationNotFound as error:
        raise _not_found(investigation_id) from error
    except InvalidInvestigationState as error:
        raise HTTPException(
            status_code=409, detail={"code": "conflict", "message": str(error)}
        ) from error
    return ResumeResponse(investigation=InvestigationRead.model_validate(investigation))


# ── SSE progress stream ───────────────────────────────────────────────────────

TERMINAL_STATUSES = ("done", "failed", "needs_input")
STREAM_POLL_SECONDS = 0.5
STREAM_TIMEOUT_SECONDS = 120


@router.get("/investigations/{investigation_id}/stream")
async def stream(
    investigation_id: int,
    session: Annotated[Session, Depends(get_session)],
    _user: Reader,
):
    """SSE progress: replays existing steps, then follows live ones until terminal."""
    investigation = session.get(Investigation, investigation_id)
    if investigation is None:
        raise _not_found(investigation_id)
    # The generator polls with its own short-lived sessions; release the request one.
    engine = session.get_bind()
    session.close()

    async def event_stream():
        last_step_no = 0
        elapsed = 0.0
        while True:
            with Session(engine) as poll_session:
                rows = poll_session.execute(
                    text(
                        "SELECT step_no, node, tool FROM app.investigation_step "
                        "WHERE investigation_id = :id AND step_no > :after ORDER BY step_no"
                    ),
                    {"id": investigation_id, "after": last_step_no},
                ).all()
                status = poll_session.execute(
                    text("SELECT status FROM app.investigation WHERE id = :id"),
                    {"id": investigation_id},
                ).scalar()

            for row in rows:
                last_step_no = row.step_no
                payload = {
                    "type": "step",
                    "step_no": row.step_no,
                    "node": row.node,
                    "tool": row.tool,
                }
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

            if status in TERMINAL_STATUSES:
                done_payload = {"type": "done", "status": status}
                yield f"data: {json.dumps(done_payload, ensure_ascii=False)}\n\n"
                return

            if elapsed >= STREAM_TIMEOUT_SECONDS:
                timeout_payload = {"type": "done", "status": status, "timeout": True}
                yield f"data: {json.dumps(timeout_payload, ensure_ascii=False)}\n\n"
                return

            await asyncio.sleep(STREAM_POLL_SECONDS)
            elapsed += STREAM_POLL_SECONDS

    return StreamingResponse(event_stream(), media_type="text/event-stream")
