"""Shelter-leg alternatives for dispatch bids (Phase 2 Step 03).

Thin wrapper over routing: list shelters that can take ``seats_needed``
reachable from ``origin_node`` via ``mode``, sorted by ETA. Full use
arrives in Phase 4 (dynamic replanning after closures/overflow); here it
only feeds the bidder with deterministic shelter options.

Phase 4 Step 01 adds DETECTION + REPLAN PRIMITIVES at manager level
(:func:`replan`, :func:`find_routes_using_edge`). They are pure/no-mutation
helpers: the Step 05 pipeline owns assignment-status transitions
(``REQUIRES_RECONCILIATION``/``CANCELLED``) and calls these primitives.

Pure functions over :class:`World`; no FastAPI/DB imports.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import networkx as nx

from ..routing.graph import build_graph
from ..routing.pathfinder import find_route

if TYPE_CHECKING:
    from ..simulation.state_manager import StateManager
    from ..simulation.world import EdgeMode, World


def shelter_options(
    world: World, origin_node: str, mode: str, seats_needed: int
) -> list[tuple[str, dict]]:
    """Return ``[(shelter_id, route)]`` sorted by ``(eta_ticks, shelter_id)``.

    Only shelters with ``world.shelter_remaining(sid) >= seats_needed`` and
    a non-``None`` ``find_route(world, origin_node, shelter.node_id, mode)``
    are included. Shelter iteration is in ``shelter_id`` order so the result
    is deterministic.
    """
    options: list[tuple[str, dict]] = []
    for sid in sorted(world.shelters):
        shelter = world.shelters[sid]
        if world.shelter_remaining(sid) < seats_needed:
            continue
        route = find_route(world, origin_node, shelter.node_id, cast("EdgeMode", mode))
        if route is None:
            continue
        options.append((sid, route))
    options.sort(key=lambda item: (item[1]["eta_ticks"], item[0]))
    return options


def replan(
    world: World,
    origin_node: str,
    dest_node: str,
    mode: str,
    allow_disputed: bool = False,
) -> tuple[dict | None, str]:
    """Find a replacement route avoiding closed edges (Phase 4 Step 01).

    Builds the mode-filtered graph excluding ``closed`` edges (plus
    ``disputed`` edges unless ``allow_disputed``) and returns the
    shortest-time path. Success returns ``(route, "OK")`` where
    ``route`` is ``{nodes, edges, eta_ticks, risk, warnings}`` (same
    shape as :func:`routing.pathfinder.find_route`); no path — unknown
    nodes, unknown mode, or disconnected graph — returns
    ``(None, "REPLAN_FAILED:NO_ROUTE")``. Never raises for missing
    nodes / no path and never mutates ``world``.

    Pure function: detection of affected assignments and the
    ``REQUIRES_RECONCILIATION``/``CANCELLED`` transitions belong to the
    Step 05 pipeline, which calls this primitive.
    """
    if origin_node not in world.nodes or dest_node not in world.nodes:
        return None, "REPLAN_FAILED:NO_ROUTE"
    if origin_node == dest_node:
        return (
            {
                "nodes": [origin_node],
                "edges": [],
                "eta_ticks": 0,
                "risk": 0.0,
                "warnings": [],
            },
            "OK",
        )
    graph = build_graph(world, cast("EdgeMode", mode))
    if not allow_disputed:
        graph.remove_edges_from(
            [
                (u, v)
                for u, v, data in graph.edges(data=True)
                if data.get("status") == "disputed"
            ]
        )
    try:
        node_path: list[str] = nx.shortest_path(
            graph, source=origin_node, target=dest_node, weight="weight"
        )
    except (nx.NetworkXNoPath, nx.NodeNotFound, nx.NetworkXError):
        return None, "REPLAN_FAILED:NO_ROUTE"
    edge_ids: list[str] = []
    for u, v in zip(node_path, node_path[1:]):
        try:
            edge_ids.append(graph[u][v]["edge_id"])
        except KeyError:
            return None, "REPLAN_FAILED:NO_ROUTE"
    route = {
        "nodes": node_path,
        "edges": edge_ids,
        "eta_ticks": sum(world.edges[eid].travel_time for eid in edge_ids),
        "risk": round(max(world.edges[eid].risk_level for eid in edge_ids), 3)
        if edge_ids
        else 0.0,
        "warnings": [
            f"DISPUTED:{eid}"
            for eid in edge_ids
            if world.edges[eid].status == "disputed"
        ],
    }
    return route, "OK"


def find_routes_using_edge(manager: StateManager, edge_id: str) -> list[str]:
    """Return sorted resource IDs whose remaining route still needs ``edge_id``.

    Only un-traversed legs (``edge_ids[next_index:]``) count: a resource
    that already crossed the edge is not affected by its closure. Pure
    read over ``manager.routes``; no mutation, no logging.
    """
    hit: list[str] = []
    for resource_id, route in manager.routes.items():
        remaining = route.get("edge_ids", [])[route.get("next_index", 0):]
        if edge_id in remaining:
            hit.append(resource_id)
    return sorted(hit)


__all__ = ["shelter_options", "replan", "find_routes_using_edge"]
