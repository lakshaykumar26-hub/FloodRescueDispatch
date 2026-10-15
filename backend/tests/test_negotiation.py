"""Phase 3 Step 01 -- belief-isolation tests for BaseAgent.

====================================================
STEP 01: belief isolation (world.state != local_belief)
====================================================

(Step 02 will append bid tests in a new clearly-marked section below;
do not mix them into the Step 01 section.)
"""

from backend.app.agents.base_agent import EDGE_RECORD_KEYS, BaseAgent
from backend.app.simulation.world import Edge, Node, Shelter, World


def _make_world() -> World:
    """Minimal world with one water edge W-01 (open) and one shelter."""
    return World(
        nodes={
            "N-A": Node(node_id="N-A", neighborhood="North", kind="station", x=0.0, y=0.0),
            "N-B": Node(
                node_id="N-B", neighborhood="North", kind="incident_site", x=1.0, y=1.0
            ),
        },
        edges={
            "W-01": Edge(
                edge_id="W-01",
                from_node="N-A",
                to_node="N-B",
                mode="water",
                travel_time=8,
                status="open",
                risk_level=0.2,
                capacity=1,
            ),
        },
        shelters={
            "SHELTER-01": Shelter(
                shelter_id="SHELTER-01", node_id="N-B", capacity=10
            ),
        },
    )


def _snapshot(world: World) -> dict:
    """Build the plain-dict snapshot a caller would hand to sense()."""
    return {
        "edges": {
            edge_id: edge.model_dump(mode="json")
            for edge_id, edge in world.edges.items()
        },
        "shelters": {
            shelter_id: shelter.model_dump(mode="json")
            for shelter_id, shelter in world.shelters.items()
        },
        "assignments": [],
    }


# ---------------- Step 01: belief isolation ----------------


def test_sense_copies_snapshot_and_bumps_version() -> None:
    world = _make_world()
    agent = BaseAgent("BOAT-03")
    assert agent.local_belief["belief_version"] == 0

    agent.sense(_snapshot(world))

    assert agent.local_belief["belief_version"] == 1
    assert agent.local_belief["edges"]["W-01"]["status"] == "open"
    # Belief edge records carry the documented edge-record shape.
    assert set(EDGE_RECORD_KEYS) <= set(agent.local_belief["edges"]["W-01"])


def test_world_mutation_without_message_does_not_leak_into_belief() -> None:
    world = _make_world()
    agent = BaseAgent("BOAT-03")
    agent.sense(_snapshot(world))

    # Global closure with NO message delivered to the agent.
    world.edges["W-01"].status = "closed"

    assert world.edges["W-01"].status == "closed"
    assert agent.local_belief["edges"]["W-01"]["status"] == "open"


def test_update_belief_newer_version_overwrites_edge_status() -> None:
    world = _make_world()
    agent = BaseAgent("BOAT-03")
    agent.sense(_snapshot(world))

    world.edges["W-01"].status = "closed"
    applied = agent.update_belief(
        {
            "message_id": "MSG-00001",
            "type": "HAZARD_REPORTED",
            "tick": 10,
            "version": 2,
            "edges": {
                edge_id: edge.model_dump(mode="json")
                for edge_id, edge in world.edges.items()
            },
        }
    )

    assert applied is True
    assert agent.local_belief["edges"]["W-01"]["status"] == "closed"
    assert agent.local_belief["belief_version"] == 2
    assert agent.audit[-1]["event"] == "BELIEF_UPDATED"


def test_update_belief_older_version_ignored_and_audited() -> None:
    world = _make_world()
    agent = BaseAgent("BOAT-03")
    agent.sense(_snapshot(world))
    agent.update_belief(
        {
            "message_id": "MSG-00001",
            "type": "HAZARD_REPORTED",
            "tick": 10,
            "version": 2,
            "edges": {
                edge_id: edge.model_dump(mode="json")
                for edge_id, edge in world.edges.items()
            },
        }
    )
    assert agent.local_belief["edges"]["W-01"]["status"] == "open"

    # Stale message claims the edge is closed but carries an older version.
    stale_edges = {
        edge_id: edge.model_dump(mode="json")
        for edge_id, edge in world.edges.items()
    }
    stale_edges["W-01"]["status"] = "closed"
    applied = agent.update_belief(
        {
            "message_id": "MSG-00000",
            "type": "HAZARD_REPORTED",
            "tick": 5,
            "version": 1,
            "edges": stale_edges,
        }
    )

    assert applied is False
    # Belief unchanged by the stale message.
    assert agent.local_belief["edges"]["W-01"]["status"] == "open"
    assert agent.local_belief["belief_version"] == 2
    assert any(
        entry.get("event") == "STALE_BELIEF_IGNORED" for entry in agent.audit
    )


def test_belief_version_bumps_on_sense_and_applied_message_only() -> None:
    world = _make_world()
    agent = BaseAgent("BOAT-03")

    agent.sense(_snapshot(world))
    assert agent.local_belief["belief_version"] == 1

    agent.sense(_snapshot(world))
    assert agent.local_belief["belief_version"] == 2

    assert (
        agent.update_belief(
            {
                "message_id": "MSG-00009",
                "type": "HAZARD_REPORTED",
                "tick": 12,
                "version": 5,
                "edges": {},
            }
        )
        is True
    )
    assert agent.local_belief["belief_version"] == 5

    # Stale messages never move the version.
    assert (
        agent.update_belief(
            {
                "message_id": "MSG-00008",
                "type": "HAZARD_REPORTED",
                "tick": 11,
                "version": 4,
                "edges": {},
            }
        )
        is False
    )
    assert agent.local_belief["belief_version"] == 5


def test_stored_edge_record_is_a_copy() -> None:
    world = _make_world()
    agent = BaseAgent("BOAT-03")
    snapshot = _snapshot(world)
    agent.sense(snapshot)

    # Mutating the caller's snapshot dict after sense() must not affect belief.
    snapshot["edges"]["W-01"]["status"] = "closed"
    assert agent.local_belief["edges"]["W-01"]["status"] == "open"

    # Mutating the live World afterwards must not affect belief either.
    world.edges["W-01"].status = "closed"
    world.edges["W-01"].risk_level = 0.9
    assert agent.local_belief["edges"]["W-01"]["status"] == "open"
    assert agent.local_belief["edges"]["W-01"]["risk_level"] == 0.2


# ====================================================
# STEP 02: resource-agent bids (local belief only, never global World)
# ====================================================
# NOTE on the step-02 brief ("2 bids + 1 rejection"): boats share one mode,
# so MODE_MISMATCH cannot reject a boat; the fixture below yields 1 feasible
# bid + 2 rejections with DISTINCT reasons (RESOURCE_UNAVAILABLE,
# FUEL_INSUFFICIENT). MODE_MISMATCH is covered separately for boats and teams.

from backend.app.agents.boat_agent import BID_KEYS as BOAT_BID_KEYS
from backend.app.agents.boat_agent import BoatAgent
from backend.app.agents.ground_team_agent import BID_KEYS as TEAM_BID_KEYS
from backend.app.agents.ground_team_agent import GroundTeamAgent
from backend.app.agents.incident_agent import IncidentAgent
from backend.app.agents.report_agent import ReportAgent
from backend.app.agents.shelter_agent import ShelterAgent

EXPECTED_BID_KEYS = {
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


def _edge_record(edge_id, frm, to, mode="water", travel=3, status="open", risk=0.1):
    return {
        "edge_id": edge_id,
        "from_node": frm,
        "to_node": to,
        "mode": mode,
        "travel_time": travel,
        "status": status,
        "risk_level": risk,
        "capacity": 10,
    }


def _shelter_record(shelter_id, node_id, capacity=10, occupancy=0, reservations=None):
    return {
        "shelter_id": shelter_id,
        "node_id": node_id,
        "capacity": capacity,
        "occupancy": occupancy,
        "reservations": dict(reservations or {}),
        "history": [],
    }


def _belief(edges, shelters):
    return {
        "edges": {e["edge_id"]: e for e in edges},
        "shelters": {s["shelter_id"]: s for s in shelters},
        "assignments": [],
    }


def _boat_request(node_id="N-I", people=4, capabilities=None):
    return {
        "incident_id": "INC-01",
        "node_id": node_id,
        "urgency": 3,
        "people": people,
        "capabilities": ["boat"] if capabilities is None else capabilities,
        "created_tick": 0,
    }


# ---------------- Step 02: request shape ----------------


def test_incident_publish_request_exact_keys() -> None:
    agent = IncidentAgent("INC-01", "N-I", 3, 4, ["boat"], 7)
    assert agent.publish_request() == {
        "incident_id": "INC-01",
        "node_id": "N-I",
        "urgency": 3,
        "people": 4,
        "capabilities": ["boat"],
        "created_tick": 7,
    }


def test_boat_and_team_bid_key_sets_match_contract() -> None:
    assert set(BOAT_BID_KEYS) == EXPECTED_BID_KEYS
    assert set(TEAM_BID_KEYS) == EXPECTED_BID_KEYS


# ---------------- Step 02: stale belief ----------------


def test_stale_belief_boat_bids_optimistically_with_old_belief_version() -> None:
    """Edge open in belief but closed globally: the agent never sees global.

    The agent is fed only the OLD snapshot (deep-copied, as sense()
    requires); the global World is then closed without any message. The bid
    must still be produced, carrying the stale belief_version.
    """
    world = _make_world()
    boat = BoatAgent("BOAT-01", capacity=6, fuel=20.0, fuel_reserve=2.0, node_id="N-A")
    boat.sense(_snapshot(world))  # belief_version 1, W-01 open
    assert boat.local_belief["belief_version"] == 1

    # Global closure the agent is never told about (no message delivered).
    world.edges["W-01"].status = "closed"

    boat.local_belief["shelters"] = {
        "SHELTER-01": _shelter_record("SHELTER-01", "N-B", capacity=10),
    }
    bid, reason = boat.evaluate(_boat_request(node_id="N-B", capabilities=["boat"]), 5)

    assert reason == "OK"
    assert bid is not None
    assert bid["belief_version"] == 1  # stale version carried, not refreshed
    assert bid["route_edge_ids"] == ["W-01"]
    assert bid["eta_ticks"] == 8
    assert bid["estimated_arrival"] == 5 + 8
    assert bid["estimated_completion"] == 5 + 8 + 2
    assert bid["risk_score"] == round(0.2, 3)
    assert world.edges["W-01"].status == "closed"  # global untouched by bid


# ---------------- Step 02: rejection codes ----------------


def test_boat_incompatible_mode_rejected() -> None:
    boat = BoatAgent("BOAT-01", capacity=6, fuel=20.0, fuel_reserve=2.0, node_id="N-A")
    boat.sense(
        _belief(
            [_edge_record("W-A", "N-A", "N-I")],
            [_shelter_record("SHELTER-01", "N-S")],
        )
    )
    bid, reason = boat.evaluate(_boat_request(capabilities=["ground"]), 0)
    assert (bid, reason) == (None, "MODE_MISMATCH")


def test_boat_low_fuel_rejected() -> None:
    boat = BoatAgent("BOAT-01", capacity=6, fuel=3.0, fuel_reserve=2.0, node_id="N-A")
    boat.sense(
        _belief(
            [
                _edge_record("W-A", "N-A", "N-I", travel=3),
                _edge_record("W-S", "N-I", "N-S", travel=2),
            ],
            [_shelter_record("SHELTER-01", "N-S", capacity=10)],
        )
    )
    # eta 3 + reserve 2.0 = 5.0 > fuel 3.0
    bid, reason = boat.evaluate(_boat_request(), 0)
    assert (bid, reason) == (None, "FUEL_INSUFFICIENT")


def test_boat_no_route_rejected() -> None:
    boat = BoatAgent("BOAT-01", capacity=6, fuel=20.0, fuel_reserve=2.0, node_id="N-A")
    boat.sense(
        _belief(
            [_edge_record("W-X", "N-A", "N-NOWHERE")],
            [_shelter_record("SHELTER-01", "N-S")],
        )
    )
    bid, reason = boat.evaluate(_boat_request(), 0)
    assert (bid, reason) == (None, "NO_ROUTE")


def test_boat_over_capacity_rejected() -> None:
    boat = BoatAgent(
        "BOAT-01", capacity=4, fuel=20.0, fuel_reserve=2.0, node_id="N-A", passengers=4
    )
    boat.sense(
        _belief(
            [
                _edge_record("W-A", "N-A", "N-I", travel=3),
                _edge_record("W-S", "N-I", "N-S", travel=2),
            ],
            [_shelter_record("SHELTER-01", "N-S", capacity=10)],
        )
    )
    bid, reason = boat.evaluate(_boat_request(people=2), 0)
    assert (bid, reason) == (None, "OVER_CAPACITY")


def test_boat_shelter_full_from_belief_rejected() -> None:
    boat = BoatAgent("BOAT-01", capacity=6, fuel=20.0, fuel_reserve=2.0, node_id="N-A")
    boat.sense(
        _belief(
            [
                _edge_record("W-A", "N-A", "N-I", travel=3),
                _edge_record("W-S", "N-I", "N-S", travel=2),
            ],
            [_shelter_record("SHELTER-01", "N-S", capacity=4, occupancy=4)],
        )
    )
    bid, reason = boat.evaluate(_boat_request(people=4), 0)
    assert (bid, reason) == (None, "SHELTER_FULL")


def test_boat_feasible_bid_shape_and_math() -> None:
    boat = BoatAgent("BOAT-01", capacity=6, fuel=20.0, fuel_reserve=2.0, node_id="N-A")
    boat.sense(
        _belief(
            [
                _edge_record("W-A", "N-A", "N-I", travel=3, risk=0.1),
                _edge_record("W-S", "N-I", "N-S", travel=2, risk=0.25),
            ],
            [_shelter_record("SHELTER-01", "N-S", capacity=10)],
        )
    )
    bid, reason = boat.evaluate(_boat_request(people=4), 10)
    assert reason == "OK"
    assert set(bid) == EXPECTED_BID_KEYS
    assert bid["resource_kind"] == "boat"
    assert bid["route_edge_ids"] == ["W-A"]
    assert bid["eta_ticks"] == 3
    assert bid["risk_sum"] == 0.1
    assert bid["risk_score"] == round(0.1, 3)
    assert bid["seats"] == 4
    assert bid["people_capacity"] == 4
    assert bid["estimated_arrival"] == 13
    assert bid["estimated_completion"] == 15
    assert bid["fuel_feasible"] is True
    assert bid["shelter_feasible"] is True
    assert bid["shelter_id"] == "SHELTER-01"
    assert bid["shelter_route_edge_ids"] == ["W-S"]
    assert bid["belief_version"] == 1


# ---------------- Step 02: ground team ----------------


def test_team_feasible_bid_needs_no_shelter_leg() -> None:
    team = GroundTeamAgent("TEAM-01", node_id="N-R", capabilities=["ground"])
    team.sense(
        _belief(
            [_edge_record("R-1", "N-R", "N-I", mode="road", travel=4, risk=0.2)],
            [],
        )
    )
    bid, reason = team.evaluate(_boat_request(capabilities=[]), 6)
    assert reason == "OK"
    assert set(bid) == EXPECTED_BID_KEYS
    assert bid["resource_kind"] == "team"
    assert bid["route_edge_ids"] == ["R-1"]
    assert bid["eta_ticks"] == 4
    assert bid["estimated_arrival"] == 10
    assert bid["estimated_completion"] == 12
    assert bid["seats"] == 4
    assert bid["shelter_id"] is None
    assert bid["shelter_route_edge_ids"] == []
    assert bid["fuel_feasible"] is True
    assert bid["shelter_feasible"] is True


def test_team_wrong_capability_rejected() -> None:
    team = GroundTeamAgent("TEAM-01", node_id="N-R", capabilities=["ground"])
    team.sense(
        _belief([_edge_record("R-1", "N-R", "N-I", mode="road")], [])
    )
    bid, reason = team.evaluate(_boat_request(capabilities=["boat"]), 0)
    assert (bid, reason) == (None, "MODE_MISMATCH")


def test_team_no_road_route_rejected() -> None:
    team = GroundTeamAgent("TEAM-01", node_id="N-R", capabilities=["ground"])
    team.sense(
        _belief([_edge_record("W-1", "N-R", "N-I", mode="water")], [])
    )
    bid, reason = team.evaluate(_boat_request(capabilities=["ground"]), 0)
    assert (bid, reason) == (None, "NO_ROUTE")


# ---------------- Step 02: shelter + report ----------------


def test_shelter_reserve_bid_full_books_rejects() -> None:
    shelter = ShelterAgent("SHELTER-01", "N-S", capacity=5, occupancy=3)
    shelter.reserved["HOLD-1"] = 2  # remaining 0 from the shelter's own books
    accept, remaining, reason = shelter.reserve_bid(1)
    assert (accept, remaining, reason) == (False, 0, "SHELTER_FULL")


def test_shelter_reserve_bid_ok_and_hold_helpers() -> None:
    shelter = ShelterAgent("SHELTER-01", "N-S", capacity=10)
    assert shelter.reserve_bid(4) == (True, 6, "OK")
    # reserve_bid is pure: no hold recorded.
    assert shelter.reserved == {}
    assert shelter.apply_hold("ASN-00001", 4) is True
    assert shelter.reserve_bid(7) == (False, 6, "SHELTER_FULL")
    assert shelter.release_hold("ASN-00001") == 4
    assert shelter.release_hold("ASN-unknown") == 0


def test_report_claim_shape_and_sequence() -> None:
    reporter = ReportAgent("UNIT-07")
    first = reporter.submit_claim("W-01", "EDGE_CLOSED", 12)
    second = reporter.submit_claim("W-01", "EDGE_OPEN", 13, confidence=0.5)
    assert first["report_id"] == "RPT-UNIT-07-0001"
    assert second["report_id"] == "RPT-UNIT-07-0002"
    assert first["verification_status"] == "UNVERIFIED"
    assert first["observed_at_tick"] == first["received_at_tick"] == 12
    assert first["source"] == "UNIT-07"
    assert second["confidence"] == 0.5


# ---------------- Step 02: 1 incident + 3 boats ----------------


def test_one_incident_three_boats_one_bid_two_distinct_rejections() -> None:
    """1 incident x 3 boats -> 1 bid + 2 rejections, reasons distinct."""
    belief = _belief(
        [
            _edge_record("W-1", "N-B1", "N-I", travel=3, risk=0.1),
            _edge_record("W-2", "N-B2", "N-I", travel=3, risk=0.1),
            _edge_record("W-S", "N-I", "N-S", travel=2, risk=0.1),
        ],
        [_shelter_record("SHELTER-01", "N-S", capacity=10)],
    )
    feasible = BoatAgent(
        "BOAT-OK", capacity=6, fuel=20.0, fuel_reserve=2.0, node_id="N-B1"
    )
    low_fuel = BoatAgent(
        "BOAT-LOW", capacity=6, fuel=3.0, fuel_reserve=2.0, node_id="N-B2"
    )
    failed = BoatAgent(
        "BOAT-DEAD",
        capacity=6,
        fuel=20.0,
        fuel_reserve=2.0,
        node_id="N-B1",
        status="FAILED",
    )
    for boat in (feasible, low_fuel, failed):
        boat.sense(belief)

    request = _boat_request(people=4)
    outcomes = [boat.evaluate(request, 0) for boat in (feasible, low_fuel, failed)]

    bids = [bid for bid, _ in outcomes if bid is not None]
    reasons = sorted(reason for bid, reason in outcomes if bid is None)
    assert len(bids) == 1
    assert bids[0]["agent_id"] == "BOAT-OK"
    assert set(bids[0]) == EXPECTED_BID_KEYS
    assert reasons == ["FUEL_INSUFFICIENT", "RESOURCE_UNAVAILABLE"]


# ====================================================
# STEP 03: negotiation scheduler flow (publish -> bids -> O-cost -> commit -> ack)
# ====================================================

import copy
import re
from pathlib import Path

from backend.app.dispatch.bid_evaluator import check_feasible
from backend.app.dispatch.commitment_manager import acknowledge
from backend.app.dispatch.negotiation_scheduler import (
    NegotiationScheduler,
    world_to_belief_snapshot,
)
from backend.app.dispatch.safety_validator import validate
from backend.app.dispatch.scheduler_interface import Scheduler
from backend.app.routing.route_validator import is_route_valid
from backend.app.simulation.engine import Simulation
from backend.app.simulation.run import build_world, load_scenario
from backend.app.simulation.state_manager import StateManager
from backend.app.simulation.world import Boat, Edge, Incident, Node, Shelter, World


def _negotiation_world_two_boats() -> World:
    """One boat incident, two boats at different distances, one shelter."""
    nodes = {
        nid: Node(node_id=nid, neighborhood="n", kind="incident_site", x=0.0, y=0.0)
        for nid in ("N-B1", "N-B2", "N-I", "N-S")
    }
    edges = {
        "W-1": Edge(
            edge_id="W-1", from_node="N-B1", to_node="N-I", mode="water",
            travel_time=2, status="open", risk_level=0.1, capacity=10,
        ),
        "W-2": Edge(
            edge_id="W-2", from_node="N-B2", to_node="N-I", mode="water",
            travel_time=5, status="open", risk_level=0.1, capacity=10,
        ),
        "W-S": Edge(
            edge_id="W-S", from_node="N-I", to_node="N-S", mode="water",
            travel_time=1, status="open", risk_level=0.1, capacity=10,
        ),
    }
    return World(
        nodes=nodes,
        edges=edges,
        incidents={
            "INC-01": Incident(
                incident_id="INC-01", node_id="N-I", urgency=4, people=2,
                required_capabilities=["boat"], created_tick=0,
            )
        },
        boats={
            "BOAT-01": Boat(
                boat_id="BOAT-01", node_id="N-B1", capacity=6,
                fuel=20.0, fuel_reserve=2.0,
            ),
            "BOAT-02": Boat(
                boat_id="BOAT-02", node_id="N-B2", capacity=6,
                fuel=20.0, fuel_reserve=2.0,
            ),
        },
        shelters={
            "SHELTER-01": Shelter(shelter_id="SHELTER-01", node_id="N-S", capacity=10)
        },
    )


def _negotiation_world_single_boat() -> World:
    """One boat, one incident, one shelter; boat starts away from the site."""
    nodes = {
        nid: Node(node_id=nid, neighborhood="n", kind="incident_site", x=0.0, y=0.0)
        for nid in ("N-A", "N-I", "N-S")
    }
    edges = {
        "W-A": Edge(
            edge_id="W-A", from_node="N-A", to_node="N-I", mode="water",
            travel_time=2, status="open", risk_level=0.1, capacity=10,
        ),
        "W-S": Edge(
            edge_id="W-S", from_node="N-I", to_node="N-S", mode="water",
            travel_time=1, status="open", risk_level=0.1, capacity=10,
        ),
    }
    return World(
        nodes=nodes,
        edges=edges,
        incidents={
            "INC-01": Incident(
                incident_id="INC-01", node_id="N-I", urgency=4, people=2,
                required_capabilities=["boat"], created_tick=0,
            )
        },
        boats={
            "BOAT-01": Boat(
                boat_id="BOAT-01", node_id="N-A", capacity=6,
                fuel=20.0, fuel_reserve=2.0,
            )
        },
        shelters={
            "SHELTER-01": Shelter(shelter_id="SHELTER-01", node_id="N-S", capacity=10)
        },
    )


def test_negotiation_scheduler_satisfies_protocol() -> None:
    assert isinstance(NegotiationScheduler(), Scheduler)
    assert NegotiationScheduler().strategy == "negotiation"


def test_snapshot_has_no_live_references() -> None:
    world = _negotiation_world_single_boat()
    snapshot = world_to_belief_snapshot(world)
    assert set(snapshot) >= {"edges", "shelters", "tick", "version"}
    assert snapshot["version"] == snapshot["tick"] == world.tick
    assert snapshot["edges"]["W-A"]["status"] == "open"
    assert snapshot["shelters"]["SHELTER-01"]["remaining"] == 10
    # Mutating the caller's snapshot must not touch the world.
    snapshot["edges"]["W-A"]["status"] = "closed"
    assert world.edges["W-A"].status == "open"
    # Mutating the world after the snapshot must not touch the snapshot.
    pristine = world_to_belief_snapshot(world)
    world.edges["W-A"].status = "closed"
    assert pristine["edges"]["W-A"]["status"] == "open"
    fresh = world_to_belief_snapshot(world)
    assert fresh["edges"]["W-A"]["status"] == "closed"


def test_two_boats_same_incident_lower_cost_wins() -> None:
    scheduler = NegotiationScheduler()
    world = _negotiation_world_two_boats()
    proposals = scheduler.propose(world, tick=5)
    assert len(proposals) == 1
    winner = proposals[0]
    # Closer boat (BOAT-01, eta 2) beats BOAT-02 (eta 5).
    assert winner.incident_id == "INC-01"
    assert winner.resource_id == "BOAT-01"
    assert winner.proposal_id == "PROP-0005-000"
    assert "NEGOTIATED" in winner.reasons
    assert winner.route_edge_ids == ["W-1"]
    loser_reasons = [
        entry for entry in scheduler.last_rejections
        if entry["incident_id"] == "INC-01" and entry["resource_id"] == "BOAT-02"
    ]
    assert len(loser_reasons) == 1
    assert re.search(
        r"HIGHER_COST: winner BOAT-\d+ cost \d+\.\d+ vs \d+\.\d+",
        loser_reasons[0]["reason"],
    ), loser_reasons[0]["reason"]
    assert f"winner {winner.resource_id}" in loser_reasons[0]["reason"]


def test_stale_bid_safety_gate_rejects_closed_edge() -> None:
    scheduler = NegotiationScheduler()
    world = _negotiation_world_single_boat()
    tick = 5
    proposals = scheduler.propose(world, tick=tick)
    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal.route_edge_ids, "expected a non-empty incident leg"
    assert proposal.seats > 0

    # Global closure AFTER the bid (stale bid): the safety tail must reject.
    closed_edge = proposal.route_edge_ids[0]
    world.edges[closed_edge].status = "closed"

    manager = StateManager(world)
    assignments: dict = {}
    ok, code = check_feasible(
        world,
        proposal.incident_id,
        proposal.resource_id,
        proposal.shelter_id,
        list(proposal.route_edge_ids),
        tick,
        proposal.seats,
    )
    assert ok is False
    assert "EDGE_CLOSED" in code

    passed, violations = validate(world, proposal, tick, assignments)
    assert passed is False
    assert any(v.startswith("EDGE_CLOSED") for v in violations), violations

    # Gated tail: no commit on safety refusal, incident stays OPEN.
    assert assignments == {}
    assert world.incidents[proposal.incident_id].status == "OPEN"
    _ = manager  # StateManager owns the world the tail validated against.


def test_ack_flow_commit_then_acknowledge_distinct() -> None:
    scheduler = NegotiationScheduler()
    world = _negotiation_world_single_boat()
    tick = 5
    proposals = scheduler.propose(world, tick=tick)
    assert len(proposals) == 1
    proposal = proposals[0]

    manager = StateManager(world)
    assignments: dict = {}
    proposals_seen: dict = {}
    assignment, code = scheduler.commit(
        world, proposal, tick, manager=manager,
        assignments=assignments, proposals_seen=proposals_seen,
    )
    assert code == "OK" and assignment is not None
    assert assignment.status == "COMMITTED"
    assert len(assignment.history) == 1
    assert assignment.history[0]["from"] == "PROPOSED"
    assert assignment.history[0]["to"] == "COMMITTED"

    ok, msg = acknowledge(
        manager, assignments, assignment.assignment_id, tick + 1,
        actor="dispatch", reason="field unit ack",
    )
    assert (ok, msg) == (True, "OK")
    committed = assignments[assignment.assignment_id]
    assert committed.status == "ACKNOWLEDGED"
    assert len(committed.history) == 2
    assert committed.history[0]["to"] == "COMMITTED"
    assert committed.history[1]["from"] == "COMMITTED"
    assert committed.history[1]["to"] == "ACKNOWLEDGED"
    kinds = [entry["kind"] for entry in manager.event_log]
    assert "COMMITTED" in kinds
    assert "ACKNOWLEDGED" in kinds


def test_negotiation_engine_smoke_10_ticks_all_committed_routes_valid() -> None:
    baseline = Path(__file__).resolve().parent.parent.parent / "scenarios" / "baseline.json"
    data = load_scenario(baseline)
    world = build_world(copy.deepcopy(data), seed=42)
    scheduler = NegotiationScheduler()
    simulation = Simulation(world, seed=42, scheduler=scheduler)
    for event in data.get("events", []):
        if int(event["tick"]) <= 10:
            simulation.manager.scheduler.push(
                int(event["tick"]), str(event["kind"]),
                dict(event.get("payload", {})), str(event["event_id"]),
            )
    final_tick = simulation.run(10)
    assert final_tick == 10

    # Zero safety violations: every committed assignment route still validates.
    assert len(simulation.assignments) > 0, "expected at least one commit in 10 ticks"
    for assignment in simulation.assignments.values():
        mode = "water" if assignment.resource_kind == "boat" else "road"
        valid, reason = is_route_valid(
            simulation.world, list(assignment.route_edge_ids), mode  # type: ignore[arg-type]
        )
        assert valid, f"{assignment.assignment_id} invalid: {reason}"
    rejected_edge_closed = [
        entry for entry in simulation.manager.event_log
        if entry["kind"] == "REJECTED"
        and "EDGE_CLOSED" in str(entry["detail"].get("reason", ""))
    ]
    assert rejected_edge_closed == []

    served = sum(
        1 for incident in simulation.world.incidents.values()
        if incident.status == "SERVED"
    )
    assert isinstance(served, int) and served >= 0
    # Validity, not parity with centralized: served count is reported.
    assert served + sum(
        1 for incident in simulation.world.incidents.values()
        if incident.status != "SERVED"
    ) == len(simulation.world.incidents)


# ====================================================
# STEP 04: strategy switch + parity (centralized vs negotiation)
# ====================================================

import pytest

from backend.app.evaluation.experiment_runner import run_pair
from backend.app.simulation.run import build_simulation, main


def _committed_triples(simulation) -> list[tuple]:
    """Sorted (proposal_id, assignment_id, resource_id) per COMMITTED log."""
    triples = []
    for entry in simulation.manager.event_log:
        if entry["kind"] != "COMMITTED":
            continue
        detail = entry["detail"]
        triples.append(
            (
                detail.get("proposal_id"),
                detail.get("assignment_id"),
                detail.get("resource_id"),
            )
        )
    return sorted(triples)


def _run_baseline(strategy: str, ticks: int = 30, seed: int = 42):
    baseline = Path(__file__).resolve().parent.parent.parent / "scenarios" / "baseline.json"
    data = load_scenario(baseline)
    simulation = build_simulation(copy.deepcopy(data), seed=seed, strategy=strategy)
    simulation.run(ticks)
    return simulation


def test_strategy_determinism_centralized_twice_identical() -> None:
    first = _committed_triples(_run_baseline("centralized"))
    second = _committed_triples(_run_baseline("centralized"))
    assert len(first) > 0
    assert first == second


def test_strategy_determinism_negotiation_twice_identical() -> None:
    first = _committed_triples(_run_baseline("negotiation"))
    second = _committed_triples(_run_baseline("negotiation"))
    assert len(first) > 0
    assert first == second


def test_run_pair_baseline_both_complete_zero_violations() -> None:
    baseline = Path(__file__).resolve().parent.parent.parent / "scenarios" / "baseline.json"
    pair = run_pair(baseline, ticks=30, seed=42)
    assert set(pair) == {"centralized", "negotiation"}
    for strategy in ("centralized", "negotiation"):
        entry = pair[strategy]
        assert entry["strategy"] == strategy
        assert entry["ticks"] == 30
        assert isinstance(entry["committed"], int) and entry["committed"] > 0
        assert isinstance(entry["rejected_by_reason"], dict)
        assert isinstance(entry["served"], int) and entry["served"] >= 0

    # Zero safety violations: every committed assignment route validates.
    for strategy in ("centralized", "negotiation"):
        simulation = _run_baseline(strategy)
        assert len(simulation.assignments) > 0
        for assignment in simulation.assignments.values():
            mode = "water" if assignment.resource_kind == "boat" else "road"
            valid, reason = is_route_valid(
                simulation.world, list(assignment.route_edge_ids), mode  # type: ignore[arg-type]
            )
            assert valid, f"{strategy} {assignment.assignment_id} invalid: {reason}"


def test_cli_bogus_strategy_exits_2_no_partial_run(monkeypatch, capsys) -> None:
    baseline = Path(__file__).resolve().parent.parent.parent / "scenarios" / "baseline.json"
    import backend.app.simulation.run as run_module

    called = {"built": False}
    real_build = run_module.build_simulation

    def _guard(*args, **kwargs):
        called["built"] = True
        return real_build(*args, **kwargs)

    monkeypatch.setattr(run_module, "build_simulation", _guard)
    with pytest.raises(SystemExit) as exc:
        main(["--scenario", str(baseline), "--strategy", "bogus"])
    assert exc.value.code == 2
    assert called["built"] is False  # argparse rejected before any run
    out, err = capsys.readouterr()
    assert "strategy:" not in out  # no summary printed on usage error


def test_cli_negotiation_strategy_prints_line(capsys) -> None:
    baseline = Path(__file__).resolve().parent.parent.parent / "scenarios" / "baseline.json"
    code = main(
        ["--scenario", str(baseline), "--strategy", "negotiation", "--ticks", "5"]
    )
    assert code == 0
    out, _ = capsys.readouterr()
    assert "strategy: negotiation" in out
