"""Phase 4 Step 01: flood progression + bridge closures (see
docs/phase-4-dynamic-events-replanning/step-01-flood-closures.md).

STEP 01 scope (DETECTION + REPLAN PRIMITIVES at manager level):
- StateManager.apply_reopen / apply_flood_rise + apply_event dispatch for
  BRIDGE_CLOSURE / EDGE_REOPEN / FLOOD_RISE.
- dispatch.route_replanner.replan / find_routes_using_edge.
- scenarios/bridge_closure.json fixture.

Steps 02/03/05 APPEND their sections below under their own headers; do not
rework the STEP 01 blocks. Assignment-status transitions
(REQUIRES_RECONCILIATION/CANCELLED) belong to Step 05's pipeline.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from backend.app.dispatch.route_replanner import (
    find_routes_using_edge,
    replan,
    shelter_options,
)
from backend.app.dispatch.bid_evaluator import check_feasible
from backend.app.dispatch.centralized_scheduler import CentralizedScheduler
from backend.app.dispatch.commitment_manager import (
    acknowledge,
    commit_assignment,
    reassign_shelter,
    start_progress,
    trigger_recovery,
)
from backend.app.dispatch.scheduler_interface import ProposedAssignment
from backend.app.routing.pathfinder import find_route
from backend.app.simulation.run import build_simulation, load_scenario
from backend.app.simulation.state_manager import StateManager
from backend.app.simulation.world import (
    Boat,
    Edge,
    GroundTeam,
    Incident,
    Node,
    Shelter,
    World,
)

BRIDGE_SCENARIO = (
    Path(__file__).resolve().parent.parent.parent
    / "scenarios"
    / "bridge_closure.json"
)


# --- STEP 01 helpers ----------------------------------------------------


def _node(node_id: str, kind: str = "intersection") -> Node:
    return Node(
        node_id=node_id, neighborhood="Test", kind=kind, x=0.0, y=0.0  # type: ignore[arg-type]
    )


def _edge(
    edge_id: str,
    frm: str,
    to: str,
    mode: str = "road",
    travel_time: int = 5,
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
        capacity=2,
    )


def _road_triangle() -> World:
    """A/B/C road graph: A->B->C costs 5+5=10, direct A->C costs 12."""
    return World(
        nodes={"A": _node("A"), "B": _node("B"), "C": _node("C")},
        edges={
            "R-AB": _edge("R-AB", "A", "B", "road", 5),
            "R-BC": _edge("R-BC", "B", "C", "road", 5),
            "R-AC": _edge("R-AC", "A", "C", "road", 12),
        },
    )


def _single_water_leg() -> World:
    """A->B water corridor with no alternate path (no-route topology)."""
    return World(
        nodes={"A": _node("A", "station"), "B": _node("B", "incident_site")},
        edges={"W-AB": _edge("W-AB", "A", "B", "water", 2)},
        boats={
            "BOAT-01": Boat(
                boat_id="BOAT-01", node_id="A", capacity=4,
                fuel=30.0, fuel_reserve=5.0,
            )
        },
    )


# --- STEP 01: closure detection -------------------------------------------


def test_bridge_closure_flags_active_route_same_tick() -> None:
    """Closing an edge on an active manager route is detectable same tick."""
    world = _road_triangle()
    world.teams["TEAM-01"] = GroundTeam(
        team_id="TEAM-01", node_id="A", capabilities=["ground"]
    )
    manager = StateManager(world, seed=7)
    manager.set_route("TEAM-01", ["R-AB", "R-BC"], "C", tick=1)

    manager.apply_event(
        {
            "tick": 5,
            "kind": "BRIDGE_CLOSURE",
            "payload": {"edge_id": "R-BC"},
            "event_id": "EVT-BC-1",
        }
    )

    assert world.edges["R-BC"].status == "closed"
    assert world.edges["R-BC"].last_updated_tick == 5
    # Detection primitive lists the still-affected resource ...
    assert find_routes_using_edge(manager, "R-BC") == ["TEAM-01"]
    # ... and a CLOSURE-class log names the edge with the bridge reason.
    closures = [
        entry for entry in manager.event_log
        if entry["kind"] == "CLOSURE"
        and entry["detail"].get("edge_id") == "R-BC"
    ]
    assert len(closures) == 1
    assert closures[0]["tick"] == 5
    assert closures[0]["detail"]["reason"] == "bridge"


def test_find_routes_using_edge_ignores_traversed_legs() -> None:
    """Only un-traversed (next_index..) legs count; no mutation, sorted."""
    world = _road_triangle()
    manager = StateManager(world, seed=7)
    manager.set_route("TEAM-01", ["R-AB", "R-BC"], "C", tick=1)
    manager.set_route("TEAM-02", ["R-AC"], "C", tick=1)
    # TEAM-01 already crossed R-AB; TEAM-02 never uses R-BC.
    manager.routes["TEAM-01"]["next_index"] = 1
    before = copy.deepcopy(manager.routes)

    assert find_routes_using_edge(manager, "R-AB") == []
    assert find_routes_using_edge(manager, "R-BC") == ["TEAM-01"]
    assert find_routes_using_edge(manager, "R-AC") == ["TEAM-02"]
    assert manager.routes == before


def test_plain_closure_log_detail_unchanged() -> None:
    """Existing CLOSURE path logs exactly {edge_id} (no reason key)."""
    manager = StateManager(_road_triangle(), seed=7)
    manager.apply_event(
        {
            "tick": 3,
            "kind": "CLOSURE",
            "payload": {"edge_id": "R-BC"},
            "event_id": "EVT-C-1",
        }
    )
    closures = [e for e in manager.event_log if e["kind"] == "CLOSURE"]
    assert len(closures) == 1
    assert closures[0]["detail"] == {"edge_id": "R-BC"}


# --- STEP 01: replan primitive --------------------------------------------


def test_replan_returns_route_avoiding_closed_edge() -> None:
    """replan() routes around the closure and reports OK."""
    world = _road_triangle()
    world.edges["R-BC"].status = "closed"
    route, code = replan(world, "A", "C", "road")
    assert code == "OK"
    assert route is not None
    assert route["edges"] == ["R-AC"]
    assert route["nodes"] == ["A", "C"]
    assert "R-BC" not in route["edges"]
    assert route["eta_ticks"] == 12
    assert set(route) == {"nodes", "edges", "eta_ticks", "risk", "warnings"}


def test_replan_from_mid_route_avoids_closure() -> None:
    """A resource holding at B replans B->A->C once B->C is closed."""
    world = _road_triangle()
    world.edges["R-BC"].status = "closed"
    route, code = replan(world, "B", "C", "road")
    assert code == "OK"
    assert route is not None
    assert route["edges"] == ["R-AB", "R-AC"]
    assert route["eta_ticks"] == 17


def test_replan_disputed_default_skips_allow_uses() -> None:
    """Disputed edges are skipped by default, usable with allow_disputed."""
    world = World(
        nodes={"A": _node("A"), "B": _node("B")},
        edges={"W-AB": _edge("W-AB", "A", "B", "water", 2, status="disputed")},
    )
    route, code = replan(world, "A", "B", "water")
    assert (route, code) == (None, "REPLAN_FAILED:NO_ROUTE")
    route, code = replan(world, "A", "B", "water", allow_disputed=True)
    assert code == "OK"
    assert route is not None
    assert route["edges"] == ["W-AB"]
    assert route["warnings"] == ["DISPUTED:W-AB"]


def test_replan_is_pure_and_never_raises_on_no_route() -> None:
    """Unknown nodes/mode give NO_ROUTE; world is never mutated."""
    world = _road_triangle()
    before = world.to_dict()
    assert replan(world, "A", "ZZZ", "road") == (None, "REPLAN_FAILED:NO_ROUTE")
    assert replan(world, "ZZZ", "A", "road") == (None, "REPLAN_FAILED:NO_ROUTE")
    assert replan(world, "A", "C", "rail") == (None, "REPLAN_FAILED:NO_ROUTE")
    assert world.to_dict() == before


# --- STEP 01: no alternate -> hold ----------------------------------------


def test_no_alternate_route_holds_resource_with_blocked_log() -> None:
    """replan fails closed; advance_positions holds (no teleport)."""
    world = _single_water_leg()
    manager = StateManager(world, seed=7)
    manager.set_route("BOAT-01", ["W-AB"], "B", tick=1)
    manager.apply_closure("W-AB", 2)

    route, code = replan(world, "A", "B", "water")
    assert (route, code) == (None, "REPLAN_FAILED:NO_ROUTE")

    manager.advance_positions(2)
    assert world.boats["BOAT-01"].node_id == "A"
    assert manager.routes["BOAT-01"]["next_index"] == 0
    blocked = [
        entry for entry in manager.event_log
        if entry["kind"] == "ROUTE_BLOCKED"
        and entry["detail"].get("edge_id") == "W-AB"
    ]
    assert len(blocked) == 1
    assert blocked[0]["tick"] == 2


# --- STEP 01: reopen ------------------------------------------------------


def test_reopen_restores_edge_for_optimal_routing() -> None:
    """EDGE_REOPENED edge is reused by find_route/replan when optimal."""
    world = _road_triangle()
    manager = StateManager(world, seed=7)
    manager.apply_closure("R-BC", 5)
    assert replan(world, "A", "C", "road")[1] == "OK"
    assert replan(world, "A", "C", "road")[0]["edges"] == ["R-AC"]

    manager.apply_reopen("R-BC", 12)
    assert world.edges["R-BC"].status == "open"
    assert world.edges["R-BC"].last_updated_tick == 12
    reopened = [e for e in manager.event_log if e["kind"] == "EDGE_REOPENED"]
    assert len(reopened) == 1
    assert reopened[0]["detail"] == {"edge_id": "R-BC"}

    direct = find_route(world, "A", "C", "road")
    assert direct is not None and direct["edges"] == ["R-AB", "R-BC"]
    route, code = replan(world, "A", "C", "road")
    assert code == "OK"
    assert route is not None and route["edges"] == ["R-AB", "R-BC"]


def test_reopen_unknown_edge_ignored_never_raises() -> None:
    """Unknown edge reopen logs IGNORED and changes nothing."""
    manager = StateManager(_road_triangle(), seed=7)
    manager.apply_reopen("R-NOPE", 4)
    ignored = [
        e for e in manager.event_log
        if e["kind"] == "IGNORED" and e["detail"].get("edge_id") == "R-NOPE"
    ]
    assert len(ignored) == 1
    assert all(e.status == "open" for e in manager.world.edges.values())


# --- STEP 01: flood rise --------------------------------------------------


def test_flood_rise_bumps_risk_with_single_log() -> None:
    """Risk rises, last_updated_tick advances, exactly one FLOOD_RISE log."""
    manager = StateManager(_single_water_leg(), seed=7)
    manager.apply_flood_rise(["W-AB"], 0.3, tick=4)
    assert manager.world.edges["W-AB"].risk_level == pytest.approx(0.4)
    assert manager.world.edges["W-AB"].last_updated_tick == 4
    rises = [e for e in manager.event_log if e["kind"] == "FLOOD_RISE"]
    assert len(rises) == 1
    assert rises[0]["tick"] == 4
    assert rises[0]["detail"] == {"edge_ids": ["W-AB"], "risk_delta": 0.3}


def test_flood_rise_clamps_and_skips_unknown() -> None:
    """Risk clamps to [0, 1]; unknown edges are skipped, never raise."""
    manager = StateManager(_single_water_leg(), seed=7)
    manager.world.edges["W-AB"].risk_level = 0.9
    manager.apply_flood_rise(["W-AB", "W-NOPE"], 0.5, tick=6)
    assert manager.world.edges["W-AB"].risk_level == 1.0
    assert manager.world.edges["W-AB"].last_updated_tick == 6
    manager.apply_flood_rise(["W-AB"], -2.0, tick=7)
    assert manager.world.edges["W-AB"].risk_level == 0.0
    assert len([e for e in manager.event_log if e["kind"] == "FLOOD_RISE"]) == 2


def test_event_dispatch_new_kinds_and_bad_payloads() -> None:
    """EDGE_REOPEN/FLOOD_RISE dispatch; malformed payloads are IGNORED."""
    manager = StateManager(_road_triangle(), seed=7)
    manager.apply_event(
        {"tick": 8, "kind": "FLOOD_RISE",
         "payload": {"edge_ids": ["R-AB", "R-BC"], "risk_delta": 0.25},
         "event_id": "EVT-FR-1"}
    )
    assert manager.world.edges["R-AB"].risk_level == pytest.approx(0.35)
    assert manager.world.edges["R-BC"].risk_level == pytest.approx(0.35)
    manager.apply_event(
        {"tick": 9, "kind": "EDGE_REOPEN",
         "payload": {"edge_id": "R-BC"}, "event_id": "EVT-RO-1"}
    )
    assert manager.world.edges["R-BC"].last_updated_tick == 9
    assert manager.world.edges["R-BC"].status == "open"

    n_ignored = lambda: sum(1 for e in manager.event_log if e["kind"] == "IGNORED")
    before = n_ignored()
    manager.apply_event(
        {"tick": 10, "kind": "FLOOD_RISE",
         "payload": {"edge_ids": "R-AB", "risk_delta": 0.1},
         "event_id": "EVT-FR-BAD"}
    )
    manager.apply_event(
        {"tick": 10, "kind": "FLOOD_RISE",
         "payload": {"edge_ids": ["R-AB"], "risk_delta": "high"},
         "event_id": "EVT-FR-BAD2"}
    )
    manager.apply_event(
        {"tick": 10, "kind": "EDGE_REOPEN", "payload": {}, "event_id": "EVT-RO-BAD"}
    )
    manager.apply_event(
        {"tick": 10, "kind": "BRIDGE_CLOSURE", "payload": {},
         "event_id": "EVT-BC-BAD"}
    )
    assert n_ignored() == before + 4
    assert manager.world.edges["R-AB"].status == "open"


# --- STEP 01: bridge_closure.json fixture --------------------------------


def test_bridge_closure_scenario_closure_then_reopen() -> None:
    """Fixture refs valid; W-04 closes tick 5 (BOAT-02 held), reopens 12."""
    data = load_scenario(BRIDGE_SCENARIO)
    simulation = build_simulation(copy.deepcopy(data), seed=7)
    simulation.run(30)

    closures = [
        e for e in simulation.manager.event_log
        if e["kind"] == "CLOSURE" and e["detail"].get("edge_id") == "W-04"
    ]
    assert len(closures) == 1
    assert closures[0]["tick"] == 5
    assert closures[0]["detail"]["reason"] == "bridge"

    blocked = [
        e for e in simulation.manager.event_log
        if e["kind"] == "ROUTE_BLOCKED"
        and e["detail"].get("resource_id") == "BOAT-02"
        and e["detail"].get("edge_id") == "W-04"
    ]
    assert blocked, "expected BOAT-02 to hold on closed W-04"
    assert min(e["tick"] for e in blocked) == 5

    reopened = [
        e for e in simulation.manager.event_log if e["kind"] == "EDGE_REOPENED"
    ]
    assert len(reopened) == 1
    assert reopened[0]["tick"] == 12
    assert reopened[0]["detail"] == {"edge_id": "W-04"}

    assert simulation.world.edges["W-04"].status == "open"
    assert simulation.world.edges["W-04"].last_updated_tick == 12
    assert all(
        incident.status == "SERVED"
        for incident in simulation.world.incidents.values()
    )


# --- STEP 02: boat failure + passenger recovery ----------------------------


BOAT_FAILURE_SCENARIO = (
    Path(__file__).resolve().parent.parent.parent
    / "scenarios"
    / "boat_failure.json"
)


def _failure_world() -> World:
    """S -W-SI-> I -W-IH-> H water corridor, two boats, one shelter."""
    return World(
        nodes={
            "S": _node("S", "station"),
            "I": _node("I", "incident_site"),
            "H": _node("H", "shelter"),
        },
        edges={
            "W-SI": _edge("W-SI", "S", "I", "water", 1),
            "W-IH": _edge("W-IH", "I", "H", "water", 1),
        },
        incidents={
            "INC-01": Incident(
                incident_id="INC-01", node_id="I", urgency=4, people=4,
                required_capabilities=["boat"],
            ),
        },
        boats={
            "BOAT-01": Boat(
                boat_id="BOAT-01", node_id="S", capacity=5,
                fuel=30.0, fuel_reserve=5.0,
            ),
            "BOAT-02": Boat(
                boat_id="BOAT-02", node_id="S", capacity=5,
                fuel=30.0, fuel_reserve=5.0,
            ),
        },
        shelters={
            "SH-01": Shelter(shelter_id="SH-01", node_id="H", capacity=8),
        },
    )


def _commit_boat_01(
    manager: StateManager, assignments: dict, seen: dict,
    tick: int = 2, seats: int = 4, aid: str = "ASN-00001",
) -> None:
    proposal = ProposedAssignment(
        proposal_id=f"PROP-{aid}", incident_id="INC-01",
        resource_id="BOAT-01", resource_kind="boat",
        shelter_id="SH-01", seats=seats, route_edge_ids=["W-SI"],
        eta_ticks=1, cost=1.0, created_tick=tick,
    )
    assignment, code = commit_assignment(
        manager, proposal, tick, aid, assignments, seen
    )
    assert code == "OK" and assignment is not None


def test_fail_empty_boat_cancels_without_recovery() -> None:
    """Failing an empty committed boat cancels cleanly, no recovery incident."""
    world = _failure_world()
    manager = StateManager(world, seed=11)
    assignments: dict = {}
    seen: dict = {}
    _commit_boat_01(manager, assignments, seen)
    assert world.incidents["INC-01"].status == "ASSIGNED"

    incident, code = trigger_recovery(manager, assignments, seen, "BOAT-01", 6)

    assert incident is None
    assert code == "OK:NO_PASSENGERS"
    assert all(inc.kind == "standard" for inc in world.incidents.values())
    failed = [e for e in manager.event_log if e["kind"] == "BOAT_FAILED"]
    assert len(failed) == 1
    assert failed[0]["tick"] == 6
    assert failed[0]["detail"] == {
        "boat_id": "BOAT-01", "passengers": 0,
        "assignment_id": "ASN-00001",
    }
    cancelled = [e for e in manager.event_log if e["kind"] == "CANCELLED"]
    assert len(cancelled) == 1
    assert cancelled[0]["detail"]["reason"] == "CANCELLED:RESOURCE_FAILED"
    assert assignments["ASN-00001"].status == "CANCELLED"
    assert (
        assignments["ASN-00001"].history[-1]["reason"]
        == "CANCELLED:RESOURCE_FAILED"
    )
    boat = world.boats["BOAT-01"]
    assert boat.status == "FAILED"
    assert boat.assignment_id is None
    assert boat.passengers == 0
    assert boat.needs_recovery is False
    # Original incident is reopened for reassignment, not served.
    assert world.incidents["INC-01"].status == "OPEN"


def test_fail_boat_with_passengers_triggers_recovery() -> None:
    """4 aboard -> recovery incident with 4 people; failed boat keeps its 4."""
    world = _failure_world()
    manager = StateManager(world, seed=11)
    assignments: dict = {}
    seen: dict = {}
    _commit_boat_01(manager, assignments, seen)
    ok, _ = manager.board_boat("BOAT-01", 4, tick=4, actor="engine")
    assert ok
    world.boats["BOAT-01"].node_id = "I"  # mid-transport at the scene node

    incident, code = trigger_recovery(manager, assignments, seen, "BOAT-01", 6)

    assert code == "OK" and incident is not None
    assert incident.incident_id == "REC-BOAT-01-0006"
    assert incident.people == 4
    assert incident.kind == "recovery"
    assert incident.caused_by == "ASN-00001"
    assert incident.urgency == 5
    assert incident.required_capabilities == ["boat"]
    assert incident.node_id == "I"
    assert incident.status == "OPEN"
    assert world.incidents["REC-BOAT-01-0006"].people == 4
    triggered = [
        e for e in manager.event_log if e["kind"] == "RECOVERY_TRIGGERED"
    ]
    assert len(triggered) == 1
    assert triggered[0]["tick"] == 6
    assert triggered[0]["detail"] == {
        "incident_id": "REC-BOAT-01-0006", "node": "I",
        "people": 4, "caused_by": "ASN-00001",
    }
    opened = [
        e for e in manager.event_log
        if e["kind"] == "INCIDENT_STATUS"
        and e["detail"].get("incident_id") == "REC-BOAT-01-0006"
    ]
    assert len(opened) == 1
    assert opened[0]["detail"]["to"] == "OPEN"
    # Passengers are never deleted: still aboard, flagged, never served.
    boat = world.boats["BOAT-01"]
    assert boat.status == "FAILED"
    assert boat.passengers == 4
    assert boat.needs_recovery is True
    assert boat.assignment_id is None
    assert world.incidents["INC-01"].status == "OPEN"
    assert assignments["ASN-00001"].status == "CANCELLED"


def test_failed_boat_rejected_and_never_proposed() -> None:
    """FAILED hull is infeasible and propose() only offers the healthy boat."""
    world = _failure_world()
    manager = StateManager(world, seed=11)
    assignments: dict = {}
    seen: dict = {}
    _commit_boat_01(manager, assignments, seen)
    ok, _ = manager.board_boat("BOAT-01", 4, tick=4, actor="engine")
    assert ok
    world.boats["BOAT-01"].node_id = "I"
    incident, code = trigger_recovery(manager, assignments, seen, "BOAT-01", 6)
    assert code == "OK" and incident is not None

    ok, gate = check_feasible(
        world, "REC-BOAT-01-0006", "BOAT-01", "SH-01", ["W-SI"], 7
    )
    assert (ok, gate) == (False, "RESOURCE_UNAVAILABLE")

    proposals = CentralizedScheduler().propose(world, 7)
    assert all(p.resource_id != "BOAT-01" for p in proposals)
    # Recovery rides the normal pipeline: healthy BOAT-02 is offered it.
    rec = [p for p in proposals if p.incident_id == "REC-BOAT-01-0006"]
    assert len(rec) == 1
    assert rec[0].resource_id == "BOAT-02"


def test_boat_failure_event_dispatch_and_unknown_boat() -> None:
    """BOAT_FAILURE dispatches via apply_event; unknown boats never raise."""
    world = _failure_world()
    manager = StateManager(world, seed=11)
    manager.apply_event(
        {"tick": 6, "kind": "BOAT_FAILURE",
         "payload": {"boat_id": "BOAT-01"}, "event_id": "EVT-BF-T"}
    )
    assert world.boats["BOAT-01"].status == "FAILED"
    assert any(e["kind"] == "BOAT_FAILED" for e in manager.event_log)

    outcome = manager.fail_boat("BOAT-99", 7)
    assert outcome["error"] == "UNKNOWN_BOAT"
    ignored = [
        e for e in manager.event_log
        if e["kind"] == "IGNORED" and e["detail"].get("boat_id") == "BOAT-99"
    ]
    assert len(ignored) == 1

    incident, code = trigger_recovery(manager, {}, {}, "BOAT-99", 7)
    assert (incident, code) == (None, "UNKNOWN_BOAT")

    n_ignored = lambda: sum(1 for e in manager.event_log if e["kind"] == "IGNORED")
    before = n_ignored()
    manager.apply_event(
        {"tick": 8, "kind": "BOAT_FAILURE",
         "payload": {}, "event_id": "EVT-BF-BAD"}
    )
    assert n_ignored() == before + 1


def test_boat_failure_scenario_fails_carrying_boat_while_healthy_boat_serves() -> None:
    """Fixture refs valid; BOAT-01 fails at tick 6 carrying 4, BOAT-02 serves on.

    STEP-05 UPDATE (replanning pipeline now wired in the engine loop):
    the tick-6 ``BOAT_FAILURE`` goes through ``trigger_recovery`` (not
    bare ``fail_boat``), so a recovery incident is raised and the
    healthy boat evacuates the hull via TRANSFER. End state therefore
    shows the failed boat EMPTIED (passengers 0, needs_recovery False)
    with the recovery incident SERVED — passengers are rescued, never
    stranded or double-counted — instead of the pre-pipeline
    stranded-forever assertion.
    """
    data = load_scenario(BOAT_FAILURE_SCENARIO)
    node_ids = {node["node_id"] for node in data["nodes"]}
    for edge in data["edges"]:
        assert edge["from_node"] in node_ids
        assert edge["to_node"] in node_ids
    for incident in data["incidents"]:
        assert incident["node_id"] in node_ids
    for boat in data["boats"]:
        assert boat["node_id"] in node_ids
    for shelter in data["shelters"]:
        assert shelter["node_id"] in node_ids
    failures = [e for e in data["events"] if e["kind"] == "BOAT_FAILURE"]
    assert len(failures) == 1
    assert failures[0]["tick"] == 6
    assert failures[0]["payload"] == {"boat_id": "BOAT-01"}
    assert len(data["boats"]) >= 2

    simulation = build_simulation(copy.deepcopy(data))
    simulation.run(30)

    failed = [
        e for e in simulation.manager.event_log
        if e["kind"] == "BOAT_FAILED"
        and e["detail"].get("boat_id") == "BOAT-01"
    ]
    assert len(failed) == 1
    assert failed[0]["tick"] == 6
    assert failed[0]["detail"]["passengers"] == 4
    boat = simulation.world.boats["BOAT-01"]
    assert boat.status == "FAILED"
    # STEP-05 UPDATE: the stranded passengers are evacuated by the
    # recovery run (TRANSFER), so the hull ends empty and cleared.
    assert boat.passengers == 0
    assert boat.needs_recovery is False
    transfers = [
        e for e in simulation.manager.event_log
        if e["kind"] == "TRANSFER"
        and e["detail"].get("from_boat") == "BOAT-01"
    ]
    assert len(transfers) == 1
    assert transfers[0]["detail"]["people"] == 4
    recoveries = [
        incident for incident in simulation.world.incidents.values()
        if incident.kind == "recovery"
    ]
    assert len(recoveries) == 1
    assert recoveries[0].caused_by == "ASN-00001"
    assert recoveries[0].status == "SERVED"
    # The original incident is re-served through a linked replacement.
    assert simulation.world.incidents["INC-01"].status == "SERVED"
    chains = [
        e for e in simulation.manager.event_log
        if e["kind"] == "REPLAN_CHAIN"
        and e["detail"].get("old_assignment_id") == "ASN-00001"
    ]
    assert len(chains) == 1
    # Healthy boat kept serving through the normal pipeline.
    assert simulation.world.boats["BOAT-02"].status == "AVAILABLE"
    assert simulation.world.incidents["INC-02"].status == "SERVED"


# --- STEP 03: shelter overflow + destination swap -------------------------

SHELTER_OVERFLOW_SCENARIO = (
    Path(__file__).resolve().parent.parent.parent
    / "scenarios"
    / "shelter_overflow.json"
)


def _boat(boat_id: str, node_id: str = "S", capacity: int = 4) -> Boat:
    return Boat(
        boat_id=boat_id, node_id=node_id, capacity=capacity,
        fuel=30.0, fuel_reserve=5.0,
    )


def _shelter_incident(incident_id: str, people: int = 2) -> Incident:
    return Incident(
        incident_id=incident_id, node_id="I", urgency=3, people=people,
        required_capabilities=["boat"],
    )


def _overflow_world(
    shelters: dict[str, Shelter],
    boat_ids: list[str],
    incidents: dict[str, Incident],
) -> World:
    """S -> I -> H1 / H2 water corridor with caller-supplied shelters/boats."""
    return World(
        nodes={
            "S": _node("S", "station"),
            "I": _node("I", "incident_site"),
            "H1": _node("H1", "shelter"),
            "H2": _node("H2", "shelter"),
        },
        edges={
            "W-SI": _edge("W-SI", "S", "I", "water", 1),
            "W-IH1": _edge("W-IH1", "I", "H1", "water", 1),
            "W-IH2": _edge("W-IH2", "I", "H2", "water", 2),
        },
        incidents=incidents,
        boats={bid: _boat(bid) for bid in boat_ids},
        shelters=shelters,
    )


def _commit_shelter_leg(
    manager: StateManager, assignments: dict, seen: dict,
    aid: str, boat_id: str, incident_id: str, shelter_id: str,
    seats: int, edges: list[str], tick: int,
) -> None:
    proposal = ProposedAssignment(
        proposal_id=f"PROP-{aid}", incident_id=incident_id,
        resource_id=boat_id, resource_kind="boat",
        shelter_id=shelter_id, seats=seats, route_edge_ids=list(edges),
        eta_ticks=1, cost=1.0, created_tick=tick,
    )
    assignment, code = commit_assignment(
        manager, proposal, tick, aid, assignments, seen
    )
    assert code == "OK" and assignment is not None


def _assert_shelter_invariant(world: World) -> None:
    for sid, shelter in world.shelters.items():
        held = shelter.occupancy + sum(shelter.reservations.values())
        assert held <= shelter.capacity, (sid, shelter.occupancy, shelter.reservations)


def test_shelter_full_event_marks_not_accepting_and_logs() -> None:
    """apply_shelter_full stops reservations; unknown shelters never raise."""
    world = _overflow_world(
        {"SH-01": Shelter(shelter_id="SH-01", node_id="H1", capacity=4)},
        ["BOAT-01"], {},
    )
    manager = StateManager(world, seed=21)
    manager.apply_shelter_full("SH-01", 5)

    assert world.shelters["SH-01"].accepting is False
    assert world.shelter_remaining("SH-01") == 0
    full = [e for e in manager.event_log if e["kind"] == "SHELTER_FULL"]
    assert len(full) == 1
    assert full[0]["tick"] == 5
    assert full[0]["detail"] == {
        "shelter_id": "SH-01", "occupancy": 0, "capacity": 4,
    }

    # Same path via apply_event dispatch.
    world.shelters["SH-02"] = Shelter(shelter_id="SH-02", node_id="H2", capacity=6)
    manager.apply_event(
        {"tick": 6, "kind": "SHELTER_FULL",
         "payload": {"shelter_id": "SH-02"}, "event_id": "EVT-SF-T"}
    )
    assert world.shelters["SH-02"].accepting is False
    assert len([e for e in manager.event_log if e["kind"] == "SHELTER_FULL"]) == 2

    # Unknown shelters and bad payloads log IGNORED and never raise.
    n_ignored = lambda: sum(1 for e in manager.event_log if e["kind"] == "IGNORED")
    before = n_ignored()
    manager.apply_shelter_full("SH-99", 7)
    manager.apply_event(
        {"tick": 7, "kind": "SHELTER_FULL",
         "payload": {}, "event_id": "EVT-SF-BAD"}
    )
    assert n_ignored() == before + 2


def test_checkin_at_capacity_flips_accepting_and_blocks_reserve() -> None:
    """Occupancy reaching capacity auto-marks full; round-trip keeps the flag."""
    world = _overflow_world(
        {"SH-01": Shelter(shelter_id="SH-01", node_id="H1", capacity=2)},
        ["BOAT-01"], {},
    )
    shelter = world.shelters["SH-01"]
    assert shelter.reserve("ASN-00001", 2, tick=1) is True
    assert shelter.checkin("ASN-00001", tick=2) == 2
    assert shelter.occupancy == 2
    assert shelter.accepting is False
    assert any(entry.get("event") == "shelter_full" for entry in shelter.history)

    assert shelter.reserve("ASN-00002", 1, tick=3) is False
    assert shelter.history[-1]["reason"] == "REJECTED:SHELTER_NOT_ACCEPTING"
    assert world.shelter_remaining("SH-01") == 0

    # Round-trip compat: old docs without the flag default to True.
    assert Shelter(shelter_id="SH-X", node_id="H1", capacity=3).accepting is True
    restored = Shelter.model_validate(shelter.model_dump(mode="json"))
    assert restored.accepting is False


def test_mid_transport_reassign_moves_hold_with_invariant_every_tick() -> None:
    """Full shelter mid-transport -> hold moves, invariant holds every tick."""
    world = _overflow_world(
        {
            "SH-01": Shelter(shelter_id="SH-01", node_id="H1", capacity=2),
            "SH-02": Shelter(shelter_id="SH-02", node_id="H2", capacity=6),
        },
        ["BOAT-01"],
        {"INC-01": _shelter_incident("INC-01")},
    )
    manager = StateManager(world, seed=21)
    assignments: dict = {}
    seen: dict = {}
    _commit_shelter_leg(
        manager, assignments, seen,
        "ASN-00001", "BOAT-01", "INC-01", "SH-01", 2, ["W-SI", "W-IH1"], 1,
    )
    assert world.shelters["SH-01"].reservations == {"ASN-00001": 2}
    assert acknowledge(manager, assignments, "ASN-00001", 1) == (True, "OK")
    assert start_progress(manager, assignments, "ASN-00001", 1) == (True, "OK")

    ok, _ = manager.board_boat("BOAT-01", 2, tick=2, actor="engine")
    assert ok
    manager.set_route("BOAT-01", ["W-SI", "W-IH1"], "H1", tick=2)
    manager.advance_positions(2)
    assert world.boats["BOAT-01"].node_id == "I"  # mid-transport at the scene
    _assert_shelter_invariant(world)

    manager.apply_event(
        {"tick": 3, "kind": "SHELTER_FULL",
         "payload": {"shelter_id": "SH-01"}, "event_id": "EVT-SF-01"}
    )
    ok, code = reassign_shelter(
        manager, assignments, "ASN-00001", "SH-02", ["W-IH2"], 3
    )
    assert (ok, code) == (True, "OK")
    assert world.shelters["SH-01"].reservations == {}
    assert world.shelters["SH-02"].reservations == {"ASN-00001": 2}
    moved = assignments["ASN-00001"]
    assert moved.shelter_id == "SH-02"
    assert moved.route_edge_ids == ["W-IH2"]
    assert manager.routes["BOAT-01"]["dest"] == "H2"
    assert manager.routes["BOAT-01"]["edge_ids"] == ["W-IH2"]
    last = moved.history[-1]
    assert last["from"] == "SH-01" and last["to"] == "SH-02"
    assert last["reason"] == "SHELTER_FULL reassigned SH-01->SH-02"
    assert last["tick"] == 3 and last["actor"] == "dispatch"
    reassigned = [
        e for e in manager.event_log if e["kind"] == "SHELTER_REASSIGNED"
    ]
    assert len(reassigned) == 1
    assert reassigned[0]["detail"]["assignment_id"] == "ASN-00001"

    for tick in (4, 5, 6):
        manager.advance_positions(tick)
        _assert_shelter_invariant(world)
    assert world.boats["BOAT-01"].node_id == "H2"
    ok, _ = manager.checkin_shelter("SH-02", "ASN-00001", 6)
    assert ok
    assert world.shelters["SH-02"].occupancy == 2
    _assert_shelter_invariant(world)


def _race_world() -> World:
    """S -> I -> HA / HB / HC water corridor, three boats, three incidents."""
    return World(
        nodes={
            "S": _node("S", "station"),
            "I": _node("I", "incident_site"),
            "HA": _node("HA", "shelter"),
            "HB": _node("HB", "shelter"),
            "HC": _node("HC", "shelter"),
        },
        edges={
            "W-SI": _edge("W-SI", "S", "I", "water", 1),
            "W-IA": _edge("W-IA", "I", "HA", "water", 1),
            "W-IB": _edge("W-IB", "I", "HB", "water", 1),
            "W-IC": _edge("W-IC", "I", "HC", "water", 2),
        },
        incidents={
            "INC-01": _shelter_incident("INC-01"),
            "INC-02": _shelter_incident("INC-02"),
            "INC-03": _shelter_incident("INC-03"),
        },
        boats={
            "BOAT-01": _boat("BOAT-01"),
            "BOAT-02": _boat("BOAT-02"),
            "BOAT-03": _boat("BOAT-03"),
        },
        shelters={
            "SH-A": Shelter(shelter_id="SH-A", node_id="HA", capacity=4),
            "SH-B": Shelter(shelter_id="SH-B", node_id="HB", capacity=4),
            "SH-C": Shelter(shelter_id="SH-C", node_id="HC", capacity=6),
        },
    )


def test_two_boats_race_last_bed_one_wins_other_rerouted() -> None:
    """One reassignment wins the last bed; the loser fails cleanly, reroutes."""
    world = _race_world()
    manager = StateManager(world, seed=21)
    assignments: dict = {}
    seen: dict = {}
    _commit_shelter_leg(
        manager, assignments, seen,
        "ASN-A", "BOAT-01", "INC-01", "SH-B", 2, ["W-SI", "W-IB"], 1,
    )
    _commit_shelter_leg(
        manager, assignments, seen,
        "ASN-B1", "BOAT-02", "INC-02", "SH-A", 2, ["W-SI", "W-IA"], 1,
    )
    _commit_shelter_leg(
        manager, assignments, seen,
        "ASN-B2", "BOAT-03", "INC-03", "SH-A", 2, ["W-SI", "W-IA"], 1,
    )
    _assert_shelter_invariant(world)

    manager.apply_event(
        {"tick": 3, "kind": "SHELTER_FULL",
         "payload": {"shelter_id": "SH-A"}, "event_id": "EVT-SF-RACE"}
    )
    # First reassignment wins the last bed at SH-B (2 of 4 held, 2 left).
    assert reassign_shelter(
        manager, assignments, "ASN-B1", "SH-B", ["W-IB"], 3
    ) == (True, "OK")
    assert world.shelters["SH-B"].reservations == {"ASN-A": 2, "ASN-B1": 2}
    _assert_shelter_invariant(world)

    # A raw second reserve for the same bed fails with no mutation.
    ok, _ = manager.reserve_shelter("SH-B", "ASN-RACE", 2, 3)
    assert ok is False
    _assert_shelter_invariant(world)

    # So does the second reassignment: old hold untouched, no over-reserve.
    assert reassign_shelter(
        manager, assignments, "ASN-B2", "SH-B", ["W-IB"], 3
    ) == (False, "REASSIGN_NO_SEATS")
    assert world.shelters["SH-A"].reservations == {"ASN-B2": 2}
    _assert_shelter_invariant(world)

    # Loser reroutes to the shelter with room.
    assert reassign_shelter(
        manager, assignments, "ASN-B2", "SH-C", ["W-IC"], 4
    ) == (True, "OK")
    assert assignments["ASN-B2"].shelter_id == "SH-C"
    assert world.shelters["SH-A"].reservations == {}
    assert world.shelters["SH-C"].reservations == {"ASN-B2": 2}
    _assert_shelter_invariant(world)


def test_no_capacity_anywhere_old_hold_intact_and_no_commit() -> None:
    """Nowhere to go -> swap fails, old hold kept, no commit to full shelter."""
    world = _overflow_world(
        {
            "SH-01": Shelter(shelter_id="SH-01", node_id="H1", capacity=2),
            "SH-02": Shelter(shelter_id="SH-02", node_id="H2", capacity=2),
        },
        ["BOAT-01", "BOAT-02", "BOAT-09"],
        {
            "INC-01": _shelter_incident("INC-01"),
            "INC-02": _shelter_incident("INC-02"),
            "INC-09": _shelter_incident("INC-09"),
        },
    )
    manager = StateManager(world, seed=21)
    assignments: dict = {}
    seen: dict = {}
    _commit_shelter_leg(
        manager, assignments, seen,
        "ASN-A", "BOAT-01", "INC-01", "SH-01", 2, ["W-SI", "W-IH1"], 1,
    )
    assert acknowledge(manager, assignments, "ASN-A", 1) == (True, "OK")
    assert start_progress(manager, assignments, "ASN-A", 1) == (True, "OK")
    _commit_shelter_leg(
        manager, assignments, seen,
        "ASN-K", "BOAT-02", "INC-02", "SH-02", 2, ["W-SI", "W-IH2"], 1,
    )
    manager.apply_event(
        {"tick": 3, "kind": "SHELTER_FULL",
         "payload": {"shelter_id": "SH-01"}, "event_id": "EVT-SF-NONE"}
    )

    assert reassign_shelter(
        manager, assignments, "ASN-A", "SH-02", ["W-IH2"], 3
    ) == (False, "REASSIGN_NO_SEATS")
    assert world.shelters["SH-01"].reservations == {"ASN-A": 2}
    assert world.shelters["SH-02"].reservations == {"ASN-K": 2}
    _assert_shelter_invariant(world)

    # Explicit NO_SHELTER path: feasibility refuses the full shelter ...
    assert check_feasible(
        world, "INC-01", "BOAT-09", "SH-01", ["W-SI"], 4
    ) == (False, "SHELTER_FULL")
    assert check_feasible(
        world, "INC-01", "BOAT-09", "SH-02", ["W-SI"], 4
    ) == (False, "SHELTER_FULL")
    # ... and no new assignment commits to it.
    proposal = ProposedAssignment(
        proposal_id="PROP-NOSHELTER", incident_id="INC-09",
        resource_id="BOAT-09", resource_kind="boat",
        shelter_id="SH-01", seats=2, route_edge_ids=["W-SI"],
        eta_ticks=1, cost=1.0, created_tick=4,
    )
    assignment, code = commit_assignment(
        manager, proposal, 4, "ASN-00009", assignments, seen
    )
    assert assignment is None
    assert code == "SHELTER_FULL_AT_COMMIT"
    assert "ASN-00009" not in assignments
    _assert_shelter_invariant(world)


def test_accepting_false_skipped_by_shelter_options() -> None:
    """Flagged-full shelters are skipped even when physically roomy."""
    world = _overflow_world(
        {
            "SH-01": Shelter(shelter_id="SH-01", node_id="H1", capacity=6),
            "SH-02": Shelter(shelter_id="SH-02", node_id="H2", capacity=6),
        },
        ["BOAT-01"], {},
    )
    manager = StateManager(world, seed=21)
    manager.apply_shelter_full("SH-01", 2)
    assert [sid for sid, _ in shelter_options(world, "I", "water", 2)] == ["SH-02"]

    world.shelters["SH-01"].accepting = True
    assert [sid for sid, _ in shelter_options(world, "I", "water", 2)] == [
        "SH-01", "SH-02",
    ]


def test_shelter_overflow_scenario_full_fires_mid_transport() -> None:
    """Fixture refs valid; SHELTER-01 fills at tick 5 under a live transport.

    STEP-05 UPDATE: the tick-5 ``SHELTER_FULL`` now triggers the
    replanning pipeline the same tick, so BOAT-01's live hold moves to
    SHELTER-02 immediately (``SHELTER_REASSIGNED`` + ``REPLAN``) instead
    of lingering at SHELTER-01. Later incidents may strand when both
    shelters end full — the invariant (never over-reserve) still holds
    every tick; completion is not promised here.
    """
    data = load_scenario(SHELTER_OVERFLOW_SCENARIO)
    node_ids = {node["node_id"] for node in data["nodes"]}
    for edge in data["edges"]:
        assert edge["from_node"] in node_ids
        assert edge["to_node"] in node_ids
    for incident in data["incidents"]:
        assert incident["node_id"] in node_ids
    for boat in data["boats"]:
        assert boat["node_id"] in node_ids
    for shelter in data["shelters"]:
        assert shelter["node_id"] in node_ids
    full_events = [e for e in data["events"] if e["kind"] == "SHELTER_FULL"]
    assert len(full_events) == 1
    assert full_events[0]["tick"] == 5
    assert full_events[0]["payload"] == {"shelter_id": "SHELTER-01"}
    assert len(data["shelters"]) == 2
    assert len(data["boats"]) >= 2

    simulation = build_simulation(copy.deepcopy(data))
    simulation.run(5)
    # BOAT-01 boards 4 at tick 4 and still holds its seats at 5 — now at
    # SHELTER-02: the tick-5 SHELTER_FULL swapped the live reservation
    # there via the Step 05 pipeline (same tick as the event).
    assert simulation.world.boats["BOAT-01"].passengers == 4
    assert simulation.world.shelters["SHELTER-01"].reservations == {}
    assert simulation.world.shelters["SHELTER-02"].reservations == {
        "ASN-00002": 2, "ASN-00001": 4,
    }
    assert simulation.world.shelters["SHELTER-01"].accepting is False
    full_logs = [
        e for e in simulation.manager.event_log if e["kind"] == "SHELTER_FULL"
    ]
    assert len(full_logs) == 1
    assert full_logs[0]["tick"] == 5
    swaps = [
        e for e in simulation.manager.event_log
        if e["kind"] == "SHELTER_REASSIGNED"
        and e["detail"].get("assignment_id") == "ASN-00001"
    ]
    assert len(swaps) == 1
    assert swaps[0]["tick"] == 5
    assert swaps[0]["detail"]["from"] == "SHELTER-01"
    assert swaps[0]["detail"]["to"] == "SHELTER-02"

    simulation.run(30)
    for shelter in simulation.world.shelters.values():
        held = shelter.occupancy + sum(shelter.reservations.values())
        assert held <= shelter.capacity


# --- STEP 05: replanning pipeline + combined disaster ---------------------
# Gate for docs/phase-4-dynamic-events-replanning/step-05 plus the phase
# gate (99-phase-testing.md): the tick-40 combined run under BOTH
# strategies, the per-tick overflow invariant, and unit pins for every
# new engine branch (COMMS_NOTE, REPORT, suspend-on-no-alternate,
# REPLAN_FAILED terminal, mixed-code cancel, own-hold credit).

COMBINED_SCENARIO = (
    Path(__file__).resolve().parent.parent.parent
    / "scenarios"
    / "combined_disaster.json"
)

COMMS_PARTITION_MESSAGE = (
    "BOAT-03 unreachable (partition simulated in Phase 5): "
    "outbound messages queued, no state assumed delivered"
)


def _run_combined(strategy: str):
    """Run combined_disaster.json to completion under ``strategy``."""
    from backend.app.simulation.engine import Simulation

    data = load_scenario(COMBINED_SCENARIO)
    simulation = build_simulation(copy.deepcopy(data), strategy=strategy)
    simulation.run(int(data.get("ticks", 120)))
    return simulation


def _kinds(simulation, kind: str, tick: int | None = None) -> list[dict]:
    entries = [
        entry for entry in simulation.manager.event_log if entry["kind"] == kind
    ]
    if tick is not None:
        entries = [entry for entry in entries if entry["tick"] == tick]
    return entries


@pytest.mark.parametrize("strategy", ["centralized", "negotiation"])
def test_combined_tick40_disruptions_all_bite(strategy: str) -> None:
    """All five tick-40 events land, and each disruption actually bites."""
    simulation = _run_combined(strategy)
    world = simulation.world

    closures = _kinds(simulation, "CLOSURE", 40)
    assert len(closures) == 1
    assert closures[0]["detail"] == {"edge_id": "W-03", "reason": "bridge"}
    assert world.edges["W-03"].status == "closed"

    failed = _kinds(simulation, "BOAT_FAILED", 40)
    assert len(failed) == 1
    assert failed[0]["detail"]["boat_id"] == "BOAT-02"
    assert failed[0]["detail"]["passengers"] > 0

    full = _kinds(simulation, "SHELTER_FULL", 40)
    assert len(full) == 1
    assert full[0]["detail"]["shelter_id"] == "SHELTER-01"

    arrivals = _kinds(simulation, "INCIDENT_ARRIVAL", 40)
    assert any(
        entry["detail"].get("incident_id") == "INC-07" for entry in arrivals
    )
    assert world.incidents["INC-07"].urgency == 5

    notes = _kinds(simulation, "COMMS_NOTE", 40)
    assert len(notes) == 1
    assert notes[0]["detail"] == {"message": COMMS_PARTITION_MESSAGE}

    # Each disruption bites a live mission: the closure replans a route
    # that used W-03, the failed boat carried passengers, the full
    # shelter held a live reservation (swapped away same tick).
    route_replans = [
        entry for entry in _kinds(simulation, "REPLAN", 40)
        if "W-03" in entry["detail"].get("old_route", [])
    ]
    assert len(route_replans) == 1
    shelter_swaps = [
        entry for entry in _kinds(simulation, "REPLAN", 40)
        if entry["detail"].get("old_shelter") == "SHELTER-01"
    ]
    assert len(shelter_swaps) == 1


@pytest.mark.parametrize("strategy", ["centralized", "negotiation"])
def test_combined_recovery_served_exactly_once(strategy: str) -> None:
    """Recovery incident exists, commits, and its people serve exactly once."""
    simulation = _run_combined(strategy)

    recoveries = [
        incident for incident in simulation.world.incidents.values()
        if incident.kind == "recovery"
    ]
    assert len(recoveries) == 1
    recovery = recoveries[0]
    assert recovery.caused_by
    assert recovery.status == "SERVED"
    caused = simulation.assignments.get(recovery.caused_by)
    assert caused is not None and caused.status == "CANCELLED"

    rec_assignments = [
        assignment for assignment in simulation.assignments.values()
        if assignment.incident_id == recovery.incident_id
    ]
    assert len(rec_assignments) == 1
    assert rec_assignments[0].status == "COMPLETED"

    # No double-serve: every disembarked passenger was boarded exactly
    # once net of transfers (failed-hull passengers board twice —
    # victim then rescuer — but serve once).
    boarded = sum(
        entry["detail"].get("count", 0)
        for entry in simulation.manager.event_log
        if entry["kind"] == "BOARD" and entry["detail"].get("ok") is True
    )
    disembarked = sum(
        entry["detail"].get("passengers", 0)
        for entry in simulation.manager.event_log
        if entry["kind"] == "DISEMBARK"
    )
    transferred = sum(
        entry["detail"].get("people", 0)
        for entry in simulation.manager.event_log
        if entry["kind"] == "TRANSFER"
    )
    assert transferred > 0
    assert disembarked == boarded - transferred

    failed_boat = simulation.world.boats["BOAT-02"]
    assert failed_boat.status == "FAILED"
    assert failed_boat.passengers == 0
    assert failed_boat.needs_recovery is False
    assert failed_boat.assignment_id is None

    assert all(
        incident.status == "SERVED"
        for incident in simulation.world.incidents.values()
    )


@pytest.mark.parametrize("strategy", ["centralized", "negotiation"])
def test_combined_every_cancelled_linked(strategy: str) -> None:
    """No orphan CANCELLED: each links to a COMMITTED replacement or a
    REPLAN_FAILED reason, with replaces/replaced_by history both ways."""
    simulation = _run_combined(strategy)

    cancelled = _kinds(simulation, "CANCELLED")
    assert cancelled, "expected at least the failure cancel"
    chains = _kinds(simulation, "REPLAN_CHAIN")
    failures = _kinds(simulation, "REPLAN_FAILED")
    for entry in cancelled:
        aid = entry["detail"]["assignment_id"]
        linked = [
            chain for chain in chains
            if chain["detail"].get("old_assignment_id") == aid
        ]
        terminal = [
            failure for failure in failures
            if failure["detail"].get("old_assignment_id") == aid
        ]
        assert linked or terminal, f"orphan CANCELLED {aid}"
    for chain in chains:
        old_asn = chain["detail"]["old_assignment_id"]
        new_asn = chain["detail"]["new_assignment_id"]
        assert simulation.assignments[new_asn].status in (
            "COMMITTED", "ACKNOWLEDGED", "IN_PROGRESS", "COMPLETED",
        )
        assert any(
            link.get("replaces") == old_asn
            for link in simulation.assignments[new_asn].history
        )
        assert any(
            link.get("replaced_by") == new_asn
            for link in simulation.assignments[old_asn].history
        )


@pytest.mark.parametrize("strategy", ["centralized", "negotiation"])
def test_combined_zero_invariant_violations(strategy: str) -> None:
    """No MOVE on a closed edge, shelters never over-held, no FAILED
    boat commits after its failure."""
    simulation = _run_combined(strategy)

    closed_at: dict[str, int] = {}
    for entry in simulation.manager.event_log:
        if entry["kind"] == "CLOSURE":
            edge_id = entry["detail"].get("edge_id")
            if isinstance(edge_id, str):
                closed_at.setdefault(edge_id, entry["tick"])
    late_moves = [
        entry
        for entry in simulation.manager.event_log
        if entry["kind"] == "MOVE"
        and entry["detail"].get("edge_id") in closed_at
        and entry["tick"] >= closed_at[entry["detail"]["edge_id"]]
    ]
    assert late_moves == []

    for shelter in simulation.world.shelters.values():
        held = shelter.occupancy + sum(shelter.reservations.values())
        assert held <= shelter.capacity
    assert all(
        not shelter.reservations for shelter in simulation.world.shelters.values()
    )

    failed_at = {
        entry["detail"]["boat_id"]: entry["tick"]
        for entry in simulation.manager.event_log
        if entry["kind"] == "BOAT_FAILED"
    }
    for entry in simulation.manager.event_log:
        if entry["kind"] != "COMMITTED":
            continue
        resource_id = entry["detail"].get("resource_id", "")
        if resource_id in failed_at:
            assert entry["tick"] < failed_at[resource_id]


def test_combined_history_chain_printed(capsys) -> None:
    """One incident end-to-end: CANCELLED -> REPLAN_CHAIN -> replacement."""
    simulation = _run_combined("centralized")
    chains = _kinds(simulation, "REPLAN_CHAIN")
    assert chains
    chain = chains[0]
    old_asn = chain["detail"]["old_assignment_id"]
    new_asn = chain["detail"]["new_assignment_id"]
    old = simulation.assignments[old_asn]
    new = simulation.assignments[new_asn]
    for line in [
        f"incident {chain['detail']['incident_id']}:",
        f"  {old_asn} history: {old.history}",
        f"  {new_asn} history: {new.history}",
        f"  chain: {old_asn} -> {new_asn} reason={chain['detail']['reason']}",
    ]:
        print(line)
    out = capsys.readouterr().out
    assert "replaces" in out
    assert "replaced_by" in out
    assert old_asn in out and new_asn in out


def test_shelter_overflow_per_tick_invariant() -> None:
    """Step shelter_overflow.json tick-by-tick: occupancy + reservations
    stays within capacity for every shelter on EVERY tick."""
    data = load_scenario(SHELTER_OVERFLOW_SCENARIO)
    simulation = build_simulation(copy.deepcopy(data))
    for _ in range(30):
        simulation.step()
        for shelter in simulation.world.shelters.values():
            held = shelter.occupancy + sum(shelter.reservations.values())
            assert held <= shelter.capacity, (
                shelter.shelter_id, shelter.occupancy, shelter.reservations
            )


def test_comms_note_logs_without_state_change() -> None:
    """COMMS_NOTE is audit-only; malformed payloads are IGNORED."""
    world = _road_triangle()
    before = world.to_dict()
    manager = StateManager(world, seed=7)
    manager.apply_event(
        {
            "tick": 40,
            "kind": "COMMS_NOTE",
            "payload": {"message": COMMS_PARTITION_MESSAGE},
            "event_id": "EVT-NOTE-1",
        }
    )
    notes = [e for e in manager.event_log if e["kind"] == "COMMS_NOTE"]
    assert len(notes) == 1
    assert notes[0]["tick"] == 40
    assert notes[0]["detail"] == {"message": COMMS_PARTITION_MESSAGE}
    assert world.to_dict() == before

    n_ignored = lambda: sum(1 for e in manager.event_log if e["kind"] == "IGNORED")
    before_ignored = n_ignored()
    manager.apply_event(
        {"tick": 41, "kind": "COMMS_NOTE", "payload": {}, "event_id": "EVT-NOTE-2"}
    )
    manager.apply_event(
        {
            "tick": 41, "kind": "COMMS_NOTE",
            "payload": {"message": 42}, "event_id": "EVT-NOTE-3",
        }
    )
    assert n_ignored() == before_ignored + 2
    assert world.to_dict() == before


def test_report_event_flows_through_engine() -> None:
    """Scheduler REPORT events file claims; malformed claims never raise."""
    from backend.app.simulation.engine import Simulation

    world = _single_water_leg()
    simulation = Simulation(world, seed=7)
    claim = {
        "report_id": "RPT-001",
        "subject_id": "W-AB",
        "claim": "CLOSED",
        "source": "BOAT-01",
        "observed_at_tick": 1,
        "received_at_tick": 2,
        "confidence": 0.9,
        "verification_status": "UNVERIFIED",
    }
    simulation.manager.scheduler.push(2, "REPORT", dict(claim), "EVT-RPT-1")
    simulation.manager.scheduler.push(3, "REPORT", {}, "EVT-RPT-BAD")
    simulation.run(4)

    assert simulation.world.edges["W-AB"].status == "disputed"
    disputed = [
        e for e in simulation.manager.event_log if e["kind"] == "EDGE_DISPUTED"
    ]
    assert len(disputed) == 1
    assert disputed[0]["detail"]["edge_id"] == "W-AB"
    ignored = [
        e for e in simulation.manager.event_log
        if e["kind"] == "IGNORED"
        and e["detail"].get("event_id") == "EVT-RPT-BAD"
    ]
    assert len(ignored) == 1


def _linear_water_world() -> World:
    """A->B->C->S water line with no alternate path (suspend topology)."""
    return World(
        nodes={
            "A": _node("A", "station"),
            "B": _node("B"),
            "C": _node("C", "incident_site"),
            "S": _node("S", "shelter"),
        },
        edges={
            "W-AB": _edge("W-AB", "A", "B", "water", 1),
            "W-BC": _edge("W-BC", "B", "C", "water", 1),
            "W-CS": _edge("W-CS", "C", "S", "water", 1),
        },
        incidents={
            "INC-01": Incident(
                incident_id="INC-01", node_id="C", urgency=4, people=2,
                required_capabilities=["boat"],
            ),
        },
        boats={
            "BOAT-01": Boat(
                boat_id="BOAT-01", node_id="A", capacity=4,
                fuel=30.0, fuel_reserve=5.0,
            ),
        },
        shelters={"SH-01": Shelter(shelter_id="SH-01", node_id="S", capacity=6)},
    )


def test_no_alternate_route_suspends_without_cancel() -> None:
    """Pure route codes with no alternate SUSPEND: hold, retry, never cancel."""
    from backend.app.simulation.engine import Simulation

    simulation = Simulation(_linear_water_world(), seed=7)
    simulation.manager.scheduler.push(
        2, "CLOSURE", {"edge_id": "W-BC"}, "EVT-CLOSE-1"
    )
    simulation.run(6)

    assert simulation.world.boats["BOAT-01"].node_id == "B"
    blocked = [
        e for e in simulation.manager.event_log if e["kind"] == "ROUTE_BLOCKED"
    ]
    assert blocked
    assert all(e["detail"].get("edge_id") == "W-BC" for e in blocked)
    assert not [
        e for e in simulation.manager.event_log if e["kind"] == "CANCELLED"
    ]
    assert simulation.pending_replans == {}
    active = [
        a for a in simulation.assignments.values()
        if a.status in ("COMMITTED", "ACKNOWLEDGED", "IN_PROGRESS")
    ]
    assert len(active) == 1
    assert simulation.world.incidents["INC-01"].status != "OPEN"


def test_terminal_orphan_logs_replan_failed_once() -> None:
    """A still-OPEN orphan no resource can reach logs one REPLAN_FAILED."""
    from backend.app.simulation.engine import Simulation
    from backend.app.dispatch.scheduler_interface import Assignment

    world = _linear_water_world()
    # Strand the incident: no edge reaches C anymore.
    world.edges["W-BC"].status = "closed"
    simulation = Simulation(world, seed=7)
    old = Assignment(
        assignment_id="ASN-OLD", version=1, proposal_id="PROP-OLD",
        incident_id="INC-01", resource_id="BOAT-01", resource_kind="boat",
        shelter_id="SH-01", seats=2, route_edge_ids=["W-AB", "W-BC"],
        status="CANCELLED", cost=1.0, created_tick=1, history=[],
    )
    simulation.assignments["ASN-OLD"] = old
    simulation.pending_replans["INC-01"] = {
        "old_asn": "ASN-OLD", "reason": "CANCELLED:EDGE_CLOSED:W-BC",
        "tick": 2, "seats": 2, "resource_kind": "boat",
    }
    simulation._link_pending_replans(3)
    simulation._link_pending_replans(4)

    failed = [
        e for e in simulation.manager.event_log if e["kind"] == "REPLAN_FAILED"
    ]
    assert len(failed) == 1
    assert failed[0]["detail"]["incident_id"] == "INC-01"
    assert failed[0]["detail"]["old_assignment_id"] == "ASN-OLD"
    assert failed[0]["detail"]["reason"] == "NO_ROUTE"
    assert simulation.pending_replans == {}


def test_mixed_codes_cancel_and_pend_for_relink() -> None:
    """Mixed route + shelter codes fall through to cancel with a pending."""
    from backend.app.simulation.engine import Simulation

    simulation = Simulation(_failure_world(), seed=11)
    assignments: dict = simulation.assignments
    seen: dict = simulation.proposals_seen
    _commit_boat_01(simulation.manager, assignments, seen)
    simulation.manager.apply_closure("W-SI", 2)
    simulation.manager.apply_shelter_full("SH-01", 2)

    simulation._detect_and_handle(2)

    assert assignments["ASN-00001"].status == "CANCELLED"
    assert assignments["ASN-00001"].history[-1]["reason"].startswith("CANCELLED:")
    assert simulation.world.incidents["INC-01"].status == "OPEN"
    assert simulation.pending_replans["INC-01"]["old_asn"] == "ASN-00001"


def test_full_hold_on_accepting_shelter_never_swaps() -> None:
    """Own-hold credit: a holder's own seats never flag its accepting shelter."""
    from backend.app.simulation.engine import Simulation

    world = _overflow_world(
        {"SH-01": Shelter(shelter_id="SH-01", node_id="H1", capacity=2)},
        ["BOAT-01"],
        {"INC-01": _shelter_incident("INC-01")},
    )
    simulation = Simulation(world, seed=21)
    _commit_shelter_leg(
        simulation.manager, simulation.assignments, simulation.proposals_seen,
        "ASN-00001", "BOAT-01", "INC-01", "SH-01", 2, ["W-SI", "W-IH1"], 1,
    )
    assert world.shelter_remaining("SH-01") == 0

    simulation._detect_and_handle(2)

    assert not [
        e for e in simulation.manager.event_log if e["kind"] == "SHELTER_REASSIGNED"
    ]
    assert not [e for e in simulation.manager.event_log if e["kind"] == "REPLAN"]
    assert not [e for e in simulation.manager.event_log if e["kind"] == "CANCELLED"]
    assert world.shelters["SH-01"].reservations == {"ASN-00001": 2}

