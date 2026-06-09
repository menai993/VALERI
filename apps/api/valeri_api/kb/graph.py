"""Graph traversal over CONFIRMED customer relationships (CI2).

Only edges with status='active' are ever traversed — a confirmed edge is the human
gate from CI1; nothing inferred is treated as truth. Used by the graph-aware rules
(group/owner-level risk) and by GET /kb/graph (the relationship map).

This module finds structure (connected components, an ego graph); the business
NUMBERS over those members are computed by the rules' SQL, never here.
"""

from collections import defaultdict
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

# Relationship types that mean "treat these objects as one group".
GROUP_REL_TYPES = ("same_owner", "same_group", "chain")


def _confirmed_edges(session: Session, rel_types: tuple[str, ...]) -> list[tuple[int, int]]:
    rows = session.execute(
        text(
            "SELECT from_customer_id, to_customer_id FROM app.client_relationship "
            "WHERE status = 'active' AND rel_type = ANY(:types)"
        ),
        {"types": list(rel_types)},
    ).all()
    return [(row.from_customer_id, row.to_customer_id) for row in rows]


def connected_components(session: Session, rel_types: tuple[str, ...]) -> list[set[int]]:
    """All connected components over confirmed edges of the given rel types (union-find)."""
    edges = _confirmed_edges(session, rel_types)
    parent: dict[int, int] = {}

    def find(node: int) -> int:
        parent.setdefault(node, node)
        root = node
        while parent[root] != root:
            root = parent[root]
        while parent[node] != root:  # path compression
            parent[node], node = root, parent[node]
        return root

    def union(a: int, b: int) -> None:
        parent[find(a)] = find(b)

    nodes: set[int] = set()
    for a, b in edges:
        nodes.add(a)
        nodes.add(b)
        union(a, b)

    groups: dict[int, set[int]] = defaultdict(set)
    for node in nodes:
        groups[find(node)].add(node)
    return list(groups.values())


def connected_group(
    session: Session, customer_id: int, rel_types: tuple[str, ...] = GROUP_REL_TYPES
) -> set[int]:
    """The set of customers connected to `customer_id` over confirmed edges (incl. itself)."""
    for component in connected_components(session, rel_types):
        if customer_id in component:
            return component
    return {customer_id}


def graph_for_customer(session: Session, customer_id: int, depth: int = 1) -> dict[str, Any]:
    """Ego graph around a customer: confirmed nodes + edges within `depth` hops.

    Returns {nodes:[{customer_id,name,segment,risk_band}], edges:[{from,to,rel_type,
    source,confidence,evidence_message_id}]} — confirmed (status='active') edges only.
    """
    visited: set[int] = {customer_id}
    frontier: set[int] = {customer_id}
    edges_seen: dict[int, dict[str, Any]] = {}

    for _ in range(max(depth, 1)):
        if not frontier:
            break
        rows = session.execute(
            text(
                "SELECT id, from_customer_id, to_customer_id, rel_type, source, "
                "       confidence, source_message_id "
                "FROM app.client_relationship "
                "WHERE status = 'active' "
                "AND (from_customer_id = ANY(:ids) OR to_customer_id = ANY(:ids))"
            ),
            {"ids": sorted(frontier)},
        ).all()
        next_frontier: set[int] = set()
        for row in rows:
            edges_seen[row.id] = {
                "from": row.from_customer_id,
                "to": row.to_customer_id,
                "rel_type": row.rel_type,
                "source": row.source,
                "confidence": str(row.confidence),
                "evidence_message_id": row.source_message_id,
            }
            for endpoint in (row.from_customer_id, row.to_customer_id):
                if endpoint not in visited:
                    next_frontier.add(endpoint)
                    visited.add(endpoint)
        frontier = next_frontier

    nodes = []
    if visited:
        node_rows = session.execute(
            text(
                "SELECT c.id, c.name, c.segment, "
                "       (SELECT s.conf_band FROM app.signal s "
                "        WHERE s.customer_id = c.id AND s.status IN ('new', 'tasked') "
                "        ORDER BY s.confidence DESC LIMIT 1) AS risk_band "
                "FROM core.customer c WHERE c.id = ANY(:ids) ORDER BY c.id"
            ),
            {"ids": sorted(visited)},
        ).all()
        nodes = [
            {
                "customer_id": row.id,
                "name": row.name,
                "segment": row.segment,
                "risk_band": row.risk_band,
            }
            for row in node_rows
        ]

    return {"nodes": nodes, "edges": list(edges_seen.values())}
