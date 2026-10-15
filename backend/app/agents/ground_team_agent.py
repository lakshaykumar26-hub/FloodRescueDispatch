"""Ground-team resource agent: feasibility evaluation from LOCAL BELIEF only.

Road-only counterpart of :mod:`.boat_agent` (logic duplicated, not shared:
agents may import networkx + stdlib + ``.base_agent`` only). Teams carry no
fuel or shelter leg: a feasible team bid has ``shelter_id None``, empty
``shelter_route_edge_ids``, ``fuel_feasible True`` and ``shelter_feasible
True`` (the team works on scene — recorded as audit note
``TEAM_ON_SCENE``). Infeasible requests return ``(None, reason-code)``.
"""

import networkx as nx

from .base_agent import BaseAgent

#: Exact keys of every bid dict this module emits (must match Step 03 shape).
BID_KEYS = frozenset(
    {
        "agent_id",
        "incident_id",
        "estimated_arrival",
        "estimated_completion",
        "risk_score",
        "people_capacity",
        "fuel_feasible",
        "shelter_feasible",
        "belief_version",
        "resource_kind",
        "seats",
        "route_edge_ids",
        "shelter_id",
        "shelter_route_edge_ids",
        "eta_ticks",
        "risk_sum",
    }
)

#: Fixed handling buffer added to arrival to get completion (ticks).
HANDLING_BUFFER_TICKS = 2


def _belief_edge_records(belief: dict) -> list:
    """Return belief edge records, tolerating dict- or list-shaped storage."""
    edges = belief.get("edges", {})
    if isinstance(edges, dict):
        return list(edges.values())
    return list(edges)


def _build_road_graph(records: list) -> nx.DiGraph:
    """Local directed graph over non-closed road belief edges, both directions."""
    best: dict = {}
    for rec in records:
        if not isinstance(rec, dict):
            continue
        if rec.get("mode") != "road":
            continue
        if rec.get("status") == "closed":
            continue
        frm, to = rec.get("from_node"), rec.get("to_node")
        if not frm or not to:
            continue
        try:
            travel = float(rec.get("travel_time", 1))
        except (TypeError, ValueError):
            continue
        try:
            risk = float(rec.get("risk_level", 0.0))
        except (TypeError, ValueError):
            risk = 0.0
        edge_id = rec.get("edge_id", "")
        for u, v in ((frm, to), (to, frm)):
            prev = best.get((u, v))
            if prev is None or travel < prev[0]:
                best[(u, v)] = (travel, edge_id, risk)
    graph = nx.DiGraph()
    for (u, v), (travel, edge_id, risk) in best.items():
        graph.add_edge(u, v, weight=travel, edge_id=edge_id, risk=risk)
    return graph


def _shortest_route(graph: nx.DiGraph, origin: str, dest: str):
    """Return (edge_ids, eta_ticks, risk_sum) or None when unreachable."""
    if origin == dest:
        return ([], 0, 0.0)
    try:
        nodes = nx.shortest_path(graph, source=origin, target=dest, weight="weight")
    except (nx.NetworkXNoPath, nx.NodeNotFound, nx.NetworkXError):
        return None
    edge_ids = [graph[u][v]["edge_id"] for u, v in zip(nodes, nodes[1:])]
    eta = sum(graph[u][v]["weight"] for u, v in zip(nodes, nodes[1:]))
    if float(eta).is_integer():
        eta = int(eta)
    risk_sum = sum(graph[u][v]["risk"] for u, v in zip(nodes, nodes[1:]))
    return (edge_ids, eta, risk_sum)


class GroundTeamAgent(BaseAgent):
    """Owns position, capabilities, mission state, and a local belief."""

    kind = "team"

    def __init__(
        self,
        team_id: str,
        node_id: str,
        capabilities: list,
        status: str = "AVAILABLE",
    ) -> None:
        super().__init__(team_id)
        self.node_id = node_id
        self.capabilities = list(capabilities)
        self.status = status

    def _reject(self, tick: int, incident_id: str, reason: str):
        self.audit.append(
            {
                "event": "BID_REJECTED",
                "tick": tick,
                "actor": self.id,
                "incident_id": incident_id,
                "reason": reason,
            }
        )
        return (None, reason)

    def evaluate(self, request: dict, tick: int) -> tuple:
        """Evaluate a rescue request from local belief.

        Returns ``(bid, "OK")`` or ``(None, reason-code)``. Checks run in
        order: status -> capability -> route. Teams offer ``seats == people``
        (no capacity field) and need no shelter leg.
        """
        incident_id = request.get("incident_id", "")
        dest = request.get("node_id", "")
        people = request.get("people", 0)
        capabilities = request.get("capabilities", []) or []

        if self.status != "AVAILABLE":
            return self._reject(tick, incident_id, "RESOURCE_UNAVAILABLE")
        if capabilities and "ground" not in capabilities:
            return self._reject(tick, incident_id, "MODE_MISMATCH")

        graph = _build_road_graph(_belief_edge_records(self.local_belief))
        route = _shortest_route(graph, self.node_id, dest)
        if route is None:
            return self._reject(tick, incident_id, "NO_ROUTE")
        route_edge_ids, eta_ticks, risk_sum = route

        seats = people
        estimated_arrival = tick + eta_ticks
        bid = {
            "agent_id": self.id,
            "incident_id": incident_id,
            "estimated_arrival": estimated_arrival,
            "estimated_completion": estimated_arrival + HANDLING_BUFFER_TICKS,
            "risk_score": round(risk_sum, 3),
            "people_capacity": seats,
            "fuel_feasible": True,
            "shelter_feasible": True,
            "belief_version": self.local_belief.get("belief_version", 0),
            "resource_kind": "team",
            "seats": seats,
            "route_edge_ids": list(route_edge_ids),
            "shelter_id": None,
            "shelter_route_edge_ids": [],
            "eta_ticks": eta_ticks,
            "risk_sum": risk_sum,
        }
        assert set(bid) == set(BID_KEYS), f"bid keys drifted: {sorted(set(bid))}"
        self.audit.append(
            {
                "event": "BID_SUBMITTED",
                "tick": tick,
                "actor": self.id,
                "incident_id": incident_id,
                "reason": "OK",
                "note": "TEAM_ON_SCENE",
                "belief_version": bid["belief_version"],
            }
        )
        return (bid, "OK")


__all__ = ["GroundTeamAgent"]
