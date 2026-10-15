"""Boat resource agent: feasibility evaluation from LOCAL BELIEF only.

The agent NEVER sees the global ``World``. It routes over its own
``local_belief`` edges (water mode, ``status != closed``, both directions)
with networkx, and checks fuel / capacity / shelter against its own state
plus belief. Infeasible requests return ``(None, reason-code)``; the caller
logs the reason (feeds the explanation panel).

Bid ``risk_sum`` is the summed ``risk_level`` over the rescue-leg
``route_edge_ids`` (incident leg only, not the shelter leg).
``people_capacity`` is the seats offered on this trip (``== seats``).
``estimated_completion = estimated_arrival + 2`` is a documented fixed
handling buffer (rescue + handover), not a second route estimate.
"""

import networkx as nx

from .base_agent import BaseAgent

#: Exact keys of every bid dict this module emits (Step 03 consumes them).
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


def _belief_shelter_records(belief: dict) -> list:
    """Return (shelter_id, record) pairs from belief shelters."""
    shelters = belief.get("shelters", {})
    if isinstance(shelters, dict):
        return list(shelters.items())
    return [(rec.get("shelter_id", ""), rec) for rec in shelters]


def _belief_shelter_remaining(record: dict) -> int:
    """Seats left per belief: capacity - occupancy - held reservations."""
    if isinstance(record.get("remaining"), (int, float)):
        return int(record["remaining"])
    capacity = record.get("capacity", 0)
    occupancy = record.get("occupancy", 0)
    held = record.get("reservations", record.get("reserved", {}))
    if isinstance(held, dict):
        held_seats = sum(held.values())
    elif isinstance(held, (int, float)):
        held_seats = held
    else:
        held_seats = 0
    return capacity - occupancy - held_seats


def _build_mode_graph(records: list, mode: str) -> nx.DiGraph:
    """Local directed graph for ``mode`` over non-closed belief edges.

    Edges are bidirectional (flood boats/teams can traverse either way);
    parallel edges between one node pair collapse to the fastest one.
    """
    best: dict = {}
    for rec in records:
        if not isinstance(rec, dict):
            continue
        if rec.get("mode") != mode:
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


class BoatAgent(BaseAgent):
    """Owns position, capacity, fuel, mission state, and a local belief."""

    kind = "boat"

    def __init__(
        self,
        boat_id: str,
        capacity: int,
        fuel: float,
        fuel_reserve: float,
        speed: float = 1.0,
        node_id: str = "",
        status: str = "AVAILABLE",
        passengers: int = 0,
    ) -> None:
        super().__init__(boat_id)
        self.capacity = capacity
        self.fuel = fuel
        self.fuel_reserve = fuel_reserve
        self.speed = speed
        self.node_id = node_id
        self.status = status
        self.passengers = passengers

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

    def _pick_shelter(self, graph: nx.DiGraph, incident_node: str, seats: int):
        """Best shelter leg from belief: min (eta, shelter_id) over reachable
        shelters with ``remaining >= seats``. Returns (shelter_id, edge_ids)
        or (None, []) when no shelter leg is feasible from local belief."""
        best = None
        for shelter_id, record in _belief_shelter_records(self.local_belief):
            if not isinstance(record, dict):
                continue
            if _belief_shelter_remaining(record) < seats:
                continue
            shelter_node = record.get("node_id", "")
            leg = _shortest_route(graph, incident_node, shelter_node)
            if leg is None:
                continue
            leg_edge_ids, leg_eta, _ = leg
            candidate = (leg_eta, str(shelter_id), leg_edge_ids)
            if best is None or (candidate[0], candidate[1]) < (best[0], best[1]):
                best = candidate
        if best is None:
            return (None, [])
        return (best[1], best[2])

    def evaluate(self, request: dict, tick: int) -> tuple:
        """Evaluate a rescue request from local belief.

        Returns ``(bid, "OK")`` or ``(None, reason-code)``. Checks run in
        order: status -> capability -> route -> fuel -> capacity -> shelter.
        """
        incident_id = request.get("incident_id", "")
        dest = request.get("node_id", "")
        people = request.get("people", 0)
        capabilities = request.get("capabilities", []) or []

        if self.status != "AVAILABLE":
            return self._reject(tick, incident_id, "RESOURCE_UNAVAILABLE")
        if capabilities and "boat" not in capabilities:
            return self._reject(tick, incident_id, "MODE_MISMATCH")

        graph = _build_mode_graph(_belief_edge_records(self.local_belief), "water")
        route = _shortest_route(graph, self.node_id, dest)
        if route is None:
            return self._reject(tick, incident_id, "NO_ROUTE")
        route_edge_ids, eta_ticks, risk_sum = route

        if self.fuel < eta_ticks + self.fuel_reserve:
            return self._reject(tick, incident_id, "FUEL_INSUFFICIENT")

        seats = min(people, self.capacity - self.passengers)
        if seats <= 0:
            return self._reject(tick, incident_id, "OVER_CAPACITY")

        shelter_id, shelter_edge_ids = self._pick_shelter(graph, dest, seats)
        if shelter_id is None:
            return self._reject(tick, incident_id, "SHELTER_FULL")

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
            "resource_kind": "boat",
            "seats": seats,
            "route_edge_ids": list(route_edge_ids),
            "shelter_id": shelter_id,
            "shelter_route_edge_ids": list(shelter_edge_ids),
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
                "belief_version": bid["belief_version"],
            }
        )
        return (bid, "OK")
