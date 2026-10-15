"""Phase 2 Step 04: conflict resolution + commitment manager (see docs/phase-2-centralized-dispatch/step-04-commitments-conflicts.md)."""

from backend.app.dispatch.commitment_manager import (
    cancel,
    commit_assignment,
)
from backend.app.dispatch.conflict_resolver import resolve
from backend.app.dispatch.scheduler_interface import ProposedAssignment
from backend.app.simulation.state_manager import StateManager
from backend.app.simulation.world import Boat, Incident, Shelter, World


def _proposal(
    proposal_id: str,
    incident_id: str,
    resource_id: str,
    cost: float,
    tick: int,
    shelter_id: str | None = None,
    seats: int = 2,
    kind: str = "boat",
) -> ProposedAssignment:
    return ProposedAssignment(
        proposal_id=proposal_id,
        incident_id=incident_id,
        resource_id=resource_id,
        resource_kind=kind,  # type: ignore[arg-type]
        shelter_id=shelter_id,
        seats=seats,
        route_edge_ids=[],
        eta_ticks=1,
        cost=cost,
        created_tick=tick,
    )


def _world_resource_conflict() -> World:
    return World(
        incidents={
            "INC-01": Incident(incident_id="INC-01", node_id="N-01", urgency=5, people=2),
            "INC-02": Incident(incident_id="INC-02", node_id="N-02", urgency=4, people=2),
        },
        boats={
            "BOAT-01": Boat(
                boat_id="BOAT-01", node_id="N-01", capacity=4,
                fuel=10.0, fuel_reserve=2.0,
            )
        },
    )


def test_resource_contention_exactly_one_committed() -> None:
    world = _world_resource_conflict()
    manager = StateManager(world)
    tick = 5
    proposals = [
        _proposal("PROP-01", "INC-01", "BOAT-01", cost=10.0, tick=tick),
        _proposal("PROP-02", "INC-02", "BOAT-01", cost=20.0, tick=tick),
    ]
    winners, rejections = resolve(proposals, world, tick)
    assert len(winners) == 1 and len(rejections) == 1
    assert winners[0].proposal_id == "PROP-01"
    assert rejections[0]["proposal_id"] == "PROP-02"
    assert rejections[0]["reason"] == "RESOURCE_CONFLICT:WINNER=PROP-01"

    assignments: dict = {}
    seen: dict = {}
    assignment, code = commit_assignment(
        manager, winners[0], tick, "ASN-00001", assignments, seen
    )
    assert code == "OK" and assignment is not None
    assert assignment.status == "COMMITTED"
    assert world.boats["BOAT-01"].status == "ASSIGNED"


def _world_shelter_conflict() -> World:
    return World(
        incidents={
            "INC-01": Incident(incident_id="INC-01", node_id="N-01", urgency=5, people=1),
            "INC-02": Incident(incident_id="INC-02", node_id="N-02", urgency=3, people=1),
        },
        boats={
            "BOAT-01": Boat(
                boat_id="BOAT-01", node_id="N-01", capacity=4,
                fuel=10.0, fuel_reserve=2.0,
            ),
            "BOAT-02": Boat(
                boat_id="BOAT-02", node_id="N-02", capacity=4,
                fuel=10.0, fuel_reserve=2.0,
            ),
        },
        shelters={
            "SH-01": Shelter(
                shelter_id="SH-01", node_id="N-09", capacity=3, occupancy=2
            )
        },
    )


def test_shelter_last_bed_one_committed() -> None:
    world = _world_shelter_conflict()
    manager = StateManager(world)
    tick = 7
    proposals = [
        _proposal("PROP-A", "INC-01", "BOAT-01", cost=5.0, tick=tick,
                  shelter_id="SH-01", seats=1),
        _proposal("PROP-B", "INC-02", "BOAT-02", cost=6.0, tick=tick,
                  shelter_id="SH-01", seats=1),
    ]
    winners, rejections = resolve(proposals, world, tick)
    assert len(winners) == 1 and len(rejections) == 1
    assert rejections[0]["reason"] == "SHELTER_CONFLICT"

    assignments: dict = {}
    seen: dict = {}
    assignment, code = commit_assignment(
        manager, winners[0], tick, "ASN-00001", assignments, seen
    )
    assert code == "OK" and assignment is not None
    shelter = world.shelters["SH-01"]
    assert shelter.occupancy + sum(shelter.reservations.values()) <= shelter.capacity

    loser = next(p for p in proposals if p.proposal_id == rejections[0]["proposal_id"])
    assignment2, code2 = commit_assignment(
        manager, loser, tick, "ASN-00002", assignments, seen
    )
    assert assignment2 is None and code2 == "SHELTER_FULL_AT_COMMIT"
    assert shelter.occupancy + sum(shelter.reservations.values()) <= shelter.capacity


def test_cancel_frees_boat_and_seats_with_history() -> None:
    world = World(
        incidents={
            "INC-01": Incident(incident_id="INC-01", node_id="N-01", urgency=5, people=2),
        },
        boats={
            "BOAT-01": Boat(
                boat_id="BOAT-01", node_id="N-01", capacity=4,
                fuel=10.0, fuel_reserve=2.0,
            )
        },
        shelters={
            "SH-01": Shelter(shelter_id="SH-01", node_id="N-09", capacity=5)
        },
    )
    manager = StateManager(world)
    tick = 3
    proposal = _proposal("PROP-01", "INC-01", "BOAT-01", cost=1.0, tick=tick,
                         shelter_id="SH-01", seats=2)
    assignments: dict = {}
    seen: dict = {}
    assignment, code = commit_assignment(
        manager, proposal, tick, "ASN-00001", assignments, seen
    )
    assert code == "OK" and assignment is not None
    assert world.shelter_remaining("SH-01") == 3
    history_len = len(assignment.history)

    ok, msg = cancel(manager, assignments, "ASN-00001", tick + 1,
                     actor="dispatch", reason="test cancel")
    assert (ok, msg) == (True, "OK")
    assert world.boats["BOAT-01"].status == "AVAILABLE"
    assert world.boats["BOAT-01"].assignment_id is None
    assert world.shelter_remaining("SH-01") == 5
    assert world.incidents["INC-01"].status == "OPEN"
    assert assignments["ASN-00001"].status == "CANCELLED"
    assert len(assignments["ASN-00001"].history) == history_len + 1
    assert assignments["ASN-00001"].history[-1]["to"] == "CANCELLED"


def test_double_commit_same_proposal_single_assignment() -> None:
    world = _world_resource_conflict()
    manager = StateManager(world)
    tick = 5
    proposal = _proposal("PROP-01", "INC-01", "BOAT-01", cost=10.0, tick=tick)
    assignments: dict = {}
    seen: dict = {}
    first, code1 = commit_assignment(
        manager, proposal, tick, "ASN-00001", assignments, seen
    )
    assert code1 == "OK" and first is not None
    second, code2 = commit_assignment(
        manager, proposal, tick, "ASN-00002", assignments, seen
    )
    assert code2 == "DUPLICATE:RETURNED_EXISTING"
    assert second is first
    assert second.assignment_id == "ASN-00001"
    assert second.version == 1
    assert len(assignments) == 1


def test_cancel_mid_mission_boat_returns_available() -> None:
    """Cancel while the boat is RESCUING frees it via the RETURNING fallback."""
    world = _world_resource_conflict()
    manager = StateManager(world)
    tick = 5
    proposal = _proposal("PROP-01", "INC-01", "BOAT-01", cost=10.0, tick=tick)
    assignments: dict = {}
    seen: dict = {}
    assignment, code = commit_assignment(
        manager, proposal, tick, "ASN-00001", assignments, seen
    )
    assert code == "OK" and assignment is not None
    ok, _ = manager.transition_boat(
        "BOAT-01", "EN_ROUTE_TO_INCIDENT", reason="depart", tick=tick, actor="engine"
    )
    assert ok is True
    ok, _ = manager.transition_boat(
        "BOAT-01", "RESCUING", reason="on scene", tick=tick, actor="engine"
    )
    assert ok is True

    ok, msg = cancel(manager, assignments, "ASN-00001", tick + 1,
                     actor="dispatch", reason="test cancel mid-mission")
    assert (ok, msg) == (True, "OK")
    assert world.boats["BOAT-01"].status == "AVAILABLE"
    assert world.boats["BOAT-01"].assignment_id is None
    assert assignments["ASN-00001"].status == "CANCELLED"
