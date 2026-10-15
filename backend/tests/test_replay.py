"""Phase 1 Step 04 (partial): snapshot round-trip + scheduler determinism."""

import copy
import json

from backend.app.simulation.event_scheduler import EventScheduler
from backend.app.simulation.snapshots import restore, take_snapshot
from backend.app.simulation.state_manager import StateManager
from backend.app.simulation.world import Boat, Edge, Node, World


def _make_world() -> World:
    return World(
        nodes={
            "N-01": Node(node_id="N-01", neighborhood="North", kind="station",
                         x=0.0, y=0.0),
            "N-02": Node(node_id="N-02", neighborhood="North", kind="incident_site",
                         x=1.0, y=0.0),
        },
        edges={
            "W-01": Edge(edge_id="W-01", from_node="N-01", to_node="N-02",
                         mode="water", travel_time=2, status="open",
                         risk_level=0.1, capacity=2),
        },
        boats={
            "BOAT-01": Boat(boat_id="BOAT-01", node_id="N-01", capacity=4,
                            fuel=10.0, fuel_reserve=2.0),
        },
        tick=10,
        seed=42,
    )


def test_snapshot_restore_deep_equal() -> None:
    manager = StateManager(_make_world(), seed=42)
    manager.apply_incident(
        {"incident_id": "INC-01", "node_id": "N-02", "urgency": 3, "people": 2},
        tick=10,
    )
    snapshot = take_snapshot(manager.world, manager.event_log, manager.seed)

    # Mutate after the snapshot: these changes must not leak into it.
    manager.world.tick = 11
    manager.world.boats["BOAT-01"].node_id = "N-02"
    manager.apply_incident(
        {"incident_id": "INC-02", "node_id": "N-01", "urgency": 2, "people": 1},
        tick=11,
    )

    world2, log2 = restore(snapshot)
    assert world2.to_dict() == snapshot["world"]
    assert world2.tick == snapshot["tick"] == 10
    assert snapshot["seed"] == 42
    assert log2 == snapshot["event_log"]
    # Restored state differs from the post-snapshot mutated world.
    assert world2.to_dict() != manager.world.to_dict()
    assert "INC-02" not in world2.incidents
    # Restored log is a copy: mutating it must not touch the snapshot.
    log2.append({"tick": 99, "kind": "X", "actor": "t", "detail": {}})
    assert len(snapshot["event_log"]) == len(log2) - 1


def test_snapshot_json_round_trip() -> None:
    manager = StateManager(_make_world(), seed=42)
    manager.apply_closure("W-01", tick=10)
    snapshot = take_snapshot(manager.world, manager.event_log, manager.seed)
    text = json.dumps(snapshot)
    reloaded = json.loads(text)
    assert reloaded == snapshot
    world2, log2 = restore(reloaded)
    assert world2.to_dict() == snapshot["world"]
    assert world2.tick == snapshot["tick"]
    assert log2 == snapshot["event_log"]
    assert copy.deepcopy(snapshot) == snapshot


def test_scheduler_same_tick_event_id_order_and_tick_boundary() -> None:
    boundary = EventScheduler(seed=42)
    boundary.push(40, "INCIDENT_ARRIVAL", {"incident_id": "INC-09"}, "EVT-003")
    assert boundary.pop_due(39) == []  # tick-40 event must not fire at tick 39
    assert [e["event_id"] for e in boundary.pop_due(40)] == ["EVT-003"]

    sched = EventScheduler(seed=42)
    sched.push(10, "CLOSURE", {"edge_id": "W-01"}, "EVT-002")
    sched.push(10, "CLOSURE", {"edge_id": "W-02"}, "EVT-001")
    # Same-tick events fire in event_id order regardless of push order.
    due10 = sched.pop_due(10)
    assert [e["event_id"] for e in due10] == ["EVT-001", "EVT-002"]


def test_scheduler_same_seed_same_sequence() -> None:
    def run_once() -> list[dict]:
        sched = EventScheduler(seed=42)
        sched.push(5, "CLOSURE", {"edge_id": "W-01"}, "EVT-002")
        sched.push(5, "FLOOD_RISE", {"level": 2}, "EVT-001")
        sched.push(40, "INCIDENT_ARRIVAL", {"incident_id": "INC-01"}, "EVT-003")
        first = sched.pop_due(5)
        second = sched.pop_due(40)
        return first + second

    assert run_once() == run_once()
