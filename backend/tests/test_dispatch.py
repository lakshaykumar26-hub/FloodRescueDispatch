"""Phase 2 Steps 01-02: scheduler interface + centralized greedy scheduler
(see docs/phase-2-centralized-dispatch/step-01-scheduler-interface.md and
step-02-centralized-scheduler.md)."""

import math
from typing import Any

from backend.app.dispatch.centralized_scheduler import CentralizedScheduler
from backend.app.dispatch.scheduler_interface import ProposedAssignment, Scheduler
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


class StubScheduler:
    strategy: str = "centralized"

    def propose(self, world: World, tick: int) -> list[ProposedAssignment]:
        return []

    def commit(
        self,
        world: World,
        proposal: ProposedAssignment,
        tick: int,
        *,
        manager: Any,
        assignments: dict,
        proposals_seen: dict,
    ) -> tuple[Any, str]:
        return None, "STUB:NOT_IMPLEMENTED"


def test_stub_satisfies_scheduler_protocol() -> None:
    assert isinstance(StubScheduler(), Scheduler)


def test_propose_on_empty_world_returns_empty_without_raising() -> None:
    world = World()
    assert world.incidents == {}
    assert StubScheduler().propose(world, tick=0) == []


# --- Phase 2 Step 02: CentralizedScheduler ---


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


def _boat(
    boat_id: str = "BOAT-01",
    node_id: str = "N-A",
    capacity: int = 6,
    status: str = "AVAILABLE",
) -> Boat:
    return Boat(
        boat_id=boat_id,
        node_id=node_id,
        capacity=capacity,
        fuel=20.0,
        fuel_reserve=2.0,
        status=status,  # type: ignore[arg-type]
    )


def _team(team_id: str = "TEAM-01", node_id: str = "N-T") -> GroundTeam:
    return GroundTeam(
        team_id=team_id,
        node_id=node_id,
        capabilities=["ground"],
    )


def _water_world_two_incidents_one_boat(
    hi_caps: list | None = None,
    lo_caps: list | None = None,
) -> World:
    """One boat, two boat incidents, one shelter reachable from both sites."""
    return World(
        nodes={
            "N-A": _node("N-A"),
            "N-HI": _node("N-HI", "incident_site"),
            "N-LO": _node("N-LO", "incident_site"),
            "N-S": _node("N-S", "shelter"),
        },
        edges={
            "W-A-HI": _edge("W-A-HI", "N-A", "N-HI", travel_time=2),
            "W-A-LO": _edge("W-A-LO", "N-A", "N-LO", travel_time=3),
            "W-HI-S": _edge("W-HI-S", "N-HI", "N-S", travel_time=2),
            "W-LO-S": _edge("W-LO-S", "N-LO", "N-S", travel_time=4),
        },
        incidents={
            "INC-HI": Incident(
                incident_id="INC-HI", node_id="N-HI", urgency=5, people=2,
                required_capabilities=hi_caps if hi_caps is not None else ["boat"],
            ),
            "INC-LO": Incident(
                incident_id="INC-LO", node_id="N-LO", urgency=2, people=2,
                required_capabilities=lo_caps if lo_caps is not None else ["boat"],
            ),
        },
        boats={"BOAT-01": _boat()},
        shelters={
            "SHELTER-01": Shelter(shelter_id="SHELTER-01", node_id="N-S", capacity=10)
        },
    )


def _mixed_mode_world() -> World:
    """Water incident reachable only by water, road incident only by road."""
    return World(
        nodes={
            "N-B": _node("N-B"),
            "N-WI": _node("N-WI", "incident_site"),
            "N-S": _node("N-S", "shelter"),
            "N-T": _node("N-T"),
            "N-RI": _node("N-RI", "incident_site"),
        },
        edges={
            "W-B-WI": _edge("W-B-WI", "N-B", "N-WI", travel_time=2),
            "W-WI-S": _edge("W-WI-S", "N-WI", "N-S", travel_time=2),
            "R-T-RI": _edge("R-T-RI", "N-T", "N-RI", mode="road", travel_time=3),
        },
        incidents={
            "INC-W": Incident(
                incident_id="INC-W", node_id="N-WI", urgency=4, people=3,
                required_capabilities=["boat"],
            ),
            "INC-R": Incident(
                incident_id="INC-R", node_id="N-RI", urgency=4, people=3,
                required_capabilities=["ground"],
            ),
        },
        boats={"BOAT-01": _boat(node_id="N-B")},
        teams={"TEAM-01": _team()},
        shelters={
            "SHELTER-01": Shelter(shelter_id="SHELTER-01", node_id="N-S", capacity=10)
        },
    )


def test_scheduler_satisfies_protocol() -> None:
    assert isinstance(CentralizedScheduler(), Scheduler)


def test_propose_empty_world_returns_empty_without_raising() -> None:
    scheduler = CentralizedScheduler()
    assert scheduler.propose(World(), tick=0) == []
    assert scheduler.last_rejections == []


def test_higher_urgency_wins_single_boat_loser_claimed() -> None:
    scheduler = CentralizedScheduler()
    world = _water_world_two_incidents_one_boat()
    proposals = scheduler.propose(world, tick=5)
    assert len(proposals) == 1
    winner = proposals[0]
    assert winner.incident_id == "INC-HI"
    assert winner.resource_id == "BOAT-01"
    assert winner.proposal_id == "PROP-0005-000"
    assert "RANK_SELECTED" in winner.reasons
    losers = [
        r for r in scheduler.last_rejections if r["incident_id"] == "INC-LO"
    ]
    assert any(
        r["resource_id"] == "BOAT-01"
        and r["reason"] == "RESOURCE_CLAIMED:HIGHER_RANK"
        for r in losers
    )


def test_all_boats_failed_returns_empty_without_raising() -> None:
    scheduler = CentralizedScheduler()
    world = _water_world_two_incidents_one_boat()
    world.boats["BOAT-01"].status = "FAILED"
    assert scheduler.propose(world, tick=5) == []


def test_no_cross_mode_proposals() -> None:
    scheduler = CentralizedScheduler()
    world = _mixed_mode_world()
    proposals = scheduler.propose(world, tick=3)
    assert len(proposals) == 2
    by_incident = {p.incident_id: p for p in proposals}
    boat_proposal = by_incident["INC-W"]
    team_proposal = by_incident["INC-R"]
    assert boat_proposal.resource_kind == "boat"
    assert boat_proposal.resource_id == "BOAT-01"
    assert team_proposal.resource_kind == "team"
    assert team_proposal.resource_id == "TEAM-01"
    assert team_proposal.shelter_id is None
    assert team_proposal.shelter_route_edge_ids == []
    for proposal in proposals:
        caps = world.incidents[proposal.incident_id].required_capabilities
        if proposal.resource_kind == "boat":
            assert "boat" in caps
        else:
            assert "ground" in caps


def test_proposal_carries_eta_and_finite_cost() -> None:
    scheduler = CentralizedScheduler()
    world = _water_world_two_incidents_one_boat()
    world.incidents["INC-LO"].status = "SERVED"
    proposals = scheduler.propose(world, tick=42)
    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal.proposal_id == "PROP-0042-000"
    assert proposal.route_edge_ids == ["W-A-HI"]
    assert proposal.eta_ticks == 2
    assert proposal.shelter_route_edge_ids == ["W-HI-S"]
    assert proposal.shelter_eta_ticks == 2
    assert proposal.seats == 2
    assert math.isfinite(proposal.cost)


def test_empty_capabilities_still_match_boats() -> None:
    scheduler = CentralizedScheduler()
    world = _water_world_two_incidents_one_boat(hi_caps=[], lo_caps=[])
    world.incidents["INC-LO"].status = "SERVED"
    proposals = scheduler.propose(world, tick=1)
    assert len(proposals) == 1
    assert proposals[0].resource_kind == "boat"


def test_boat_ground_incident_gets_boat_leg_only_note() -> None:
    scheduler = CentralizedScheduler()
    world = _water_world_two_incidents_one_boat(hi_caps=["boat", "ground"])
    world.incidents["INC-LO"].status = "SERVED"
    proposals = scheduler.propose(world, tick=1)
    assert len(proposals) == 1
    assert proposals[0].resource_kind == "boat"
    assert "MULTI_STAGE:BOAT_LEG_ONLY" in proposals[0].reasons


def test_commit_delegates_to_commitment_manager() -> None:
    scheduler = CentralizedScheduler()
    world = _water_world_two_incidents_one_boat()
    world.incidents["INC-LO"].status = "SERVED"
    proposals = scheduler.propose(world, tick=5)
    assert len(proposals) == 1
    manager = StateManager(world)
    assignments: dict = {}
    seen: dict = {}
    assignment, code = scheduler.commit(
        world, proposals[0], 5, manager=manager,
        assignments=assignments, proposals_seen=seen,
    )
    assert code == "OK" and assignment is not None
    assert assignment.status == "COMMITTED"
    assert world.boats["BOAT-01"].status == "ASSIGNED"
