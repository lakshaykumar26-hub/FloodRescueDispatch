"""Phase 4 Step 04: contradictory reports + conservative routing.

See docs/phase-4-dynamic-events-replanning/step-04-conflicting-reports.md.
"""

import json

from backend.app.agents.report_agent import ReportAgent
from backend.app.dispatch.bid_evaluator import check_feasible
from backend.app.dispatch.report_store import ReportStore
from backend.app.dispatch.safety_validator import validate
from backend.app.dispatch.scheduler_interface import ProposedAssignment
from backend.app.simulation.state_manager import StateManager
from backend.app.simulation.world import (
    Boat,
    Edge,
    Incident,
    Node,
    World,
)


def _node(node_id: str, kind: str = "intersection") -> Node:
    return Node(node_id=node_id, neighborhood="n", kind=kind, x=0.0, y=0.0)  # type: ignore[arg-type]


def _world() -> World:
    return World(
        nodes={
            "N-A": _node("N-A"),
            "N-B": _node("N-B", "incident_site"),
        },
        edges={
            "W-12": Edge(
                edge_id="W-12",
                from_node="N-A",
                to_node="N-B",
                mode="water",
                travel_time=2,
                status="open",
                risk_level=0.1,
                capacity=10,
            ),
        },
        incidents={
            "INC-01": Incident(
                incident_id="INC-01",
                node_id="N-B",
                urgency=3,
                people=2,
                required_capabilities=["boat"],
            ),
        },
        boats={
            "BOAT-03": Boat(
                boat_id="BOAT-03",
                node_id="N-A",
                capacity=6,
                fuel=20.0,
                fuel_reserve=2.0,
            ),
        },
    )


def _manager(world: World) -> StateManager:
    return StateManager(world, seed=7)


def _proposal() -> ProposedAssignment:
    return ProposedAssignment(
        proposal_id="PROP-001",
        incident_id="INC-01",
        resource_id="BOAT-03",
        resource_kind="boat",
        seats=2,
        route_edge_ids=["W-12"],
        eta_ticks=2,
        cost=1.0,
        reasons=["test"],
        created_tick=38,
    )


def _kinds(manager: StateManager) -> list[str]:
    return [e["kind"] for e in manager.event_log]


def test_conflicting_reports_store_both_and_dispute_edge() -> None:
    world = _world()
    manager = _manager(world)
    store = ReportStore()
    boat = ReportAgent("BOAT-03")
    team = ReportAgent("TEAM-01")

    closed = boat.submit_claim("W-12", "CLOSED", 38, confidence=0.9)
    opened = team.submit_claim("W-12", "OPEN", 39, confidence=0.4)

    status1, _ = store.ingest_report(manager, closed, 38, actor="BOAT-03")
    assert status1 == "disputed"  # lone above-threshold CLOSED already disputes
    status2, explanation = store.ingest_report(
        manager, opened, 39, actor="TEAM-01"
    )

    # Both claims kept (append-only), edge disputed, explanation cites both.
    assert len(store.claims) == 2
    assert [c["report_id"] for c in store.claims] == [
        closed["report_id"],
        opened["report_id"],
    ]
    assert world.edges["W-12"].status == "disputed"
    assert status2 == "disputed"
    assert closed["report_id"] in explanation
    assert opened["report_id"] in explanation
    disputed_logs = [
        e for e in manager.event_log if e["kind"] == "EDGE_DISPUTED"
    ]
    assert disputed_logs
    last = disputed_logs[-1]
    assert last["detail"]["edge_id"] == "W-12"
    assert set(last["detail"]["report_ids"]) == {
        closed["report_id"],
        opened["report_id"],
    }


def test_new_routes_avoid_disputed_edge() -> None:
    world = _world()
    manager = _manager(world)
    store = ReportStore()
    boat = ReportAgent("BOAT-03")
    team = ReportAgent("TEAM-01")
    store.ingest_report(
        manager, boat.submit_claim("W-12", "CLOSED", 38, confidence=0.9), 38
    )
    store.ingest_report(
        manager,
        team.submit_claim("W-12", "OPEN", 39, confidence=0.4),
        39,
    )
    assert world.edges["W-12"].status == "disputed"

    ok, code = check_feasible(world, "INC-01", "BOAT-03", None, ["W-12"], 39)
    assert (ok, code) == (False, "EDGE_DISPUTED:W-12")

    passed, violations = validate(world, _proposal(), 39, assignments={})
    assert passed is False
    assert "EDGE_DISPUTED:W-12" in violations


def test_confirmed_open_reopens_disputed_edge() -> None:
    world = _world()
    manager = _manager(world)
    store = ReportStore()
    boat = ReportAgent("BOAT-03")
    team = ReportAgent("TEAM-01")
    authority = ReportAgent("HQ")
    store.ingest_report(
        manager, boat.submit_claim("W-12", "CLOSED", 38, confidence=0.9), 38
    )
    store.ingest_report(
        manager, team.submit_claim("W-12", "OPEN", 39, confidence=0.4), 39
    )
    assert world.edges["W-12"].status == "disputed"

    verified = authority.submit_verified_open("W-12", 40)
    assert verified["claim"] == "OPEN"
    assert verified["confidence"] == 1.0
    assert verified["verification_status"] == "CONFIRMED"

    status, _ = store.ingest_report(manager, verified, 40, actor="HQ")
    assert status == "open"
    assert world.edges["W-12"].status == "open"
    reopened = [e for e in manager.event_log if e["kind"] == "EDGE_REOPENED"]
    assert len(reopened) == 1
    assert reopened[0]["detail"]["reason"] == "CONFIRMED_OPEN"
    assert verified["report_id"] in reopened[0]["detail"]["report_ids"]
    # All three claims retained; new commits feasible again.
    assert len(store.claims) == 3
    assert check_feasible(world, "INC-01", "BOAT-03", None, ["W-12"], 40) == (
        True,
        "OK",
    )
    passed, violations = validate(world, _proposal(), 40, assignments={})
    assert (passed, violations) == (True, [])


def test_lone_weak_closed_keeps_edge_open_with_warning() -> None:
    world = _world()
    manager = _manager(world)
    store = ReportStore()
    scout = ReportAgent("BOAT-03")
    weak = scout.submit_claim("W-12", "CLOSED", 38, confidence=0.2)

    status, _ = store.ingest_report(manager, weak, 38, actor="BOAT-03")
    assert status == "open"
    assert world.edges["W-12"].status == "open"
    warnings = [
        e for e in manager.event_log if e["kind"] == "REPORT_WARNING"
    ]
    assert len(warnings) == 1
    assert warnings[0]["detail"]["edge_id"] == "W-12"
    # Weak evidence does not block new commits.
    assert check_feasible(world, "INC-01", "BOAT-03", None, ["W-12"], 38) == (
        True,
        "OK",
    )


def test_unknown_edge_report_ignored_never_raises() -> None:
    world = _world()
    manager = _manager(world)
    store = ReportStore()
    scout = ReportAgent("BOAT-03")
    status, _ = store.ingest_report(
        manager, scout.submit_claim("W-NOPE", "CLOSED", 38, confidence=0.9), 38
    )
    assert status == "disputed"  # belief still derives from claims
    ignored = [e for e in manager.event_log if e["kind"] == "IGNORED"]
    assert ignored and ignored[-1]["detail"]["edge_id"] == "W-NOPE"


def test_store_json_round_trip() -> None:
    store = ReportStore()
    boat = ReportAgent("BOAT-03")
    team = ReportAgent("TEAM-01")
    store.add_claim(boat.submit_claim("W-12", "CLOSED", 38, confidence=0.9))
    store.add_claim(team.submit_claim("W-12", "OPEN", 39, confidence=0.4))

    snapshot = json.loads(json.dumps(store.to_dict()))
    restored = ReportStore.from_dict(snapshot)
    assert restored.threshold == store.threshold
    assert restored.claims == store.claims
    assert restored.edge_belief("W-12") == store.edge_belief("W-12")
    # Restored store keeps appending, never overwriting.
    restored.add_claim(boat.submit_claim("W-12", "CLOSED", 41, confidence=0.8))
    assert len(restored.claims) == 3
    assert len(store.claims) == 2


def test_submit_claim_verification_defaults_unverified() -> None:
    reporter = ReportAgent("UNIT-07")
    plain = reporter.submit_claim("W-12", "CLOSED", 12)
    assert plain["verification_status"] == "UNVERIFIED"
    flagged = reporter.submit_claim(
        "W-12", "CLOSED", 13, confidence=0.9, verification="CONFIRMED"
    )
    assert flagged["verification_status"] == "CONFIRMED"
    assert flagged["report_id"] == "RPT-UNIT-07-0002"
