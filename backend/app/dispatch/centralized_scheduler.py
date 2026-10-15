"""Centralized greedy scheduler (Phase 2 Step 02; spec section 7.1 steps 1-5).

Pure decision-maker over :class:`World`; no FastAPI/DB imports. ``propose``
ranks OPEN incidents, matches kind-compatible resources, resolves routes
(incident leg + shelter leg for boats), runs the feasibility gate, scores
survivors, and emits at most one proposal per incident. A tentative claim
set inside one ``propose`` call stops two incidents from proposing the same
resource in the same tick (final arbitration lives in Step 04). ``commit``
is a thin wrapper over ``commitment_manager.commit_assignment``.

Determinism: incidents ranked by ``rank_key`` (ascending sort gives rank
order); candidates iterated in ``resource_id`` order; cost ties broken by
lower ``resource_id``; ``proposal_id`` derived from ``(tick, rank index)``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..routing.pathfinder import find_route
from .bid_evaluator import check_feasible, score
from .commitment_manager import commit_assignment
from .route_replanner import shelter_options
from .scheduler_interface import (
    DEFAULT_WEIGHTS,
    Assignment,
    ProposedAssignment,
    Weights,
    incident_zone_risk,
    rank_key,
)

if TYPE_CHECKING:
    from ..simulation.world import EdgeMode, World


class CentralizedScheduler:
    """Greedy centralized dispatch strategy (spec section 7.1 steps 1-5)."""

    strategy: str = "centralized"

    def __init__(self, weights: Weights | None = None) -> None:
        self.weights = weights if weights is not None else DEFAULT_WEIGHTS
        self.last_rejections: list[dict] = []

    def propose(self, world: World, tick: int) -> list[ProposedAssignment]:
        """Rank incidents and return feasible proposals; never mutates the world."""
        rejections: list[dict] = []
        incidents = [
            inc
            for inc in world.incidents.values()
            if inc.status == "OPEN" and inc.created_tick <= tick
        ]
        ranked = sorted(
            incidents,
            key=lambda inc: rank_key(
                inc.urgency,
                tick - inc.created_tick,
                inc.people,
                inc.incident_id,
                incident_zone_risk(world, inc),
            ),
        )
        claimed: set[str] = set()
        proposals: list[ProposedAssignment] = []
        for i, inc in enumerate(ranked):
            caps = inc.required_capabilities or []
            wants_boat = "boat" in caps or not caps
            wants_ground = "ground" in caps
            multi_stage = "boat" in caps and "ground" in caps
            candidates: list[tuple[str, str, Any]] = []
            if wants_boat:
                for rid in sorted(world.boats):
                    candidates.append((rid, "boat", world.boats[rid]))
            if wants_ground and not multi_stage:
                for rid in sorted(world.teams):
                    candidates.append((rid, "team", world.teams[rid]))
            candidates.sort(key=lambda c: c[0])

            best: tuple | None = None
            best_payload: dict | None = None
            for rid, kind, res in candidates:
                if res.status != "AVAILABLE" or res.assignment_id is not None:
                    continue
                if rid in claimed:
                    rejections.append(
                        {
                            "incident_id": inc.incident_id,
                            "resource_id": rid,
                            "reason": "RESOURCE_CLAIMED:HIGHER_RANK",
                        }
                    )
                    continue
                mode: EdgeMode = "water" if kind == "boat" else "road"
                route = find_route(world, res.node_id, inc.node_id, mode)
                if route is None:
                    rejections.append(
                        {
                            "incident_id": inc.incident_id,
                            "resource_id": rid,
                            "reason": "NO_ROUTE",
                        }
                    )
                    continue
                cap = getattr(res, "capacity", None) or inc.people
                seats = min(inc.people, cap)
                shelter_id: str | None = None
                shelter_route: dict = {
                    "nodes": [],
                    "edges": [],
                    "eta_ticks": 0,
                    "risk": 0.0,
                    "warnings": [],
                }
                if kind == "boat":
                    options = shelter_options(world, inc.node_id, "water", seats)
                    if not options:
                        rejections.append(
                            {
                                "incident_id": inc.incident_id,
                                "resource_id": rid,
                                "reason": "NO_SHELTER_ROUTE",
                            }
                        )
                        continue
                    shelter_id, shelter_route = options[0]
                waiting_ticks = tick - inc.created_tick
                ok, code = check_feasible(
                    world, inc.incident_id, rid, shelter_id, route["edges"], tick, seats
                )
                if not ok:
                    rejections.append(
                        {
                            "incident_id": inc.incident_id,
                            "resource_id": rid,
                            "reason": code,
                        }
                    )
                    continue
                cost = score(
                    world, inc.incident_id, rid, route, waiting_ticks, self.weights
                )
                if best is None or cost < best[0] or (cost == best[0] and rid < best[1]):
                    best = (cost, rid)
                    best_payload = {
                        "resource_id": rid,
                        "resource_kind": kind,
                        "route": route,
                        "shelter_id": shelter_id,
                        "shelter_route": shelter_route,
                        "seats": seats,
                    }
            if best is not None and best_payload is not None:
                reasons = [
                    "RANK_SELECTED",
                    f"ZONE_RISK:{incident_zone_risk(world, inc):.2f}",
                ]
                if multi_stage:
                    reasons.append("MULTI_STAGE:BOAT_LEG_ONLY")
                route = best_payload["route"]
                shelter_route = best_payload["shelter_route"]
                proposals.append(
                    ProposedAssignment(
                        proposal_id=f"PROP-{tick:04d}-{i:03d}",
                        incident_id=inc.incident_id,
                        resource_id=best_payload["resource_id"],
                        resource_kind=best_payload["resource_kind"],
                        shelter_id=best_payload["shelter_id"],
                        seats=best_payload["seats"],
                        route_edge_ids=list(route["edges"]),
                        shelter_route_edge_ids=list(shelter_route["edges"]),
                        eta_ticks=route["eta_ticks"],
                        shelter_eta_ticks=shelter_route["eta_ticks"],
                        cost=best[0],
                        reasons=reasons,
                        created_tick=tick,
                    )
                )
                claimed.add(best_payload["resource_id"])
        self.last_rejections = rejections
        return proposals

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


__all__ = ["CentralizedScheduler"]
