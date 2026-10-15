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


# --- Phase 6 Step 03 (additive): WS live view + deterministic replay ---

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def api_client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", str(tmp_path / "replay_test.db"))
    from backend.app.api import store
    from backend.app.main import create_app
    from backend.app.persistence import database as _database

    store.clear_entries()
    _database.reset_shared()
    yield TestClient(create_app())
    store.clear_entries()
    _database.reset_shared()


def _scenario_path() -> object:
    from pathlib import Path

    return Path(__file__).resolve().parents[2] / "scenarios" / "baseline.json"


def test_ws_receives_ticks_in_order_with_matching_event_counts(
    api_client: TestClient,
) -> None:
    client = api_client
    resp = client.post(
        "/api/simulations", json={"scenario_name": "baseline"}
    )
    assert resp.status_code == 200, resp.text
    sim_id = resp.json()["simulation_id"]
    assert client.post(f"/api/simulations/{sim_id}/start").status_code == 200
    with client.websocket_connect(f"/ws/simulations/{sim_id}") as ws:
        hello = ws.receive_json()
        assert hello["tick"] == 0
        assert hello["events"] == []
        ticks: list[int] = []
        frame_events = 0
        for expected in range(1, 6):
            ws.send_json({"action": "step", "steps": 1})
            frame = ws.receive_json()
            ticks.append(frame["tick"])
            assert frame["tick"] == expected
            frame_events += len(frame["events"])
            assert {"tick", "state_digest", "events", "assignments_delta",
                    "comms_digest"} <= set(frame)
    assert ticks == [1, 2, 3, 4, 5]
    rest = client.get(f"/api/simulations/{sim_id}/events")
    assert rest.status_code == 200
    assert rest.json()["count"] == frame_events


def test_fixed_seed_replay_identical_event_order_and_winners() -> None:
    import copy

    from backend.app.simulation.replay import (
        event_signature,
        replay_simulation,
        winners_signature,
    )
    from backend.app.simulation.run import build_simulation, load_scenario

    data = load_scenario(_scenario_path())

    def run_once() -> object:
        sim = build_simulation(copy.deepcopy(data), seed=42)
        sim.run(25)
        return sim

    first = run_once()
    second = run_once()
    assert event_signature(first) == event_signature(second)
    assert winners_signature(first) == winners_signature(second)

    injections = [
        {"tick": 6, "kind": "CLOSURE", "payload": {"edge_id": "R-11"},
         "event_id": "EVT-INJECT-0001"},
    ]
    replayed = replay_simulation(
        copy.deepcopy(data), 42, "centralized", injections, 25
    )
    live = build_simulation(copy.deepcopy(data), seed=42)
    for entry in injections:
        from backend.app.simulation.replay import apply_injection

        apply_injection(
            live, entry["kind"], dict(entry["payload"]),
            entry["tick"], entry["event_id"],
        )
    live.run(25)
    assert event_signature(replayed) == event_signature(live)
    assert winners_signature(replayed) == winners_signature(live)


def test_replay_from_mid_snapshot_equals_uninterrupted_run() -> None:
    import copy

    from backend.app.simulation.replay import event_signature, replay_simulation
    from backend.app.simulation.run import build_simulation, load_scenario

    data = load_scenario(_scenario_path())
    live = build_simulation(copy.deepcopy(data), seed=42)
    live.run(30)
    assert 20 in live.snapshots
    resumed = replay_simulation(
        copy.deepcopy(data), 42, "centralized", [], 30,
        from_snapshot=live.snapshots[20],
    )
    assert resumed.tick == 30
    assert event_signature(resumed) == event_signature(live)
    assert resumed.world.to_dict() == live.world.to_dict()


def test_metrics_recompute_after_replay_matches(api_client: TestClient) -> None:
    client = api_client
    resp = client.post(
        "/api/simulations",
        json={"scenario_name": "baseline", "strategy": "negotiation"},
    )
    assert resp.status_code == 200, resp.text
    sim_id = resp.json()["simulation_id"]
    client.post(f"/api/simulations/{sim_id}/start")
    client.post(
        f"/api/simulations/{sim_id}/events",
        json={"kind": "CLOSURE", "payload": {"edge_id": "R-11"}},
    )
    client.post(f"/api/simulations/{sim_id}/step", json={"steps": 20})
    live = client.get(f"/api/simulations/{sim_id}/metrics").json()
    replay = client.post(f"/api/simulations/{sim_id}/replay", json={}).json()
    assert replay["summary"]["served"] == live["served"]
    assert replay["summary"]["committed"] == live["committed"]
    assert replay["summary"]["rejected_by_reason"] == live["rejected_by_reason"]
    mid = client.post(
        f"/api/simulations/{sim_id}/replay", json={"from_snapshot_tick": 10}
    )
    assert mid.status_code == 200, mid.text
    assert mid.json()["summary"]["served"] == live["served"]
