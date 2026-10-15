"""Mode-filtered directed graph built from a World.

Pure function over :class:`World`; no clock, no I/O, no FastAPI/DB imports.
"""

from typing import Optional

import networkx as nx

from ..simulation.world import EdgeMode, World


def build_graph(world: World, mode: EdgeMode, tick: Optional[int] = None) -> nx.DiGraph:
    """Build a directed graph of traversable edges for ``mode``.

    Each world edge with matching ``mode`` and ``status`` of ``open`` or
    ``disputed`` becomes two directed arcs (both travel directions) with
    ``weight=travel_time`` plus ``edge_id``/``risk_level``/``status``/
    ``capacity`` attributes. Edges with ``status == "closed"`` are excluded.

    ``tick`` is accepted for forward compatibility (tick ordering is
    documented by callers: a closure at tick T applies before movement in
    tick T) but does not change filtering: the graph always reflects the
    current ``world.edges`` statuses.
    """
    _ = tick  # reserved for future snapshot filtering; intentionally unused.
    graph = nx.DiGraph()
    for node_id in world.nodes:
        graph.add_node(node_id)
    for edge in world.edges.values():
        if edge.mode != mode:
            continue
        if edge.status == "closed":
            continue
        graph.add_edge(
            edge.from_node,
            edge.to_node,
            weight=edge.travel_time,
            edge_id=edge.edge_id,
            risk_level=edge.risk_level,
            status=edge.status,
            capacity=edge.capacity,
        )
        graph.add_edge(
            edge.to_node,
            edge.from_node,
            weight=edge.travel_time,
            edge_id=edge.edge_id,
            risk_level=edge.risk_level,
            status=edge.status,
            capacity=edge.capacity,
        )
    return graph
