"""Phase 1 Step 06: engine loop + baseline scenario smoke tests (headless)."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from backend.app.routing.route_validator import is_route_valid
from backend.app.simulation.engine import Simulation
from backend.app.simulation.run import build_simulation, load_scenario
from backend.app.simulation.world import Boat, Edge, Incident, Node, Shelter, World

BASELINE = Path(__file__).resolve().parent.parent.parent / "scenarios" / "baseline.json"


def _served_count(simulation) -> int:
    return sum(1 for incident in simulation.world.incidents.values() if incident.status == "SERVED")


def _log_hash(event_log: list[dict]) -> str:
    return hashlib.sha256(
        json.dumps(event_log, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def test_baseline_runs_30_ticks_headless() -> None:
    data = load_scenario(BASELINE)
    simulation = build_simulation(copy.deepcopy(data), seed=42)
    start_nodes = {
        **{bid: boat.node_id for bid, boat in simulation.world.boats.items()},
        **{tid: team.node_id for tid, team in simulation.world.teams.items()},
    }
    final_tick = simulation.run(30)

    assert final_tick == 30
    assert len(simulation.manager.event_log) > 0
    end_nodes = {
        **{bid: boat.node_id for bid, boat in simulation.world.boats.items()},
        **{tid: team.node_id for tid, team in simulation.world.teams.items()},
    }
    assert any(end_nodes[rid] != start_nodes[rid] for rid in start_nodes)
    assert 10 in simulation.snapshots
    assert 20 in simulation.snapshots
    assert 30 in simulation.snapshots


def test_determinism_same_seed_identical() -> None:
    def run_once() -> tuple[int, int, str]:
        data = load_scenario(BASELINE)
        simulation = build_simulation(copy.deepcopy(data), seed=42)
        simulation.run(30)
        return (
            simulation.tick,
            _served_count(simulation),
            _log_hash(simulation.manager.event_log),
        )

    first = run_once()
    second = run_once()
    assert first == second


def test_closure_blocks_route_no_traversal(tmp_path) -> None:
    data = load_scenario(BASELINE)
    # Probe run: find an edge a resource traverses at tick 5 *along a route
    # committed before tick 5*. Closing it at tick 5 (closure applies before
    # movement in tick 5) must therefore hold that resource with a
    # ROUTE_BLOCKED log. (Edges first routed during tick 5 itself are
    # closure-aware replans and may legitimately avoid the closed edge.)
    probe = build_simulation(copy.deepcopy(data), seed=42)
    probe.run(5)
    pre_routes: dict[str, list[str]] = {}
    rerouted_at_5: set[str] = set()
    for entry in probe.manager.event_log:
        if entry["kind"] == "ROUTE_SET":
            if entry["tick"] < 5:
                pre_routes[entry["detail"]["resource_id"]] = list(
                    entry["detail"]["edge_ids"]
                )
            elif entry["tick"] == 5:
                # Route (re)computed during tick 5 itself — e.g. a shelter leg
                # planned in progression — is closure-aware and may legitimately
                # avoid the closed edge, so it cannot force a hold.
                rerouted_at_5.add(entry["detail"]["resource_id"])
    candidates = [
        entry
        for entry in probe.manager.event_log
        if entry["kind"] == "MOVE"
        and entry["tick"] == 5
        and entry["detail"]["resource_id"] not in rerouted_at_5
        and entry["detail"]["edge_id"]
        in pre_routes.get(entry["detail"]["resource_id"], [])
    ]
    assert candidates, "probe run traversed no pre-closure route edge at tick 5"
    closed_edge = candidates[0]["detail"]["edge_id"]
    closed_mode = next(
        item["mode"] for item in data["edges"] if item["edge_id"] == closed_edge
    )

    injected = copy.deepcopy(data)
    injected["events"] = list(injected.get("events", [])) + [
        {
            "tick": 5,
            "kind": "CLOSURE",
            "payload": {"edge_id": closed_edge},
            "event_id": "EVT-INJECTED-CLOSURE",
        }
    ]
    scenario_copy = tmp_path / "baseline_closure.json"
    scenario_copy.write_text(json.dumps(injected), encoding="utf-8")

    simulation = build_simulation(load_scenario(scenario_copy), seed=42)
    simulation.run(30)

    assert simulation.world.edges[closed_edge].status == "closed"
    blocked = [
        entry for entry in simulation.manager.event_log if entry["kind"] == "ROUTE_BLOCKED"
    ]
    # STEP-05 UPDATE: the Step 05 pipeline replans live routes around a
    # closure when an alternate exists, so a hold is no longer
    # guaranteed. Either outcome is safe: hold on the closed edge, or
    # an in-place REPLAN whose old legs used it. (No-alternate worlds
    # still hold — see test_closure_applies_before_movement_same_tick,
    # unchanged.)
    blocked_on_edge = [
        entry for entry in blocked if entry["detail"].get("edge_id") == closed_edge
    ]
    replanned_around = [
        entry
        for entry in simulation.manager.event_log
        if entry["kind"] == "REPLAN"
        and closed_edge in entry["detail"].get("old_route", [])
    ]
    assert blocked_on_edge or replanned_around, (
        "expected a hold or an in-place replan for the closed edge"
    )
    # World-state walk: no resource may traverse the closed edge at or
    # after the closure tick.
    late_moves = [
        entry
        for entry in simulation.manager.event_log
        if entry["kind"] == "MOVE"
        and entry["detail"].get("edge_id") == closed_edge
        and entry["tick"] >= 5
    ]
    assert late_moves == []
    valid, reason = is_route_valid(simulation.world, [closed_edge], closed_mode)  # type: ignore[arg-type]
    assert valid is False
    assert reason == f"EDGE_CLOSED:{closed_edge}"


def _tiny_closure_world() -> World:
    """One boat, one incident, one shelter; only water path uses W-BC."""
    nodes = {
        nid: Node(node_id=nid, neighborhood="H1", kind=kind, x=float(i), y=0.0)
        for i, (nid, kind) in enumerate(
            [("A", "station"), ("B", "intersection"), ("C", "incident_site"), ("S", "shelter")]
        )
    }
    edges = {
        eid: Edge(
            edge_id=eid, from_node=frm, to_node=to, mode="water",
            travel_time=2, status="open", risk_level=0.1, capacity=1,
        )
        for eid, frm, to in [("W-AB", "A", "B"), ("W-BC", "B", "C"), ("W-CS", "C", "S")]
    }
    return World(
        nodes=nodes,
        edges=edges,
        incidents={
            "INC-01": Incident(
                incident_id="INC-01", node_id="C", urgency=4, people=2,
                required_capabilities=["boat"],
            )
        },
        boats={
            "BOAT-01": Boat(
                boat_id="BOAT-01", node_id="A", capacity=4,
                fuel=30.0, fuel_reserve=5.0,
            )
        },
        teams={},
        shelters={
            "SH-01": Shelter(shelter_id="SH-01", node_id="S", capacity=6)
        },
        tick=0,
        seed=7,
    )


def test_closure_applies_before_movement_same_tick() -> None:
    """Tick-ordering contract: a closure at tick T lands before movement in T.

    Phase-2 dispatch commits at tick 1 (after movement), so the boat first
    crosses W-AB in tick 2 — after the tick-2 W-BC closure is applied — and
    then holds at B from tick 3 on. The tick-2 log must show CLOSURE before
    the tick-2 MOVE, the hold must surface as ROUTE_BLOCKED only after the
    closure tick, and W-BC must never be traversed at or after tick 2.
    """
    simulation = Simulation(_tiny_closure_world(), seed=7)
    simulation.manager.scheduler.push(
        2, "CLOSURE", {"edge_id": "W-BC"}, "EVT-CLOSE-1"
    )
    simulation.run(6)

    assert simulation.world.edges["W-BC"].status == "closed"
    # Boat crossed W-AB in tick 2, then held at B from tick 3 on.
    assert simulation.world.boats["BOAT-01"].node_id == "B"
    tick2 = [e for e in simulation.manager.event_log if e["tick"] == 2]
    closure_idx = next(i for i, e in enumerate(tick2) if e["kind"] == "CLOSURE")
    moves2 = [i for i, e in enumerate(tick2) if e["kind"] == "MOVE"]
    assert moves2, "expected the W-AB crossing at tick 2"
    assert closure_idx < min(moves2)
    assert tick2[min(moves2)]["detail"]["edge_id"] == "W-AB"
    blocked = [
        e for e in simulation.manager.event_log if e["kind"] == "ROUTE_BLOCKED"
    ]
    assert blocked, "expected ROUTE_BLOCKED holds after the closure"
    assert all(e["detail"].get("edge_id") == "W-BC" for e in blocked)
    assert min(e["tick"] for e in blocked) > 2
    late_crossings = [
        e for e in simulation.manager.event_log
        if e["kind"] == "MOVE"
        and e["detail"].get("edge_id") == "W-BC"
        and e["tick"] >= 2
    ]
    assert late_crossings == []


def test_snapshot_restore_continue_equals_uninterrupted() -> None:
    """Snapshot at tick 20 -> restore -> continue == uninterrupted run."""
    data = load_scenario(BASELINE)
    full = build_simulation(copy.deepcopy(data), seed=42)
    full.run(60)

    part = build_simulation(copy.deepcopy(data), seed=42)
    part.run(20)
    snapshot = json.loads(json.dumps(part.snapshots[20]))  # JSON round-trip
    resumed = Simulation.from_snapshot(snapshot)
    resumed.run(60)

    assert resumed.tick == full.tick
    assert _served_count(resumed) == _served_count(full)
    assert _log_hash(resumed.manager.event_log) == _log_hash(full.manager.event_log)
    assert resumed.world.to_dict() == full.world.to_dict()
    assert resumed.world.seed == full.world.seed == 42
