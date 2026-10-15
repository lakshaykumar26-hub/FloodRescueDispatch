"""Authoritative safety validator (Phase 2 Step 05; spec section 10).

Every dispatch proposal must pass :func:`validate` before commit. Hard
constraint failures are REJECTs with machine-readable codes, never score
penalties (AGENTS.md hard rule 3).

Pure function over :class:`World`; no FastAPI/DB imports.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..routing.route_validator import is_route_valid
from .scheduler_interface import ProposedAssignment

if TYPE_CHECKING:
    from ..simulation.world import World

_ACTIVE_ASSIGNMENT_STATUSES: tuple[str, ...] = (
    "COMMITTED",
    "ACKNOWLEDGED",
    "IN_PROGRESS",
)


def validate(
    world: World,
    proposal: ProposedAssignment,
    tick: int,
    assignments: dict,
) -> tuple[bool, list[str]]:
    """Check ``proposal`` against every safety invariant, in order.

    Collects ALL violations (not first-only) so a single log entry can
    explain everything wrong with a proposal. Returns ``(True, [])`` on
    success, else ``(False, [codes...])``. Never raises on missing
    entities; checks are skipped only when their inputs are absent
    (with ``UNKNOWN_ENTITY`` already recorded).

    Check order and codes:

    1. unknown incident/resource -> ``UNKNOWN_ENTITY``
    2. incident terminal (SERVED/CANCELLED) ->
       ``ASSIGNMENT_INVALID:INCIDENT_<status>``
    3. mode mismatch (boat<->non-water / team<->non-road edges, or
       resource kind incompatible with ``required_capabilities``;
       empty capabilities = no constraint) -> ``MODE_MISMATCH``
    4. route safety, one entry per bad edge via ``is_route_valid``
       (``EDGE_CLOSED:<id>`` / ``UNKNOWN_EDGE:<id>`` / ``ZERO_CAPACITY:<id>``),
       plus one ``EDGE_DISPUTED:<id>`` per disputed edge (conflicting
       reports, Phase 4 Step 04: conservative routing rejects new commits
       over disputed edges; in-flight movement may still traverse them
       with a warning)
    5. resource not AVAILABLE or already owned -> ``RESOURCE_UNAVAILABLE``
    6. conflicting active assignment on the same resource ->
       ``ASSIGNMENT_CONFLICT``
    7. boat seats over capacity -> ``OVER_CAPACITY``
    8. boat fuel below incident-leg eta + reserve -> ``FUEL_INSUFFICIENT``
    9. shelter reservation would overflow ->
       ``SHELTER_FULL`` (``SHELTER_UNKNOWN`` when the shelter is missing)

    ``tick`` is accepted for interface stability (future expiry checks)
    and does not affect the outcome yet.
    """
    _ = tick  # reserved for future expiry/validity checks; intentionally unused.
    violations: list[str] = []

    incident = world.incidents.get(proposal.incident_id)
    boat = world.boats.get(proposal.resource_id)
    team = world.teams.get(proposal.resource_id) if boat is None else None
    if incident is None or (boat is None and team is None):
        violations.append("UNKNOWN_ENTITY")

    is_boat = proposal.resource_kind == "boat"
    resource = boat if is_boat else team
    # Fall back to the proposal's kind when the resource object is missing
    # (UNKNOWN_ENTITY already recorded above).
    mode = "water" if is_boat else "road"

    # 2. Assignment validity: terminal incidents cannot take new missions.
    if incident is not None and incident.status in ("SERVED", "CANCELLED"):
        violations.append(f"ASSIGNMENT_INVALID:INCIDENT_{incident.status}")

    # 3. Transport compatibility: edge modes + capability cross-check.
    for eid in proposal.route_edge_ids:
        edge = world.edges.get(eid)
        if edge is not None and edge.mode != mode:
            violations.append("MODE_MISMATCH")
            break
    if incident is not None:
        caps = incident.required_capabilities or []
        if caps:
            if is_boat and "boat" not in caps:
                violations.append("MODE_MISMATCH")
            if not is_boat and "ground" not in caps:
                violations.append("MODE_MISMATCH")

    # 4. Route safety: one violation per bad edge (mode mismatches already
    # reported above, so only propagate the safety codes here).
    for eid in proposal.route_edge_ids:
        ok, code = is_route_valid(world, [eid], mode)  # type: ignore[arg-type]
        if not ok and code != "MODE_MISMATCH":
            violations.append(code)

    # 4b. Disputed edges (Phase 4 Step 04): conflicting reports with no newer
    # CONFIRMED OPEN reject NEW commits conservatively, collected alongside
    # the other route violations above.
    for eid in proposal.route_edge_ids:
        edge = world.edges.get(eid)
        if edge is not None and edge.status == "disputed":
            violations.append(f"EDGE_DISPUTED:{eid}")

    # 5. Resource availability.
    if resource is not None:
        if resource.status != "AVAILABLE" or resource.assignment_id is not None:
            violations.append("RESOURCE_UNAVAILABLE")
    # 6. Exclusive assignment: no other active assignment may hold it.
    for assignment in assignments.values():
        if (
            assignment.resource_id == proposal.resource_id
            and assignment.proposal_id != proposal.proposal_id
            and assignment.status in _ACTIVE_ASSIGNMENT_STATUSES
        ):
            violations.append("ASSIGNMENT_CONFLICT")
            break

    # 7. Boat capacity.
    if is_boat and boat is not None:
        if (
            proposal.seats > boat.capacity
            or boat.passengers + proposal.seats > boat.capacity
        ):
            violations.append("OVER_CAPACITY")

    # 8. Fuel feasibility (incident leg only).
    if is_boat and boat is not None:
        eta = sum(
            world.edges[eid].travel_time
            for eid in proposal.route_edge_ids
            if eid in world.edges
        )
        if boat.fuel < eta + boat.fuel_reserve:
            violations.append("FUEL_INSUFFICIENT")

    # 9. Shelter capacity (boats only carry shelter legs; teams travel
    # without a shelter reservation).
    if proposal.shelter_id is not None:
        if proposal.shelter_id not in world.shelters:
            violations.append("SHELTER_UNKNOWN")
        else:
            try:
                remaining = world.shelter_remaining(proposal.shelter_id)
            except KeyError:
                remaining = -1
            if remaining < proposal.seats:
                violations.append("SHELTER_FULL")

    return (len(violations) == 0, violations)


__all__ = ["validate"]
