"""Shortest-path lookup over a mode-filtered world graph.

Pure function over :class:`World`; no clock, no I/O, no FastAPI/DB imports.
"""

from typing import Optional

import networkx as nx

from ..simulation.world import EdgeMode, World
from .graph import build_graph


def find_route(
    world: World, origin: str, dest: str, mode: EdgeMode
) -> Optional[dict]:
    """Find the shortest-time route from ``origin`` to ``dest`` for ``mode``.

    Returns ``{"nodes": [...], "edges": [edge_ids...], "eta_ticks": int,
    "risk": float, "warnings": [...]}`` or ``None`` when there is no path
    (including unknown nodes). Never raises for missing nodes / no path.

    - ``eta_ticks`` equals the sum of ``travel_time`` over the chosen edges.
    - ``risk`` is the max ``risk_level`` along the path, rounded to 3 decimals.
    - ``warnings`` lists disputed edges traversed as ``"DISPUTED:<edge_id>"``.
    """
    if origin not in world.nodes or dest not in world.nodes:
        return None
    if origin == dest:
        return {"nodes": [origin], "edges": [], "eta_ticks": 0, "risk": 0.0, "warnings": []}
    graph = build_graph(world, mode)
    try:
        node_path: list[str] = nx.shortest_path(
            graph, source=origin, target=dest, weight="weight"
        )
    except (nx.NetworkXNoPath, nx.NodeNotFound, nx.NetworkXError):
        return None
    edge_ids: list[str] = []
    for u, v in zip(node_path, node_path[1:]):
        try:
            edge_ids.append(graph[u][v]["edge_id"])
        except KeyError:
            return None
    eta_ticks = sum(world.edges[eid].travel_time for eid in edge_ids)
    risk = round(max(world.edges[eid].risk_level for eid in edge_ids), 3) if edge_ids else 0.0
    warnings = [
        f"DISPUTED:{eid}" for eid in edge_ids if world.edges[eid].status == "disputed"
    ]
    return {
        "nodes": node_path,
        "edges": edge_ids,
        "eta_ticks": eta_ticks,
        "risk": risk,
        "warnings": warnings,
    }
