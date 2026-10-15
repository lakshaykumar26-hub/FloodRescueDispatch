"""Phase 2 Step 03: feasibility codes + bid scoring (see docs/phase-2-centralized-dispatch/step-03-feasibility-scoring.md)."""

import pytest

from backend.app.dispatch.bid_evaluator import check_feasible, score
from backend.app.dispatch.route_replanner import shelter_options
from backend.app.dispatch.scheduler_interface import Weights
from backend.app.routing.pathfinder import find_route
from backend.app.simulation.world import (
    Boat,
    Edge,
    GroundTeam,
    Incident,
    Node,
    Shelter,
    World,
)


def _node(node_id: str, kind: str = "intersection") -> Node:
    return Node(node_id=node_id, neighborhood="n", kind=kind, x=0.0, y=0.0)  # type: ignore[arg-type]


def _edge(
    edge_id: str,
    frm: str,
    to: str,
    mode: str = "water",
    travel_time: int = 2,
    status: str = "open",
    risk: float = 0.1,
) -> Edge:
    return Edge(
        edge_id=edge_id,
        from_node=frm,
        to_node=to,
        mode=mode,  # type: ignore[arg-type]
        travel_time=travel_time,
        status=status,  # type: ignore[arg-type]
        risk_level=risk,
        capacity=10,
    )


def _incident(
    incident_id: str = "INC-01",
    node_id: str = "N-I",
    people: int = 4,
    status: str = "OPEN",
    caps: list | None = None,
) -> Incident:
    return Incident(
        incident_id=incident_id,
        node_id=node_id,
        urgency=3,
        people=people,
        required_capabilities=caps if caps is not None else ["boat"],
        status=status,  # type: ignore[arg-type]
    )


def _boat(
    boat_id: str = "BOAT-01",
    node_id: str = "N-A",
    capacity: int = 6,
    fuel: float = 20.0,
    reserve: float = 2.0,
    status: str = "AVAILABLE",
    assignment_id: str | None = None,
    passengers: int = 0,
) -> Boat:
    return Boat(
        boat_id=boat_id,
        node_id=node_id,
        capacity=capacity,
        fuel=fuel,
        fuel_reserve=reserve,
        status=status,  # type: ignore[arg-type]
        assignment_id=assignment_id,
        passengers=passengers,
    )


def _team(
    team_id: str = "TEAM-01",
    node_id: str = "N-R",
    status: str = "AVAILABLE",
    assignment_id: str | None = None,
) -> GroundTeam:
    return GroundTeam(
        team_id=team_id,
        node_id=node_id,
        capabilities=["ground"],
        status=status,  # type: ignore[arg-type]
        assignment_id=assignment_id,
    )


def _shelter(
    shelter_id: str = "SHELTER-01",
    node_id: str = "N-S",
    capacity: int = 10,
    occupancy: int = 0,
) -> Shelter:
    return Shelter(shelter_id=shelter_id, node_id=node_id, capacity=capacity, occupancy=occupancy)


def _base_world() -> World:
    """Water incident world: N-A -W-A-> N-I, shelter at N-S via W-S."""
    return World(
        nodes={
            "N-A": _node("N-A"),
            "N-I": _node("N-I", "incident_site"),
            "N-S": _node("N-S", "shelter"),
        },
        edges={
            "W-A": _edge("W-A", "N-A", "N-I"),
            "W-S": _edge("W-S", "N-I", "N-S"),
        },
        incidents={"INC-01": _incident()},
        boats={"BOAT-01": _boat()},
        shelters={"SHELTER-01": _shelter()},
    )


def _scoring_world() -> World:
    """Two boats, one incident.

    BOAT-NEAR: N-A -W-N-> N-I, eta 2, risk 0.9 (short but risky).
    BOAT-FAR: N-B -W-F1-> N-M -W-F2-> N-I, eta 3+3=6, risk 0.1+0.1 (long, safe).
    """
    return World(
        nodes={
            "N-A": _node("N-A"),
            "N-B": _node("N-B"),
            "N-M": _node("N-M"),
            "N-I": _node("N-I", "incident_site"),
        },
        edges={
            "W-N": _edge("W-N", "N-A", "N-I", travel_time=2, risk=0.9),
            "W-F1": _edge("W-F1", "N-B", "N-M", travel_time=3, risk=0.1),
            "W-F2": _edge("W-F2", "N-M", "N-I", travel_time=3, risk=0.1),
        },
        incidents={"INC-01": _incident(people=4)},
        boats={
            "BOAT-NEAR": _boat("BOAT-NEAR", node_id="N-A"),
            "BOAT-FAR": _boat("BOAT-FAR", node_id="N-B"),
        },
    )


def _route_or_fail(world: World, origin: str, dest: str, mode: str = "water") -> dict:
    route = find_route(world, origin, dest, mode)  # type: ignore[arg-type]
    assert route is not None
    return route


def _score_if_feasible(
    world: World,
    incident_id: str,
    resource_id: str,
    shelter_id: str | None,
    edge_ids: list[str],
    tick: int,
    route: dict,
    waiting_ticks: int,
    weights: Weights | None = None,
) -> float:
    """Feasibility gate: scoring an infeasible bid is a test bug, fail loudly."""
    ok, reason = check_feasible(world, incident_id, resource_id, shelter_id, edge_ids, tick)
    assert ok, f"must be feasible to score, got {reason}"
    return score(world, incident_id, resource_id, route, waiting_ticks, weights)


# --- hard-fail codes ---


def test_closed_edge_propagates_exact_code() -> None:
    world = _base_world()
    world.edges["W-A"].status = "closed"
    assert check_feasible(world, "INC-01", "BOAT-01", None, ["W-A"], 0) == (
        False,
        "EDGE_CLOSED:W-A",
    )


def test_unknown_edge_propagates_exact_code() -> None:
    world = _base_world()
    assert check_feasible(world, "INC-01", "BOAT-01", None, ["W-NOPE"], 0) == (
        False,
        "UNKNOWN_EDGE:W-NOPE",
    )


def test_low_fuel_rejected() -> None:
    world = _base_world()
    world.boats["BOAT-01"].fuel = 1.0  # eta 2 + reserve 2.0 = 4.0 needed
    assert check_feasible(world, "INC-01", "BOAT-01", None, ["W-A"], 0) == (
        False,
        "FUEL_INSUFFICIENT",
    )


def test_over_capacity_rejected() -> None:
    world = _base_world()
    # seats=6 fits capacity but passengers already aboard push it over.
    world.boats["BOAT-01"].passengers = 2
    ok, reason = check_feasible(world, "INC-01", "BOAT-01", None, ["W-A"], 0, seats=6)
    assert (ok, reason) == (False, "OVER_CAPACITY")
    # seats above capacity outright.
    ok, reason = check_feasible(world, "INC-01", "BOAT-01", None, ["W-A"], 0, seats=7)
    assert (ok, reason) == (False, "OVER_CAPACITY")


def test_full_shelter_rejected() -> None:
    world = _base_world()
    world.shelters["SHELTER-01"].occupancy = 9  # remaining 1 < seats 4
    assert check_feasible(world, "INC-01", "BOAT-01", "SHELTER-01", ["W-A"], 0) == (
        False,
        "SHELTER_FULL",
    )


def test_unknown_shelter_rejected() -> None:
    world = _base_world()
    assert check_feasible(world, "INC-01", "BOAT-01", "SHELTER-99", ["W-A"], 0) == (
        False,
        "SHELTER_UNKNOWN",
    )


def test_failed_boat_rejected() -> None:
    world = _base_world()
    world.boats["BOAT-01"].status = "FAILED"
    assert check_feasible(world, "INC-01", "BOAT-01", None, ["W-A"], 0) == (
        False,
        "RESOURCE_UNAVAILABLE",
    )


def test_busy_resource_rejected() -> None:
    world = _base_world()
    world.boats["BOAT-01"].assignment_id = "ASN-00001"
    assert check_feasible(world, "INC-01", "BOAT-01", None, ["W-A"], 0) == (
        False,
        "RESOURCE_UNAVAILABLE",
    )


def test_cross_mode_water_edge_for_team_rejected() -> None:
    world = World(
        nodes={"N-R": _node("N-R"), "N-I": _node("N-I", "incident_site")},
        edges={"W-A": _edge("W-A", "N-R", "N-I", mode="water")},
        incidents={"INC-01": _incident(caps=["ground"])},
        teams={"TEAM-01": _team()},
    )
    assert check_feasible(world, "INC-01", "TEAM-01", None, ["W-A"], 0) == (
        False,
        "MODE_MISMATCH",
    )


def test_road_edge_for_boat_rejected() -> None:
    world = World(
        nodes={"N-A": _node("N-A"), "N-I": _node("N-I", "incident_site")},
        edges={"R-A": _edge("R-A", "N-A", "N-I", mode="road")},
        incidents={"INC-01": _incident()},
        boats={"BOAT-01": _boat()},
    )
    assert check_feasible(world, "INC-01", "BOAT-01", None, ["R-A"], 0) == (
        False,
        "MODE_MISMATCH",
    )


def test_wrong_capability_rejected() -> None:
    world = _base_world()  # incident requires "boat"
    world.teams["TEAM-01"] = _team()
    world.edges["R-T"] = _edge("R-T", "N-R", "N-I", mode="road")
    world.nodes["N-R"] = _node("N-R")
    assert check_feasible(world, "INC-01", "TEAM-01", None, ["R-T"], 0) == (
        False,
        "MODE_MISMATCH",
    )


def test_served_incident_rejected() -> None:
    world = _base_world()
    world.incidents["INC-01"].status = "SERVED"
    assert check_feasible(world, "INC-01", "BOAT-01", None, ["W-A"], 0) == (
        False,
        "ASSIGNMENT_INVALID:INCIDENT_SERVED",
    )


def test_cancelled_incident_rejected() -> None:
    world = _base_world()
    world.incidents["INC-01"].status = "CANCELLED"
    assert check_feasible(world, "INC-01", "BOAT-01", None, ["W-A"], 0) == (
        False,
        "ASSIGNMENT_INVALID:INCIDENT_CANCELLED",
    )


def test_unknown_incident_and_resource_never_raise() -> None:
    world = _base_world()
    assert check_feasible(world, "INC-99", "BOAT-01", None, ["W-A"], 0) == (
        False,
        "UNKNOWN_ENTITY",
    )
    assert check_feasible(world, "INC-01", "BOAT-99", None, ["W-A"], 0) == (
        False,
        "UNKNOWN_ENTITY",
    )


def test_feasible_bid_ok() -> None:
    world = _base_world()
    assert check_feasible(world, "INC-01", "BOAT-01", "SHELTER-01", ["W-A"], 0) == (
        True,
        "OK",
    )


# --- scoring ---


def test_nearer_boat_wins_with_default_weights() -> None:
    world = _scoring_world()
    near_route = _route_or_fail(world, "N-A", "N-I")
    far_route = _route_or_fail(world, "N-B", "N-I")
    assert (near_route["eta_ticks"], far_route["eta_ticks"]) == (2, 6)
    near = _score_if_feasible(world, "INC-01", "BOAT-NEAR", None, ["W-N"], 0, near_route, 4)
    far = _score_if_feasible(world, "INC-01", "BOAT-FAR", None, ["W-F1", "W-F2"], 0, far_route, 4)
    assert near == pytest.approx(2 * 1.0 + 0.9 * 2.0 + (-4) * 0.5)
    assert far == pytest.approx(6 * 1.0 + 0.2 * 2.0 + (-4) * 0.5)
    assert near < far


def test_high_risk_weight_flips_winner_to_safer_boat() -> None:
    world = _scoring_world()
    near_route = _route_or_fail(world, "N-A", "N-I")
    far_route = _route_or_fail(world, "N-B", "N-I")
    heavy_risk = Weights(w_t=1.0, w_r=100.0, w_f=0.5, w_o=0.3)
    near = _score_if_feasible(
        world, "INC-01", "BOAT-NEAR", None, ["W-N"], 0, near_route, 4, heavy_risk
    )
    far = _score_if_feasible(
        world, "INC-01", "BOAT-FAR", None, ["W-F1", "W-F2"], 0, far_route, 4, heavy_risk
    )
    assert near == pytest.approx(2 + 100 * 0.9 - 2)
    assert far == pytest.approx(6 + 100 * 0.2 - 2)
    assert far < near


def test_longer_wait_is_cheaper_fairness_nudge() -> None:
    world = _scoring_world()
    route = _route_or_fail(world, "N-A", "N-I")
    now = _score_if_feasible(world, "INC-01", "BOAT-NEAR", None, ["W-N"], 0, route, 0)
    waited = _score_if_feasible(world, "INC-01", "BOAT-NEAR", None, ["W-N"], 10, route, 10)
    assert waited < now


def test_infeasible_pairs_never_scored() -> None:
    world = _scoring_world()
    world.edges["W-N"].status = "closed"
    bad_route = {"nodes": ["N-A", "N-I"], "edges": ["W-N"], "eta_ticks": 2, "risk": 0.9, "warnings": []}
    ok, reason = check_feasible(world, "INC-01", "BOAT-NEAR", None, ["W-N"], 0)
    assert (ok, reason) == (False, "EDGE_CLOSED:W-N")
    with pytest.raises(AssertionError):
        _score_if_feasible(world, "INC-01", "BOAT-NEAR", None, ["W-N"], 0, bad_route, 4)


# --- route_replanner thin wrapper ---


def test_shelter_options_filters_full_and_sorts_by_eta() -> None:
    world = World(
        nodes={
            "N-O": _node("N-O"),
            "N-S1": _node("N-S1", "shelter"),
            "N-S2": _node("N-S2", "shelter"),
            "N-S3": _node("N-S3", "shelter"),
        },
        edges={
            "W-1": _edge("W-1", "N-O", "N-S1", travel_time=5),
            "W-2": _edge("W-2", "N-O", "N-S2", travel_time=2),
            "W-3": _edge("W-3", "N-O", "N-S3", travel_time=3),
        },
        shelters={
            "SHELTER-01": _shelter("SHELTER-01", "N-S1", capacity=10),
            "SHELTER-02": _shelter("SHELTER-02", "N-S2", capacity=10),
            "SHELTER-03": _shelter("SHELTER-03", "N-S3", capacity=2, occupancy=2),
        },
    )
    options = shelter_options(world, "N-O", "water", 4)
    assert [sid for sid, _ in options] == ["SHELTER-02", "SHELTER-01"]  # eta 2 then 5; -03 full
    assert options[0][1]["eta_ticks"] == 2
