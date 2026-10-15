"""Negotiation scheduler flow (Phase 3 Step 03; spec sections 7.2-7.4).

Pipeline: incident agents publish requests -> eligible resource agents bid
from LOCAL BELIEF only (Step 02 ``evaluate``) -> lowest base-cost feasible
bid wins per incident with opportunity cost ``O = second_best - best``
(``0.0`` when only one bid; ``cost = base + w_o * O``) -> claim set stops
two incidents taking the same resource in one tick -> the engine tail
(``check_feasible`` + authoritative ``safety_validator.validate`` +
``commitment_manager.commit_assignment``) still gates every winner.

Synchronous in-process for MVP: ``propose`` calls ``publish_request`` and
``evaluate`` directly in sorted-ID order. Phase 5 will slot
``await gateway.send()`` around the publish/bid exchange (request delivery
+ bid collection become async messages with ACK/retry/dedup/expiry);
the ``propose``/``commit`` signatures stay unchanged.

Determinism: incidents in ``rank_key`` order; candidates in ``agent_id``
order; ties broken by lower ``agent_id``; ``proposal_id`` derived from
``(tick, rank index)`` as ``PROP-%04d-%03d`` (same as centralized, gaps
when an incident yields no proposal).
"""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any

from ..agents.boat_agent import BoatAgent
from ..agents.ground_team_agent import GroundTeamAgent
from ..agents.incident_agent import IncidentAgent
from ..agents.shelter_agent import ShelterAgent
from .bid_evaluator import score
from .commitment_manager import commit_assignment
from .scheduler_interface import (
    DEFAULT_WEIGHTS,
    Assignment,
    ProposedAssignment,
    Weights,
    rank_key,
)

if TYPE_CHECKING:
    from ..simulation.world import World


def world_to_belief_snapshot(world: World) -> dict:
    """Build a deep-copied plain-dict belief snapshot from ``world``.

    Shape: ``{edges: {id: {edge_id, from_node, to_node, mode, travel_time,
    status, risk_level, capacity}}, shelters: {id: {node_id, remaining}},
    tick, version: tick}``. All values are fresh plain objects; no live
    ``World`` references leak (mutating the snapshot or the world
    afterwards does not affect the other).
    """
    edges: dict[str, dict] = {}
    for edge_id, edge in world.edges.items():
        edges[edge_id] = {
            "edge_id": edge.edge_id,
            "from_node": edge.from_node,
            "to_node": edge.to_node,
            "mode": edge.mode,
            "travel_time": edge.travel_time,
            "status": edge.status,
            "risk_level": edge.risk_level,
            "capacity": edge.capacity,
        }
    shelters: dict[str, dict] = {}
    for shelter_id, shelter in world.shelters.items():
        try:
            remaining = world.shelter_remaining(shelter_id)
        except (KeyError, AttributeError):
            capacity = getattr(shelter, "capacity", 0)
            occupancy = getattr(shelter, "occupancy", 0)
            reservations = getattr(shelter, "reservations", {})
            held = sum(reservations.values()) if isinstance(reservations, dict) else 0
            remaining = capacity - occupancy - held
        shelters[shelter_id] = {
            "node_id": getattr(shelter, "node_id", ""),
            "remaining": int(remaining),
        }
    tick = int(getattr(world, "tick", 0))
    return {
        "edges": copy.deepcopy(edges),
        "shelters": copy.deepcopy(shelters),
        "tick": tick,
        "version": tick,
    }


class NegotiationScheduler:
    """Agent-negotiation dispatch strategy (spec section 7.2 pipeline)."""

    strategy: str = "negotiation"

    def __init__(self, weights: Weights | None = None) -> None:
        self.weights = weights if weights is not None else DEFAULT_WEIGHTS
        self.last_rejections: list[dict] = []
        # Persistent across propose() calls within a run so belief_version grows.
        self.agents: dict[str, Any] = {}

    def _sync_agents(self, world: World, tick: int) -> None:
        """Create-or-update one agent per world entity and refresh beliefs.

        Incident fields, boat/team position + status (+ fuel/passengers),
        and shelter books are refreshed from ``world``; every synced agent
        then gets ``sense(world_to_belief_snapshot(world))``. Iteration is
        in sorted-ID order for determinism. ``tick`` is accepted for future
        staleness accounting and does not affect the sync itself.
        """
        _ = tick  # reserved for future staleness/expiry bookkeeping.
        snapshot = world_to_belief_snapshot(world)

        for incident_id in sorted(world.incidents):
            incident = world.incidents[incident_id]
            agent = self.agents.get(incident_id)
            if not isinstance(agent, IncidentAgent):
                agent = IncidentAgent(
                    incident.incident_id,
                    incident.node_id,
                    incident.urgency,
                    incident.people,
                    list(incident.required_capabilities or []),
                    incident.created_tick,
                )
                self.agents[incident_id] = agent
            else:
                agent.node_id = incident.node_id
                agent.urgency = incident.urgency
                agent.people = incident.people
                agent.capabilities = list(incident.required_capabilities or [])
                agent.created_tick = incident.created_tick
            agent.sense(snapshot)

        for boat_id in sorted(world.boats):
            boat = world.boats[boat_id]
            agent = self.agents.get(boat_id)
            if not isinstance(agent, BoatAgent):
                agent = BoatAgent(
                    boat.boat_id,
                    boat.capacity,
                    float(boat.fuel),
                    float(boat.fuel_reserve),
                    float(getattr(boat, "speed", 1.0)),
                    node_id=boat.node_id,
                    status=boat.status,
                    passengers=int(getattr(boat, "passengers", 0)),
                )
                self.agents[boat_id] = agent
            else:
                agent.capacity = boat.capacity
                agent.fuel = float(boat.fuel)
                agent.fuel_reserve = float(boat.fuel_reserve)
                agent.speed = float(getattr(boat, "speed", 1.0))
                agent.node_id = boat.node_id
                agent.status = boat.status
                agent.passengers = int(getattr(boat, "passengers", 0))
            agent.sense(snapshot)

        for team_id in sorted(world.teams):
            team = world.teams[team_id]
            agent = self.agents.get(team_id)
            if not isinstance(agent, GroundTeamAgent):
                agent = GroundTeamAgent(
                    team.team_id,
                    team.node_id,
                    list(team.capabilities or []),
                    status=team.status,
                )
                self.agents[team_id] = agent
            else:
                agent.node_id = team.node_id
                agent.capabilities = list(team.capabilities or [])
                agent.status = team.status
            agent.sense(snapshot)

        for shelter_id in sorted(world.shelters):
            shelter = world.shelters[shelter_id]
            agent = self.agents.get(shelter_id)
            if not isinstance(agent, ShelterAgent):
                agent = ShelterAgent(
                    shelter.shelter_id,
                    shelter.node_id,
                    shelter.capacity,
                    occupancy=int(getattr(shelter, "occupancy", 0)),
                )
                reservations = getattr(shelter, "reservations", {})
                if isinstance(reservations, dict):
                    agent.reserved = dict(reservations)
                self.agents[shelter_id] = agent
            else:
                agent.node_id = shelter.node_id
                agent.capacity = shelter.capacity
                agent.occupancy = int(getattr(shelter, "occupancy", 0))
                reservations = getattr(shelter, "reservations", {})
                if isinstance(reservations, dict):
                    agent.reserved = dict(reservations)
            agent.sense(snapshot)

    def propose(self, world: World, tick: int) -> list[ProposedAssignment]:
        """Collect bids and emit at most one negotiated proposal per incident.

        Never mutates ``world`` and never raises on empty/degraded worlds
        (returns ``[]`` with rejections recorded when nothing is feasible).
        """
        rejections: list[dict] = []
        try:
            self._sync_agents(world, tick)
        except Exception:  # degraded world: no agents, no proposals.
            self.last_rejections = []
            return []

        try:
            incidents = [
                incident
                for incident in world.incidents.values()
                if incident.status == "OPEN" and incident.created_tick <= tick
            ]
        except Exception:
            self.last_rejections = []
            return []
        ranked = sorted(
            incidents,
            key=lambda incident: rank_key(
                incident.urgency,
                tick - incident.created_tick,
                incident.people,
                incident.incident_id,
            ),
        )

        claimed: set[str] = set()
        proposals: list[ProposedAssignment] = []
        for i, incident in enumerate(ranked):
            try:
                proposals_for_incident = self._propose_for_incident(
                    world, incident, tick, i, claimed, rejections
                )
            except Exception:
                continue
            if proposals_for_incident is not None:
                proposals.append(proposals_for_incident)
        self.last_rejections = rejections
        # Already in incident-rank order (ranked iteration); sort defensively
        # by rank key so the output order never depends on dict ordering.
        try:
            order = {
                incident.incident_id: rank_key(
                    incident.urgency,
                    tick - incident.created_tick,
                    incident.people,
                    incident.incident_id,
                )
                for incident in ranked
            }
            proposals.sort(key=lambda p: (order.get(p.incident_id, (0, p.incident_id)), p.proposal_id))
        except Exception:
            pass
        return proposals

    def _propose_for_incident(
        self,
        world: World,
        incident: Any,
        tick: int,
        rank_index: int,
        claimed: set[str],
        rejections: list[dict],
    ) -> ProposedAssignment | None:
        """Bid, price with opportunity cost, and claim one incident's winner."""
        incident_agent = self.agents.get(incident.incident_id)
        if not isinstance(incident_agent, IncidentAgent):
            return None
        try:
            request = incident_agent.publish_request()
        except Exception:
            return None

        caps = list(incident.required_capabilities or [])
        wants_boat = "boat" in caps or not caps
        wants_ground = "ground" in caps
        multi_stage = "boat" in caps and "ground" in caps

        candidate_ids: list[str] = []
        if wants_boat:
            try:
                candidate_ids.extend(sorted(world.boats))
            except Exception:
                pass
        if wants_ground and not multi_stage:
            try:
                candidate_ids.extend(sorted(world.teams))
            except Exception:
                pass
        # Deterministic: sorted IDs (boats then teams would already be sorted
        # within kind; re-sort globally for a single stable order).
        candidate_ids = sorted(set(candidate_ids))

        feasible: list[tuple[float, str, dict]] = []
        for agent_id in candidate_ids:
            agent = self.agents.get(agent_id)
            if agent is None:
                continue
            kind = getattr(agent, "kind", "")
            if kind == "boat" and not wants_boat:
                continue
            if kind == "team" and not (wants_ground and not multi_stage):
                continue
            if getattr(agent, "status", None) != "AVAILABLE":
                continue
            evaluate = getattr(agent, "evaluate", None)
            if evaluate is None:
                continue
            try:
                bid, reason = evaluate(request, tick)
            except Exception:
                continue
            if bid is None:
                rejections.append(
                    {
                        "incident_id": incident.incident_id,
                        "resource_id": agent_id,
                        "reason": str(reason),
                    }
                )
                continue
            try:
                waiting_ticks = tick - incident.created_tick
                base_cost = score(
                    world,
                    incident.incident_id,
                    str(bid.get("agent_id", agent_id)),
                    {
                        "eta_ticks": bid.get("eta_ticks", 0),
                        "edges": list(bid.get("route_edge_ids", [])),
                    },
                    waiting_ticks,
                    self.weights,
                )
                base_cost = float(base_cost)
            except Exception:
                continue
            feasible.append((base_cost, str(bid.get("agent_id", agent_id)), bid))

        if not feasible:
            return None
        feasible.sort(key=lambda item: (item[0], item[1]))

        # Claim filtering: drop resources taken by higher-rank incidents.
        unclaimed: list[tuple[float, str, dict]] = []
        for base_cost, agent_id, bid in feasible:
            if agent_id in claimed:
                rejections.append(
                    {
                        "incident_id": incident.incident_id,
                        "resource_id": agent_id,
                        "reason": "RESOURCE_CLAIMED:HIGHER_RANK",
                    }
                )
                continue
            unclaimed.append((base_cost, agent_id, bid))
        if not unclaimed:
            return None

        best_base, winner_agent, winner_bid = unclaimed[0]
        if len(unclaimed) > 1:
            second_base = unclaimed[1][0]
            opportunity = float(second_base - best_base)
        else:
            opportunity = 0.0
        final_cost = float(best_base + self.weights.w_o * opportunity)

        # Losers (unclaimed, not the winner) cite the winner's final cost.
        for loser_base, loser_agent, _ in unclaimed[1:]:
            rejections.append(
                {
                    "incident_id": incident.incident_id,
                    "resource_id": loser_agent,
                    "reason": (
                        f"HIGHER_COST: winner {winner_agent} "
                        f"cost {final_cost:.1f} vs {float(loser_base):.1f}"
                    ),
                }
            )

        try:
            shelter_edges = list(winner_bid.get("shelter_route_edge_ids", []) or [])
        except Exception:
            shelter_edges = []
        shelter_eta = 0
        try:
            for eid in shelter_edges:
                edge = world.edges.get(eid)
                if edge is not None:
                    shelter_eta += int(edge.travel_time)
        except Exception:
            shelter_eta = 0

        try:
            resource_kind = str(winner_bid.get("resource_kind", "boat"))
        except Exception:
            resource_kind = "boat"
        if resource_kind not in ("boat", "team"):
            resource_kind = "boat" if winner_agent in world.boats else "team"

        reasons = ["NEGOTIATED"]
        if multi_stage:
            reasons.append("MULTI_STAGE:BOAT_LEG_ONLY")

        try:
            proposal = ProposedAssignment(
                proposal_id=f"PROP-{tick:04d}-{rank_index:03d}",
                incident_id=incident.incident_id,
                resource_id=winner_agent,
                resource_kind=resource_kind,  # type: ignore[arg-type]
                shelter_id=winner_bid.get("shelter_id"),
                seats=int(winner_bid.get("seats", 0)),
                route_edge_ids=list(winner_bid.get("route_edge_ids", []) or []),
                shelter_route_edge_ids=list(shelter_edges),
                eta_ticks=int(winner_bid.get("eta_ticks", 0)),
                shelter_eta_ticks=int(shelter_eta),
                cost=float(final_cost),
                reasons=reasons,
                created_tick=tick,
            )
        except Exception:
            return None
        claimed.add(winner_agent)
        return proposal

    def commit(
        self,
        world: World,
        proposal: ProposedAssignment,
        tick: int,
        *,
        manager: Any,
        assignments: dict,
        proposals_seen: dict,
    ) -> tuple[Assignment | None, str]:
        """Thin wrapper around commitment_manager; engine passes state_manager + registries."""
        _ = world  # mutation flows through manager (StateManager owns the world).
        if proposal.proposal_id.startswith("PROP-"):
            assignment_id = f"ASN-{proposal.proposal_id[5:]}"
        else:
            assignment_id = f"ASN-{proposal.proposal_id}"
        return commit_assignment(
            manager, proposal, tick, assignment_id, assignments, proposals_seen
        )


__all__ = ["NegotiationScheduler", "world_to_belief_snapshot"]
