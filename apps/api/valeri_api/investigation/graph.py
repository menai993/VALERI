"""The LangGraph state machine (M13): plan → act ⇄ critic → [HITL] → synthesize.

LangGraph only sequences nodes and checkpoints state — it never talks to an LLM
or the DB itself (the nodes do, through VALERI's existing discipline). The graph
interrupts BEFORE execute_action: proposed task/draft actions can only run after
an explicit human approval (POST /investigations/{id}/resume).
"""

from langgraph.graph import END, START, StateGraph

from valeri_api.investigation.nodes import SessionFactory, build_nodes, route_after_critic
from valeri_api.investigation.schemas import InvestigationState
from valeri_api.llm.client import LLMClient

# The nodes the graph must pause before — anything that executes an action.
HITL_NODES = ["execute_action"]


def build_graph(session_factory: SessionFactory, client: LLMClient | None, checkpointer):
    """Compile the investigation graph with Postgres checkpointing + the HITL gate."""
    nodes = build_nodes(session_factory, client)

    builder = StateGraph(InvestigationState)
    builder.add_node("plan", nodes["plan"])
    builder.add_node("act", nodes["act"])
    builder.add_node("critic", nodes["critic"])
    builder.add_node("execute_action", nodes["execute_action"])
    builder.add_node("synthesize", nodes["synthesize"])

    builder.add_edge(START, "plan")
    builder.add_edge("plan", "act")
    builder.add_edge("act", "critic")
    builder.add_conditional_edges(
        "critic",
        route_after_critic,
        {"act": "act", "execute_action": "execute_action", "synthesize": "synthesize"},
    )
    builder.add_edge("execute_action", "synthesize")
    builder.add_edge("synthesize", END)

    return builder.compile(checkpointer=checkpointer, interrupt_before=HITL_NODES)
