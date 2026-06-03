"""The tool registry + dispatcher: RBAC → validate → run → log, for every call.

This is the single chokepoint between the conversation layer (or the M13 agent)
and the tools. Nothing reaches a tool implementation without passing through
dispatch(), and no call — successful or not — escapes the tool_call_log.
"""

import logging
import time
from typing import Any

from pydantic import BaseModel, ValidationError

from valeri_api.tools.base import ToolContext, ToolDefinition, ToolError, ToolPermissionError
from valeri_api.tools.compare_periods import COMPARE_PERIODS
from valeri_api.tools.create_task_draft import CREATE_TASK_DRAFT
from valeri_api.tools.explain_signal import EXPLAIN_SIGNAL
from valeri_api.tools.get_client_knowledge import GET_CLIENT_KNOWLEDGE
from valeri_api.tools.get_customer_360 import GET_CUSTOMER_360
from valeri_api.tools.list_signals import LIST_SIGNALS
from valeri_api.tools.log import log_tool_call
from valeri_api.tools.propose_rule_change import PROPOSE_RULE_CHANGE
from valeri_api.tools.query_metric import QUERY_METRIC
from valeri_api.tools.start_investigation import START_INVESTIGATION

logger = logging.getLogger("valeri.tools.catalog")

TOOLS: dict[str, ToolDefinition] = {
    tool.name: tool
    for tool in (
        QUERY_METRIC,
        COMPARE_PERIODS,
        LIST_SIGNALS,
        EXPLAIN_SIGNAL,
        GET_CUSTOMER_360,
        GET_CLIENT_KNOWLEDGE,
        CREATE_TASK_DRAFT,
        PROPOSE_RULE_CHANGE,
        START_INVESTIGATION,
    )
}


class ToolResult(BaseModel):
    """What a dispatch returns to the conversation layer."""

    tool: str
    ok: bool
    output: dict[str, Any] | None = None
    error: str | None = None
    error_code: str | None = None


def dispatch(
    context: ToolContext,
    tool_name: str,
    params: dict[str, Any] | None = None,
) -> ToolResult:
    """Run one tool call with the full discipline. Never raises — errors become results.

    Order matters: RBAC is checked before params validation so a denied caller
    learns nothing about what valid parameters look like.
    """
    started = time.monotonic()
    params = params or {}

    def _log(ok: bool, result_ref: str | None = None) -> None:
        log_tool_call(
            context.session,
            tool=tool_name,
            args=params,
            ok=ok,
            result_ref=result_ref,
            latency_ms=int((time.monotonic() - started) * 1000),
            message_id=context.message_id,
        )

    # ── unknown tool ──────────────────────────────────────────────────────────
    definition = TOOLS.get(tool_name)
    if definition is None:
        _log(ok=False)
        return ToolResult(
            tool=tool_name, ok=False, error=f"Nepoznat alat: {tool_name}", error_code="unknown_tool"
        )

    # ── RBAC: role gate ───────────────────────────────────────────────────────
    if context.user.role not in definition.allowed_roles:
        _log(ok=False)
        return ToolResult(
            tool=tool_name,
            ok=False,
            error="Nemate pristup ovom alatu (RBAC)",
            error_code="forbidden",
        )

    # ── validate params ───────────────────────────────────────────────────────
    try:
        tool_input = definition.input_schema.model_validate(params)
    except ValidationError as error:
        _log(ok=False)
        return ToolResult(
            tool=tool_name,
            ok=False,
            error=f"Neispravni parametri: {error.error_count()} grešaka",
            error_code="invalid_params",
        )

    # ── run (row-level RBAC happens inside the tool) ─────────────────────────
    try:
        output = definition.run(tool_input, context)
    except ToolPermissionError as error:
        _log(ok=False)
        return ToolResult(tool=tool_name, ok=False, error=str(error), error_code="forbidden")
    except ToolError as error:
        _log(ok=False)
        return ToolResult(tool=tool_name, ok=False, error=str(error), error_code=error.code)
    except Exception:  # noqa: BLE001 - the audit trail must be total: nothing escapes the log
        logger.exception("unexpected error in tool %s", tool_name)
        _log(ok=False)
        return ToolResult(
            tool=tool_name,
            ok=False,
            error="Neočekivana greška pri izvršavanju alata",
            error_code="tool_error",
        )

    result_ref = getattr(output, "result_ref", None)
    _log(ok=True, result_ref=result_ref)
    return ToolResult(tool=tool_name, ok=True, output=output.model_dump(mode="json"))
