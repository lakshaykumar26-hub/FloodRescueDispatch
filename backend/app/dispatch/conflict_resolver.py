"""Deterministic conflict resolution over same-tick proposals.

Pure function: never mutates ``world`` or the input proposals. Two stages:

1. Resource contention: group by ``resource_id``; keep lowest
   ``(cost, proposal_id)``; reject the rest with
   ``RESOURCE_CONFLICT:WINNER=<winning proposal_id>``.
2. Shelter over-subscription: among survivors with a ``shelter_id``,
   group by shelter; order each group by incident rank
   (``rank_key(urgency, tick - created_tick, people, incident_id)`` with
   ``proposal_id`` as final tiebreak) and allocate seats while
   ``world.shelter_remaining(sid) - already_allocated >= proposal.seats``;
   reject the rest with ``SHELTER_CONFLICT``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .scheduler_interface import ProposedAssignment, incident_zone_risk, rank_key

if TYPE_CHECKING:
    from ..simulation.world import World


def _incident_rank(proposal: ProposedAssignment, world: World, tick: int) -> tuple:
    incident = world.incidents.get(proposal.incident_id) if hasattr(world, "incidents") else None
    if incident is not None:
        urgency = incident.urgency
        people = incident.people
        created = incident.created_tick
    else:
        urgency = 0
        people = proposal.seats
        created = proposal.created_tick
    waiting = tick - created
    zone_risk = incident_zone_risk(world, incident) if incident is not None else 0.0
    return rank_key(urgency, waiting, people, proposal.incident_id, zone_risk)


def resolve(
    proposals: list[ProposedAssignment], world: World, tick: int
) -> tuple[list[ProposedAssignment], list[dict]]:
    """Split same-tick ``proposals`` into (winners, rejections).

    Deterministic and order-independent: outputs are sorted by
    ``proposal_id``. No mutation of ``world`` or ``proposals``.
    """
    if not proposals:
        return [], []

    # Stage 1: resource contention.
    by_resource: dict[str, list[ProposedAssignment]] = {}
    for proposal in proposals:
        by_resource.setdefault(proposal.resource_id, []).append(proposal)
    survivors: list[ProposedAssignment] = []
    rejections: list[dict] = []
    for resource_id in sorted(by_resource):
        group = sorted(by_resource[resource_id], key=lambda p: (p.cost, p.proposal_id))
        winner = group[0]
        survivors.append(winner)
        for loser in group[1:]:
            rejections.append(
                {
                    "proposal_id": loser.proposal_id,
                    "incident_id": loser.incident_id,
                    "resource_id": loser.resource_id,
                    "reason": f"RESOURCE_CONFLICT:WINNER={winner.proposal_id}",
                }
            )

    # Stage 2: shelter over-subscription (survivors only).
    by_shelter: dict[str, list[ProposedAssignment]] = {}
    winners: list[ProposedAssignment] = [p for p in survivors if not p.shelter_id]
    for proposal in survivors:
        if proposal.shelter_id:
            by_shelter.setdefault(proposal.shelter_id, []).append(proposal)
    for shelter_id in sorted(by_shelter):
        group = sorted(
            by_shelter[shelter_id],
            key=lambda p: (_incident_rank(p, world, tick), p.proposal_id),
        )
        try:
            remaining = world.shelter_remaining(shelter_id)
        except (KeyError, AttributeError):
            for proposal in group:
                rejections.append(
                    {
                        "proposal_id": proposal.proposal_id,
                        "incident_id": proposal.incident_id,
                        "resource_id": proposal.resource_id,
                        "shelter_id": shelter_id,
                        "reason": "SHELTER_CONFLICT",
                    }
                )
            continue
        allocated = 0
        for proposal in group:
            if remaining - allocated >= proposal.seats:
                winners.append(proposal)
                allocated += proposal.seats
            else:
                rejections.append(
                    {
                        "proposal_id": proposal.proposal_id,
                        "incident_id": proposal.incident_id,
                        "resource_id": proposal.resource_id,
                        "shelter_id": shelter_id,
                        "reason": "SHELTER_CONFLICT",
                    }
                )

    winners = sorted(winners, key=lambda p: p.proposal_id)
    rejections = sorted(rejections, key=lambda r: r["proposal_id"])
    return winners, rejections
