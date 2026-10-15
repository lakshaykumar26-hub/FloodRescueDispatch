"""Phase 2 Step 05: safety validator invariants + engine wiring gates.

See docs/phase-2-centralized-dispatch/step-05-safety-validator-logging.md
and the architecture spec section 10 (every invariant row).
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from backend.app.dispatch.safety_validator import validate
from backend.app.dispatch.scheduler_interface import Assignment, ProposedAssignment
from backend.app.simulation.engine import Simulation
from backend.app.simulation.run import build_simulation, load_scenario
from backend.app.simulation.world import (
    Boat,
    Edge,
    GroundTeam,
    Incident,
    Node,
    Shelter,
    World,
)

BASELINE = Path(__file__).resolve().parent.parent.parent / "scenarios" / "baseline.json"


# --- tiny-world builders -------------------------------------------------


def _node(node_id: str, kind: str = "intersection") -> Node:
    return Node(node_id=node_id, neighborhood="n", kind=kind, x=0.0, y=0.0)  # type: ignore[arg-type]


def _edge(
    edge_id: str,
    frm: str,
    to: str,
    mode: str = "water",
    travel_time: int = 2,
    status: str = "open",
) -> Edge:
    return Edge(
        edge_id=edge_id,
        from_node=frm,
        to_node=to,
        mode=mode,  # type: ignore[arg-type]
        travel_time=travel_time,
        status=status,  # type: ignore[arg-type]
        risk_level=0.1,
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
    return Shelter(
        shelter_id=shelter_id, node_id=node_id,
        capacity=capacity, occupancy=occupancy,
    )


def _mixed_world() -> World:
    """One water leg (boat) and one road leg (team) to a shared incident."""
    return World(
        nodes={
            "N-A": _node("N-A"),
            "N-I": _node("N-I", "incident_site"),
            "N-S": _node("N-S", "shelter"),
            "N-R": _node("N-R"),
        },
        edges={
            "W-A": _edge("W-A", "N-A", "N-I", mode="water", travel_time=2),
            "W-S": _edge("W-S", "N-I", "N-S", mode="water", travel_time=2),
            "R-A": _edge("R-A", "N-R", "N-I", mode="road", travel_time=3),
        },
        incidents={"INC-01": _incident()},
        boats={"BOAT-01": _boat()},
        teams={"TEAM-01": _team()},
        shelters={"SHELTER-01": _shelter()},
    )


def _proposal(**overrides) -> ProposedAssignment:
    base: dict = {
        "proposal_id": "PROP-0001-000",
        "incident_id": "INC-01",
        "resource_id": "BOAT-01",
        "resource_kind": "boat",
        "shelter_id": "SHELTER-01",
        "seats": 4,
        "route_edge_ids": ["W-A"],
        "eta_ticks": 2,
        "cost": 1.0,
        "created_tick": 1,
    }
    base.update(overrides)
    return ProposedAssignment(**base)


def _committed_assignment(
    assignment_id: str = "ASN-00001",
    proposal_id: str = "PROP-0000-000",
    resource_id: str = "BOAT-01",
) -> Assignment:
    return Assignment(
        assignment_id=assignment_id,
        version=1,
        proposal_id=proposal_id,
        incident_id="INC-01",
        resource_id=resource_id,
        resource_kind="boat",
        shelter_id="SHELTER-01",
        seats=4,
        route_edge_ids=["W-A"],
        status="COMMITTED",
        cost=1.0,
        created_tick=0,
        history=[
            {
                "tick": 0,
                "from": "PROPOSED",
                "to": "COMMITTED",
                "reason": "setup",
                "actor": "dispatch",
            }
        ],
    )


# --- invariant rows (spec section 10) ------------------------------------


def test_unknown_incident_rejected() -> None:
    world = _mixed_world()
    ok, violations = validate(world, _proposal(incident_id="INC-99"), 1, {})
    assert ok is False
    assert "UNKNOWN_ENTITY" in violations


def test_unknown_resource_rejected() -> None:
    world = _mixed_world()
    ok, violations = validate(world, _proposal(resource_id="BOAT-99"), 1, {})
    assert ok is False
    assert "UNKNOWN_ENTITY" in violations


def test_served_incident_rejected() -> None:
    world = _mixed_world()
    world.incidents["INC-01"].status = "SERVED"
    ok, violations = validate(world, _proposal(), 1, {})
    assert ok is False
    assert "ASSIGNMENT_INVALID:INCIDENT_SERVED" in violations


def test_cancelled_incident_rejected() -> None:
    world = _mixed_world()
    world.incidents["INC-01"].status = "CANCELLED"
    ok, violations = validate(world, _proposal(), 1, {})
    assert ok is False
    assert "ASSIGNMENT_INVALID:INCIDENT_CANCELLED" in violations


def test_boat_on_road_edges_rejected() -> None:
    world = _mixed_world()
    ok, violations = validate(world, _proposal(route_edge_ids=["R-A"]), 1, {})
    assert ok is False
    assert "MODE_MISMATCH" in violations


def test_team_on_water_edges_rejected() -> None:
    world = _mixed_world()
    proposal = _proposal(
        resource_id="TEAM-01",
        resource_kind="team",
        shelter_id=None,
        route_edge_ids=["W-A"],
    )
    ok, violations = validate(world, proposal, 1, {})
    assert ok is False
    assert "MODE_MISMATCH" in violations


def test_wrong_capability_rejected() -> None:
    world = _mixed_world()  # INC-01 requires "boat"
    proposal = _proposal(
        resource_id="TEAM-01",
        resource_kind="team",
        shelter_id=None,
        route_edge_ids=["R-A"],
    )
    ok, violations = validate(world, proposal, 1, {})
    assert ok is False
    assert "MODE_MISMATCH" in violations


def test_empty_capabilities_impose_no_constraint() -> None:
    world = _mixed_world()
    world.incidents["INC-01"].required_capabilities = []
    proposal = _proposal(
        resource_id="TEAM-01",
        resource_kind="team",
        shelter_id=None,
        route_edge_ids=["R-A"],
    )
    ok, violations = validate(world, proposal, 1, {})
    assert (ok, violations) == (True, [])


def test_closed_edge_rejected() -> None:
    world = _mixed_world()
    world.edges["W-A"].status = "closed"
    ok, violations = validate(world, _proposal(), 1, {})
    assert ok is False
    assert "EDGE_CLOSED:W-A" in violations


def test_unknown_edge_rejected() -> None:
    world = _mixed_world()
    ok, violations = validate(world, _proposal(route_edge_ids=["W-NOPE"]), 1, {})
    assert ok is False
    assert "UNKNOWN_EDGE:W-NOPE" in violations


def test_failed_resource_rejected() -> None:
    world = _mixed_world()
    world.boats["BOAT-01"].status = "FAILED"
    ok, violations = validate(world, _proposal(), 1, {})
    assert ok is False
    assert "RESOURCE_UNAVAILABLE" in violations


def test_busy_resource_rejected() -> None:
    world = _mixed_world()
    world.boats["BOAT-01"].assignment_id = "ASN-00001"
    ok, violations = validate(world, _proposal(), 1, {})
    assert ok is False
    assert "RESOURCE_UNAVAILABLE" in violations


def test_conflicting_active_assignment_rejected() -> None:
    world = _mixed_world()
    assignments = {"ASN-00001": _committed_assignment()}
    ok, violations = validate(world, _proposal(), 1, assignments)
    assert ok is False
    assert "ASSIGNMENT_CONFLICT" in violations


def test_terminal_assignment_does_not_conflict() -> None:
    world = _mixed_world()
    done = _committed_assignment()
    done.status = "COMPLETED"
    ok, violations = validate(world, _proposal(), 1, {"ASN-00001": done})
    assert (ok, violations) == (True, [])


def test_over_capacity_rejected() -> None:
    world = _mixed_world()
    ok, violations = validate(world, _proposal(seats=7), 1, {})
    assert ok is False
    assert "OVER_CAPACITY" in violations


def test_low_fuel_rejected() -> None:
    world = _mixed_world()
    world.boats["BOAT-01"].fuel = 1.0  # eta 2 + reserve 2.0 = 4.0 needed
    ok, violations = validate(world, _proposal(), 1, {})
    assert ok is False
    assert "FUEL_INSUFFICIENT" in violations


def test_full_shelter_rejected() -> None:
    world = _mixed_world()
    world.shelters["SHELTER-01"].occupancy = 9  # remaining 1 < seats 4
    ok, violations = validate(world, _proposal(), 1, {})
    assert ok is False
    assert "SHELTER_FULL" in violations


def test_feasible_proposal_passes() -> None:
    world = _mixed_world()
    assert validate(world, _proposal(), 1, {}) == (True, [])


def test_violations_collect_all_not_first_only() -> None:
    world = _mixed_world()
    world.edges["W-A"].status = "closed"
    world.boats["BOAT-01"].status = "FAILED"
    world.shelters["SHELTER-01"].occupancy = 9
    ok, violations = validate(world, _proposal(), 1, {})
    assert ok is False
    assert "EDGE_CLOSED:W-A" in violations
    assert "RESOURCE_UNAVAILABLE" in violations
    assert "SHELTER_FULL" in violations
    assert len(violations) >= 3


# --- end-to-end refusal through the real commit path ----------------------


class _FixedScheduler:
    """Replays canned proposals through the real engine commit path."""

    strategy = "centralized"

    def __init__(self, proposals: list[ProposedAssignment]) -> None:
        self._proposals = proposals
        self.last_rejections: list[dict] = []

    def propose(self, world: World, tick: int) -> list[ProposedAssignment]:
        _ = (world, tick)
        return list(self._proposals)


def _closed_edge_world() -> World:
    """Boat at A, incident at C; only path crosses closed W-BC."""
    nodes = {
        nid: Node(node_id=nid, neighborhood="H1", kind=kind, x=float(i), y=0.0)
        for i, (nid, kind) in enumerate(
            [("A", "station"), ("B", "intersection"), ("C", "incident_site"), ("S", "shelter")]
        )
    }
    edges = {
        "W-AB": _edge("W-AB", "A", "B", mode="water"),
        "W-BC": _edge("W-BC", "B", "C", mode="water", status="closed"),
        "W-CS": _edge("W-CS", "C", "S", mode="water"),
    }
    return World(
        nodes=nodes,
        edges=edges,
        incidents={"INC-01": _incident(node_id="C")},
        boats={"BOAT-01": _boat(node_id="A")},
        teams={},
        shelters={"SH-01": _shelter("SH-01", "S", capacity=6)},
        tick=0,
        seed=7,
    )


def test_engine_refuses_closed_edge_proposal() -> None:
    world = _closed_edge_world()
    proposal = ProposedAssignment(
        proposal_id="PROP-0001-000",
        incident_id="INC-01",
        resource_id="BOAT-01",
        resource_kind="boat",
        shelter_id="SH-01",
        seats=2,
        route_edge_ids=["W-AB", "W-BC"],
        eta_ticks=4,
        cost=1.0,
        created_tick=1,
    )
    simulation = Simulation(world, seed=7, scheduler=_FixedScheduler([proposal]))
    simulation._dispatch(1)

    assert simulation.assignments == {}
    assert world.boats["BOAT-01"].status == "AVAILABLE"
    assert world.incidents["INC-01"].status == "OPEN"
    rejected = [
        entry for entry in simulation.manager.event_log if entry["kind"] == "REJECTED"
    ]
    assert rejected, "expected a REJECTED audit entry"
    assert any(
        entry["detail"].get("proposal_id") == "PROP-0001-000"
        and "EDGE_CLOSED:W-BC" in entry["detail"].get("reason", "")
        for entry in rejected
    )
    assert not [
        entry for entry in simulation.manager.event_log if entry["kind"] == "COMMITTED"
    ]


def test_engine_refuses_conflicting_assignment_via_validator() -> None:
    """Registry-only conflict passes check_feasible but validator rejects it."""
    world = _mixed_world()
    simulation = Simulation(world, seed=7, scheduler=_FixedScheduler([_proposal()]))
    simulation.assignments["ASN-00001"] = _committed_assignment()
    simulation._dispatch(1)

    assert simulation.assignments.keys() == {"ASN-00001"}
    rejected = [
        entry for entry in simulation.manager.event_log if entry["kind"] == "REJECTED"
    ]
    assert any(
        entry["detail"].get("proposal_id") == "PROP-0001-000"
        and "ASSIGNMENT_CONFLICT" in entry["detail"].get("reason", "")
        for entry in rejected
    )


# --- baseline gates -------------------------------------------------------


def _baseline_run(ticks: int, seed: int = 42) -> Simulation:
    data = load_scenario(BASELINE)
    simulation = build_simulation(copy.deepcopy(data), seed=seed)
    simulation.run(ticks)
    return simulation


def _committed_entries(simulation: Simulation) -> list[dict]:
    return [e for e in simulation.manager.event_log if e["kind"] == "COMMITTED"]


def test_baseline_committed_have_proposed_and_rejected_have_reasons() -> None:
    simulation = _baseline_run(60)
    log = simulation.manager.event_log
    proposed_by_id = {}
    for entry in log:
        if entry["kind"] == "PROPOSED":
            proposed_by_id.setdefault(entry["detail"]["proposal_id"], entry["tick"])
    committed = _committed_entries(simulation)
    assert committed, "baseline should commit at least one assignment in 60 ticks"
    for entry in committed:
        proposal_id = entry["detail"]["proposal_id"]
        assert proposal_id in proposed_by_id, (
            f"COMMITTED {entry['detail'].get('assignment_id')} has no preceding PROPOSED"
        )
        assert proposed_by_id[proposal_id] <= entry["tick"]
    for entry in log:
        if entry["kind"] == "REJECTED":
            assert entry["detail"].get("reason"), "bare REJECTED without a reason"


def test_baseline_no_commit_on_closed_route() -> None:
    simulation = _baseline_run(60)
    log = simulation.manager.event_log
    closures: list[tuple[int, str]] = [
        (entry["tick"], entry["detail"]["edge_id"])
        for entry in log
        if entry["kind"] == "CLOSURE"
    ]
    for entry in _committed_entries(simulation):
        aid = entry["detail"]["assignment_id"]
        route = simulation.assignments[aid].route_edge_ids
        for closed_tick, edge_id in closures:
            if closed_tick <= entry["tick"]:
                assert edge_id not in route, (
                    f"{aid} committed at tick {entry['tick']} over {edge_id} "
                    f"closed at tick {closed_tick}"
                )
    for closed_tick, edge_id in closures:
        late = [
            entry
            for entry in log
            if entry["kind"] == "MOVE"
            and entry["detail"].get("edge_id") == edge_id
            and entry["tick"] >= closed_tick
        ]
        assert late == [], f"{edge_id} traversed while closed (closure tick {closed_tick})"


def test_baseline_determinism_identical_commits() -> None:
    first = _baseline_run(60)
    second = _baseline_run(60)

    def commits(simulation: Simulation) -> list[tuple]:
        return [
            (
                entry["tick"],
                entry["detail"]["proposal_id"],
                entry["detail"]["assignment_id"],
                entry["detail"]["incident_id"],
                entry["detail"]["resource_id"],
            )
            for entry in _committed_entries(simulation)
        ]

    assert commits(first) == commits(second)

    def log_hash(simulation: Simulation) -> str:
        return hashlib.sha256(
            json.dumps(simulation.manager.event_log, sort_keys=True, default=str).encode()
        ).hexdigest()

    assert log_hash(first) == log_hash(second)


def test_baseline_exclusive_assignment_scan() -> None:
    """Walk the log: COMMITTED claims a resource; only a terminal
    lifecycle kind (COMPLETED via complete(), CANCELLED via cancel() —
    the exact terminal kinds commitment_manager.py emits) releases it."""
    simulation = _baseline_run(60)
    terminal = {"COMPLETED", "CANCELLED"}
    assignment_resource: dict[str, str] = {}
    active: dict[str, str] = {}
    for entry in simulation.manager.event_log:
        kind = entry["kind"]
        detail = entry["detail"]
        if kind == "COMMITTED":
            rid = detail["resource_id"]
            assert rid not in active, (
                f"double-commit of {rid}: {active[rid]} still active at tick {entry['tick']}"
            )
            active[rid] = detail["assignment_id"]
            assignment_resource[detail["assignment_id"]] = rid
        elif kind in terminal:
            rid = assignment_resource.get(detail["assignment_id"], "")
            if rid and active.get(rid) == detail["assignment_id"]:
                del active[rid]
    # Cross-check against live world state: no busy resource is double-booked.
    for boat in simulation.world.boats.values():
        assert boat.assignment_id is None or boat.status != "AVAILABLE"
    for team in simulation.world.teams.values():
        assert team.assignment_id is None or team.status != "AVAILABLE"
