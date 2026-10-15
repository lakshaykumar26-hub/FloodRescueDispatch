"""Feasibility gate + bid scoring for the centralized dispatcher (Phase 2 Step 03).

Hard feasibility (reject with a code) is kept strictly separate from soft
cost (rank). Only bids that pass :func:`check_feasible` may be passed to
:func:`score`; a hard failure is never folded into the cost as a penalty
(spec sections 7.3 and 10).

Cost function: ``C(r,i) = w_t*T + w_r*R + w_f*F + w_o*O`` where ``T`` is
route ETA in ticks, ``R`` is summed edge risk, ``F = -waiting_ticks`` is a
fairness nudge (long-waiting incidents score cheaper), and ``O`` is
opportunity cost (``0.0`` until Phase 3 negotiation; the parameter exists
so the signature stays stable).

Pure functions over :class:`World`; no FastAPI/DB imports.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..routing.route_validator import is_route_valid
from .scheduler_interface import DEFAULT_WEIGHTS, Weights

if TYPE_CHECKING:
    from ..simulation.world import World


def check_feasible(
    world: World,
    incident_id: str,
    resource_id: str,
    shelter_id: str | None,
    route_edge_ids: list[str],
    tick: int,
    seats: int | None = None,
) -> tuple[bool, str]:
    """Return ``(True, "OK")`` or ``(False, CODE)`` for a dispatch bid.

    ``seats`` defaults to ``min(incident.people, boat.capacity)`` for boats
    and ``incident.people`` for ground teams (teams have no capacity field).
    Checks run in order, first failure wins:

    1. unknown incident/resource -> ``UNKNOWN_ENTITY``
    2. resource not AVAILABLE or already assigned -> ``RESOURCE_UNAVAILABLE``
    3. transport-mode / capability mismatch -> ``MODE_MISMATCH``
    4. route invalid -> exact code from ``is_route_valid``
       (e.g. ``EDGE_CLOSED:<id>``, ``UNKNOWN_EDGE:<id>``)
    5. boat fuel ``< eta + reserve`` -> ``FUEL_INSUFFICIENT``
    6. seats over boat capacity -> ``OVER_CAPACITY``
    7. shelter unknown / full -> ``SHELTER_UNKNOWN`` / ``SHELTER_FULL``
       (checked only when ``shelter_id`` is given and the resource is a boat)
    8. incident terminal -> ``ASSIGNMENT_INVALID:INCIDENT_<status>``

    ``tick`` is accepted for interface stability (future expiry checks) and
    does not affect the outcome yet. Never raises on missing entities.
    """
    _ = tick  # reserved for future expiry/validity checks; intentionally unused.
    incident = world.incidents.get(incident_id)
    boat = world.boats.get(resource_id)
    team = world.teams.get(resource_id) if boat is None else None
    if incident is None or (boat is None and team is None):
        return (False, "UNKNOWN_ENTITY")

    is_boat = boat is not None
    resource = boat if is_boat else team
    assert resource is not None  # narrowed by the lookup above
    if seats is None:
        seats = min(incident.people, boat.capacity) if is_boat else incident.people

    if resource.status != "AVAILABLE" or resource.assignment_id is not None:
        return (False, "RESOURCE_UNAVAILABLE")

    mode = "water" if is_boat else "road"
    for eid in route_edge_ids:
        edge = world.edges.get(eid)
        if edge is not None and edge.mode != mode:
            return (False, "MODE_MISMATCH")
    caps = incident.required_capabilities or []
    if caps:
        if is_boat and "boat" not in caps:
            return (False, "MODE_MISMATCH")
        if not is_boat and "ground" not in caps:
            return (False, "MODE_MISMATCH")

    ok, code = is_route_valid(world, route_edge_ids, mode)  # type: ignore[arg-type]
    if not ok:
        return (False, code)

    if is_boat:
        assert boat is not None
        eta = sum(world.edges[eid].travel_time for eid in route_edge_ids)
        if boat.fuel < eta + boat.fuel_reserve:
            return (False, "FUEL_INSUFFICIENT")
        if seats > boat.capacity or boat.passengers + seats > boat.capacity:
            return (False, "OVER_CAPACITY")

    if shelter_id is not None and is_boat:
        if shelter_id not in world.shelters:
            return (False, "SHELTER_UNKNOWN")
        if world.shelter_remaining(shelter_id) < seats:
            return (False, "SHELTER_FULL")

    if incident.status in ("SERVED", "CANCELLED"):
        return (False, f"ASSIGNMENT_INVALID:INCIDENT_{incident.status}")

    return (True, "OK")


def score(
    world: World,
    incident_id: str,
    resource_id: str,
    route: dict,
    waiting_ticks: int,
    weights: Weights | None = None,
    opportunity_cost: float = 0.0,
) -> float:
    """Score an already-feasible bid; lower is better.

    ``T = route["eta_ticks"]``; ``R`` is the summed ``risk_level`` over
    ``route["edges"]`` rounded to 3 decimals (note: this differs from
    ``find_route``'s max-risk summary); ``F = -waiting_ticks`` so
    long-waiting incidents get cheaper bids (fairness nudge);
    ``O = opportunity_cost``, ``0.0`` until Phase 3 (kept as a parameter,
    documented here).

    Callers must run :func:`check_feasible` first and only score bids that
    return ``(True, "OK")``. ``incident_id``/``resource_id`` identify the
    bid for future opportunity-cost accounting and are not re-validated here.
    """
    _ = (incident_id, resource_id)  # bid identity only; validity belongs to check_feasible.
    w = weights if weights is not None else DEFAULT_WEIGHTS
    t = route["eta_ticks"]
    r = round(sum(world.edges[eid].risk_level for eid in route["edges"]), 3)
    f = -waiting_ticks
    o = opportunity_cost
    return w.w_t * t + w.w_r * r + w.w_f * f + w.w_o * o


__all__ = ["check_feasible", "score"]
