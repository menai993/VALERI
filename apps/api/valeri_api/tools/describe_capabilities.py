"""Tool: describe_capabilities — the platform's self-description (CSA).

Read-only, no numbers: returns the RBAC-filtered list of metrics + tools the
caller can use, so the agent (and the user, via "šta me možeš pitati?") knows
what the platform can actually answer. Never returns a business value.
"""

from pydantic import BaseModel

from valeri_api.semantic.capabilities import CapabilityDescriptor, list_capabilities
from valeri_api.tools.base import ToolContext, ToolDefinition

ALL_ROLES = ("owner", "admin", "finance", "sales_rep")


class DescribeCapabilitiesInput(BaseModel):
    """No parameters — the caller's role decides what is visible."""


class DescribeCapabilitiesOutput(BaseModel):
    capabilities: list[CapabilityDescriptor]


def _run(tool_input: DescribeCapabilitiesInput, context: ToolContext) -> DescribeCapabilitiesOutput:
    return DescribeCapabilitiesOutput(
        capabilities=list_capabilities(context.session, context.user.role)
    )


DESCRIBE_CAPABILITIES = ToolDefinition(
    name="describe_capabilities",
    description=(
        "Vraća spisak onoga što VALERI može odgovoriti (dostupne metrike i alate), "
        "prilagođen ulozi korisnika. Bez brojki — samo mogućnosti."
    ),
    input_schema=DescribeCapabilitiesInput,
    output_schema=DescribeCapabilitiesOutput,
    allowed_roles=ALL_ROLES,
    run=_run,
)
