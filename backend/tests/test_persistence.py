"""Phase 6 Step 02: persistence over sqlite (in-memory; no live Supabase).

Covers: run row with seed+strategy+status; commit+cancel through the real
commitment lifecycle -> two history rows + current row reflects cancel;
message lifecycle states persisted distinctly; snapshot restore from DB
equals in-memory restore; 30-tick run -> ~3 snapshots, events > 0, no
per-tick movement spam.
"""

from __future__ import annotations

import copy

from backend.app.dispatch import commitment_manager
from backend.app.dispatch.scheduler_interface import ProposedAssignment
from backend.app.persistence import database as _database
from backend.app.persistence import repositories as repos
from backend.app.simulation.run import build_simulation, load_scenario
from backend.app.simulation.snapshots import restore, take_snapshot
from backend.app.simulation.state_manager import StateManager
from backend.app.simulation.world import (
    Boat,
    Edge,
    Incident,
    Node,
    Shelter,
    World,
)


def _db() -> _database.Database:
    return _database.Database(url=":memory:")


def _mini_world() -> World:
    return World(
        nodes={
            "N-01": Node(node_id="N-01", neighborhood="n", kind="station",
                         x=0.0, y=0.0),
            "N-02": Node(node_id="N-02", neighborhood="n", kind="incident_site",
                         x=1.0, y=0.0),
        },
        edges={
            "W-01": Edge(edge_id="W-01", from_node="N-01", to_node="N-02",
                         mode="water", travel_time=1, status="open",
                         risk_level=0.1, capacity=2),
        },
        incidents={
            "INC-01": Incident(incident_id="INC-01", node_id="N-02", urgency=4,
                               people=2, required_capabilities=["boat"]),
        },
        boats={
            "BOAT-01": Boat(boat_id="BOAT-01", node_id="N-01", capacity=4,
                            fuel=10.0, fuel_reserve=2.0),
        },
        teams={},
        shelters={
            "SHELTER-01": Shelter(shelter_id="SHELTER-01", node_id="N-01",
                                  capacity=10, occupancy=0),
        },
        tick=0,
        seed=42,
    )


def _proposal() -> ProposedAssignment:
    return ProposedAssignment(
        proposal_id="PROP-t0-0",
        incident_id="INC-01",
        resource_id="BOAT-01",
        resource_kind="boat",
        shelter_id="SHELTER-01",
        seats=2,
        route_edge_ids=["W-01"],
        eta_ticks=1,
        cost=3.0,
        reasons=["test"],
        created_tick=0,
    )


def test_create_run_row_with_seed_strategy_status() -> None:
    db = _db()
    repos.save_run(db, "SIM-001", "baseline", "centralized", 42, "running", 5, 120)
    row = repos.get_run(db, "SIM-001")
    assert row is not None
    assert row["seed"] == 42
    assert row["strategy"] == "centralized"
    assert row["status"] == "running"
    assert row["tick"] == 5


def test_commit_then_cancel_two_history_rows_current_reflects_cancel() -> None:
    db = _db()
    world = _mini_world()
    manager = StateManager(world, seed=42)
    assignments: dict = {}
    proposals_seen: dict = {}
    assignment, code = commitment_manager.commit_assignment(
        manager, _proposal(), 0, "ASN-00001", assignments, proposals_seen
    )
    assert assignment is not None, code
    repos.save_run(db, "SIM-001", "mini", "centralized", 42, "running", 0, 10)
    repos.sync_assignments(db, "SIM-001", 0, assignments, manager.event_log)
    ok, cancel_code = commitment_manager.cancel(
        manager, assignments, "ASN-00001", 3, actor="api", reason="CANCELLED:TEST"
    )
    assert ok, cancel_code
    new_log = manager.event_log[len(manager.event_log) - 1 :]
    repos.sync_assignments(db, "SIM-001", 3, assignments, new_log)
    current = repos.get_assignment(db, "SIM-001", "ASN-00001")
    assert current is not None
    assert current["status"] == "CANCELLED"
    history = repos.history_for(db, "SIM-001", "ASN-00001")
    assert len(history) == 2
    assert history[0]["to_status"] == "COMMITTED"
    assert history[1]["to_status"] == "CANCELLED"
    assert history[1]["reason"] == "CANCELLED:TEST"


def test_message_lifecycle_states_persisted_distinctly() -> None:
    db = _db()
    repos.save_message(db, "SIM-001", 1, "MSG-00001", "ASSIGNMENT_OFFER",
                       "DISPATCH-01", "BOAT-01", "QUEUED", {"assignment_id": "A"})
    assert repos.get_message(db, "SIM-001", "MSG-00001")["status"] == "QUEUED"
    repos.update_message_status(db, "SIM-001", "MSG-00001", 2, "DELIVERED")
    assert repos.get_message(db, "SIM-001", "MSG-00001")["status"] == "DELIVERED"
    repos.update_message_status(db, "SIM-001", "MSG-00001", 3, "ACKED")
    assert repos.get_message(db, "SIM-001", "MSG-00001")["status"] == "ACKED"
    repos.save_message(db, "SIM-001", 4, "MSG-00002", "BOAT_POSITION",
                       "BOAT-01", "DISPATCH-01", "EXPIRED", {})
    states = {
        repos.get_message(db, "SIM-001", "MSG-00001")["status"],
        repos.get_message(db, "SIM-001", "MSG-00002")["status"],
    }
    assert states == {"ACKED", "EXPIRED"}


def test_snapshot_restore_from_db_equals_in_memory_restore() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    data = load_scenario(root / "scenarios" / "baseline.json")
    sim = build_simulation(copy.deepcopy(data), seed=42, snapshot_every=10)
    sim.run(10)
    assert 10 in sim.snapshots
    db = _db()
    repos.save_snapshot(db, "SIM-001", 10, sim.snapshots[10])
    from_db = repos.load_snapshot(db, "SIM-001", 10)
    assert from_db is not None
    world_db, log_db = restore(from_db)
    world_mem, log_mem = restore(sim.snapshots[10])
    assert world_db.to_dict() == world_mem.to_dict()
    assert log_db == log_mem
    assert from_db["version"] == 1


def test_run_30_ticks_snapshots_about_three_events_positive_no_spam() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    data = load_scenario(root / "scenarios" / "baseline.json")
    sim = build_simulation(copy.deepcopy(data), seed=42, snapshot_every=10)
    sim.run(30)
    db = _db()
    repos.save_run(db, "SIM-001", "baseline", "centralized", 42, "running",
                   sim.tick, 120)
    for tick, snapshot in sorted(sim.snapshots.items()):
        repos.save_snapshot(db, "SIM-001", tick, snapshot)
    assert repos.list_snapshot_ticks(db, "SIM-001") == [10, 20, 30]
    n = repos.save_events_batch(db, "SIM-001", sim.manager.event_log)
    assert n > 0
    assert repos.count_events(db, "SIM-001") == n
    kinds = {
        r["kind"]
        for r in db.execute(
            "SELECT DISTINCT kind FROM simulation_events WHERE simulation_id = ?",
            ("SIM-001",),
        )
    }
    assert "MOVE" not in kinds
    assert "COMMITTED" in kinds
    fresh = take_snapshot(sim.world, sim.manager.event_log, sim.seed)
    assert fresh["version"] == 1


def test_reports_and_metrics_round_trip() -> None:
    db = _db()
    repos.save_report(
        db, "SIM-001", 6,
        {"report_id": "RPT-001", "subject_id": "W-01", "claim": "CLOSED",
         "source": "BOAT-01", "observed_at_tick": 5, "received_at_tick": 6,
         "confidence": 0.8, "verification_status": "UNVERIFIED"},
    )
    repos.save_metrics(
        db, "SIM-001", 10,
        {"strategy": "centralized", "served": 3, "unserved": 9,
         "committed": 5, "rejected_by_reason": {"X": 1}, "snapshots": [10]},
    )
    metrics = repos.get_metrics(db, "SIM-001", 10)
    assert metrics is not None
    assert metrics["served"] == 3
    assert db.count("reports", "simulation_id = ?", ("SIM-001",)) == 1
