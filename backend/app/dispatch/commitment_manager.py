"""Atomic commitment + explicit assignment lifecycle (Phase 2 Step 04).

Mutation only happens here (via ``StateManager``) after conflict
resolution; schedulers themselves stay pure. Every transition appends
``{tick, from, to, reason, actor}`` to ``Assignment.history`` and mirrors
an audit entry into ``manager.event_log`` via ``manager._log``.
"""

from __future__ import annotations

from typing import Any

from .scheduler_interface import Assignment, ProposedAssignment
from ..simulation.world import Incident

_CANCELABLE = ("COMMITTED", "ACKNOWLEDGED", "IN_PROGRESS")

_TERMINAL_RECONCILE = ("COMPLETED", "CANCELLED", "REJECTED", "EXPIRED")


def check_version(current_version: int, base_version: int) -> tuple[bool, str]:
    """Guard a commit against a stale base version (Step 04).

    Returns ``(True, "OK")`` iff ``base_version == current_version``,
    else ``(False, "REJECTED_STALE")`` (mirrors the mobile
    ``base_assignment_version`` check wired in Phase 7).
    """
    if int(base_version) == int(current_version):
        return True, "OK"
    return False, "REJECTED_STALE"


def flag_reconciliation(
    assignments: dict,
    assignment_id: str,
    tick: int,
    reason: str,
    actor: str = "dispatch",
) -> tuple[bool, str]:
    """Mark an assignment REQUIRES_RECONCILIATION (Step 04, pure registry op).

    Moves from any non-terminal status (not COMPLETED/CANCELLED/REJECTED/
    EXPIRED); already-flagged is idempotent ``(True, "OK:ALREADY")``.
    Appends ``{tick, from, to, reason, actor}`` to history. Stale or
    conflicting state is represented explicitly, never silently erased.

    NOTE: no ``manager`` param here — audit logging is the caller's job
    (the caller owns the StateManager/event log; Step 05 wires it).
    """
    assignment = assignments.get(assignment_id)
    if assignment is None:
        return False, "UNKNOWN_ASSIGNMENT"
    if assignment.status in _TERMINAL_RECONCILE:
        return False, "REJECTED:TERMINAL"
    if assignment.status == "REQUIRES_RECONCILIATION":
        return True, "OK:ALREADY"
    frm = assignment.status
    assignment.status = "REQUIRES_RECONCILIATION"  # type: ignore[assignment]
    assignment.history.append(
        {
            "tick": tick,
            "from": frm,
            "to": "REQUIRES_RECONCILIATION",
            "reason": reason,
            "actor": actor,
        }
    )
    return True, "OK"


def _commit_reason(assignment_id: str, proposal: ProposedAssignment) -> str:
    return f"commit {assignment_id} {proposal.resource_id}->{proposal.incident_id}"


def _new_assignment(
    proposal: ProposedAssignment, tick: int, assignment_id: str
) -> Assignment:
    """Build a fresh ``COMMITTED`` assignment (version 1, one history entry)."""
    reason = _commit_reason(assignment_id, proposal)
    return Assignment(
        assignment_id=assignment_id,
        version=1,
        proposal_id=proposal.proposal_id,
        incident_id=proposal.incident_id,
        resource_id=proposal.resource_id,
        resource_kind=proposal.resource_kind,
        shelter_id=proposal.shelter_id,
        seats=proposal.seats,
        route_edge_ids=list(proposal.route_edge_ids),
        status="COMMITTED",
        cost=proposal.cost,
        created_tick=tick,
        history=[
            {
                "tick": tick,
                "from": "PROPOSED",
                "to": "COMMITTED",
                "reason": reason,
                "actor": "dispatch",
            }
        ],
    )


def _get_resource(manager: Any, proposal: ProposedAssignment) -> Any | None:
    if proposal.resource_kind == "boat":
        return manager.world.boats.get(proposal.resource_id)
    return manager.world.teams.get(proposal.resource_id)


def commit_assignment(
    manager: Any,
    proposal: ProposedAssignment,
    tick: int,
    assignment_id: str,
    assignments: dict,
    proposals_seen: dict,
    actor: str = "dispatch",
) -> tuple[Assignment | None, str]:
    """Commit one resolved proposal atomically (all-or-nothing).

    Idempotent on ``proposal_id``; validates resource availability before
    touching shelter state; rolls back the shelter reservation when the
    resource transition fails.
    """
    if proposal.proposal_id in proposals_seen:
        existing_id = proposals_seen[proposal.proposal_id]
        existing = assignments.get(existing_id)
        if existing is not None:
            return existing, "DUPLICATE:RETURNED_EXISTING"
        del proposals_seen[proposal.proposal_id]
    if assignment_id in assignments:
        return None, "REJECTED:DUPLICATE_ASSIGNMENT_ID"

    resource = _get_resource(manager, proposal)
    if resource is None or resource.status != "AVAILABLE" or resource.assignment_id is not None:
        return None, "RESOURCE_UNAVAILABLE_AT_COMMIT"

    incident = manager.world.incidents.get(proposal.incident_id)
    if incident is None:
        return None, "REJECTED:UNKNOWN_INCIDENT"

    reason = _commit_reason(assignment_id, proposal)

    if proposal.shelter_id:
        ok, _ = manager.reserve_shelter(
            proposal.shelter_id, assignment_id, proposal.seats, tick, actor=actor
        )
        if not ok:
            return None, "SHELTER_FULL_AT_COMMIT"

    if proposal.resource_kind == "boat":
        ok, code = manager.transition_boat(
            proposal.resource_id, "ASSIGNED", reason, tick, actor=actor
        )
    else:
        ok, code = manager.transition_team(
            proposal.resource_id, "ASSIGNED", reason, tick, actor=actor
        )
    if not ok:
        if proposal.shelter_id:
            manager.release_shelter(proposal.shelter_id, assignment_id, tick, actor=actor)
        return None, code

    resource.assignment_id = assignment_id

    frm = incident.status
    incident.status = "ASSIGNED"  # type: ignore[assignment]
    manager._log(
        tick,
        "INCIDENT_STATUS",
        actor,
        {
            "incident_id": proposal.incident_id,
            "from": frm,
            "to": "ASSIGNED",
            "reason": reason,
        },
    )

    assignment = _new_assignment(proposal, tick, assignment_id)
    if assignment.history:
        assignment.history[0]["actor"] = actor
        assignment.history[0]["reason"] = reason
    assignments[assignment_id] = assignment
    proposals_seen[proposal.proposal_id] = assignment_id
    manager._log(
        tick,
        "COMMITTED",
        actor,
        {
            "assignment_id": assignment_id,
            "proposal_id": proposal.proposal_id,
            "incident_id": proposal.incident_id,
            "resource_id": proposal.resource_id,
            "shelter_id": proposal.shelter_id,
            "cost": proposal.cost,
        },
    )
    return assignment, "OK"


def _transition_assignment(
    manager: Any,
    assignments: dict,
    assignment_id: str,
    tick: int,
    actor: str,
    reason: str,
    expected_from: str,
    to: str,
    kind: str,
) -> tuple[bool, str]:
    assignment = assignments.get(assignment_id)
    if assignment is None:
        return False, "REJECTED:UNKNOWN_ASSIGNMENT"
    if assignment.status != expected_from:
        return False, "REJECTED:ILLEGAL_TRANSITION"
    frm = assignment.status
    assignment.status = to  # type: ignore[assignment]
    assignment.history.append(
        {"tick": tick, "from": frm, "to": to, "reason": reason, "actor": actor}
    )
    manager._log(
        tick,
        kind,
        actor,
        {"assignment_id": assignment_id, "from": frm, "to": to, "reason": reason},
    )
    return True, "OK"


def acknowledge(
    manager: Any,
    assignments: dict,
    assignment_id: str,
    tick: int,
    actor: str = "dispatch",
    reason: str = "acknowledged",
) -> tuple[bool, str]:
    """COMMITTED -> ACKNOWLEDGED."""
    return _transition_assignment(
        manager, assignments, assignment_id, tick, actor, reason,
        "COMMITTED", "ACKNOWLEDGED", "ACKNOWLEDGED",
    )


def start_progress(
    manager: Any,
    assignments: dict,
    assignment_id: str,
    tick: int,
    actor: str = "dispatch",
    reason: str = "started",
) -> tuple[bool, str]:
    """ACKNOWLEDGED -> IN_PROGRESS."""
    return _transition_assignment(
        manager, assignments, assignment_id, tick, actor, reason,
        "ACKNOWLEDGED", "IN_PROGRESS", "IN_PROGRESS",
    )


def complete(
    manager: Any,
    assignments: dict,
    assignment_id: str,
    tick: int,
    actor: str = "dispatch",
    reason: str = "completed",
) -> tuple[bool, str]:
    """IN_PROGRESS -> COMPLETED."""
    return _transition_assignment(
        manager, assignments, assignment_id, tick, actor, reason,
        "IN_PROGRESS", "COMPLETED", "COMPLETED",
    )


def _release_resource(manager: Any, assignment: Assignment, tick: int, actor: str, reason: str) -> tuple[bool, str]:
    """Return the assignment's resource to AVAILABLE and clear its owner.

    Tries the direct cancel edge first (``cancel returns resource to
    AVAILABLE``); when the FSM has no direct edge (e.g. RESCUING, where no
    direct edge to AVAILABLE exists by design so a mid-rescue boat cannot
    teleport to AVAILABLE), routes via the neutral hold state (boats
    ``->RETURNING->AVAILABLE``, teams ``->UNAVAILABLE->AVAILABLE``), both
    reachable from every active state.
    """
    if assignment.resource_kind == "boat":
        resource = manager.world.boats.get(assignment.resource_id)
    else:
        resource = manager.world.teams.get(assignment.resource_id)
    if resource is None:
        return True, "OK"
    if resource.status == "AVAILABLE":
        resource.assignment_id = None
        return True, "OK"
    if assignment.resource_kind == "boat":
        ok, code = manager.transition_boat(
            assignment.resource_id, "AVAILABLE", reason, tick, actor=actor
        )
    else:
        ok, code = manager.transition_team(
            assignment.resource_id, "AVAILABLE", reason, tick, actor=actor
        )
    if ok:
        resource.assignment_id = None
        return True, "OK"
    if code != "REJECTED:ILLEGAL_TRANSITION":
        return False, code
    via = "RETURNING" if assignment.resource_kind == "boat" else "UNAVAILABLE"
    if assignment.resource_kind == "boat":
        ok, code = manager.transition_boat(
            assignment.resource_id, via, reason, tick, actor=actor
        )
    else:
        ok, code = manager.transition_team(
            assignment.resource_id, via, reason, tick, actor=actor
        )
    if not ok:
        return False, code
    if assignment.resource_kind == "boat":
        ok, code = manager.transition_boat(
            assignment.resource_id, "AVAILABLE", reason, tick, actor=actor
        )
    else:
        ok, code = manager.transition_team(
            assignment.resource_id, "AVAILABLE", reason, tick, actor=actor
        )
    if not ok:
        return False, code
    resource.assignment_id = None
    return True, "OK"


def cancel(
    manager: Any,
    assignments: dict,
    assignment_id: str,
    tick: int,
    actor: str = "dispatch",
    reason: str = "cancelled",
) -> tuple[bool, str]:
    """Cancel from COMMITTED/ACKNOWLEDGED/IN_PROGRESS.

    Releases the shelter reservation (if any), returns the resource to
    AVAILABLE, clears ``resource.assignment_id``, reopens the incident to
    OPEN (when still ASSIGNED/IN_PROGRESS), and marks CANCELLED.
    """
    assignment = assignments.get(assignment_id)
    if assignment is None:
        return False, "REJECTED:UNKNOWN_ASSIGNMENT"
    if assignment.status not in _CANCELABLE:
        return False, "REJECTED:ILLEGAL_TRANSITION"
    frm = assignment.status

    if assignment.shelter_id:
        manager.release_shelter(assignment.shelter_id, assignment_id, tick, actor=actor)

    ok, code = _release_resource(manager, assignment, tick, actor, reason)
    if not ok:
        return False, code

    incident = manager.world.incidents.get(assignment.incident_id)
    if incident is not None and incident.status in ("ASSIGNED", "IN_PROGRESS"):
        frm_inc = incident.status
        incident.status = "OPEN"  # type: ignore[assignment]
        manager._log(
            tick,
            "INCIDENT_STATUS",
            actor,
            {
                "incident_id": assignment.incident_id,
                "from": frm_inc,
                "to": "OPEN",
                "reason": reason,
            },
        )

    assignment.status = "CANCELLED"  # type: ignore[assignment]
    assignment.history.append(
        {"tick": tick, "from": frm, "to": "CANCELLED", "reason": reason, "actor": actor}
    )
    manager._log(
        tick,
        "CANCELLED",
        actor,
        {"assignment_id": assignment_id, "from": frm, "to": "CANCELLED", "reason": reason},
    )
    return True, "OK"


def trigger_recovery(
    manager: Any,
    assignments: dict,
    proposals_seen: dict,
    boat_id: str,
    tick: int,
    actor: str = "dispatch",
) -> tuple[Incident | None, str]:
    """Fail ``boat_id`` and raise a recovery incident for stranded passengers.

    Calls ``manager.fail_boat`` (which sets ``FAILED``, keeps passengers,
    and logs ``BOAT_FAILED``), cancels the boat's active assignment with
    reason ``"CANCELLED:RESOURCE_FAILED"`` (releasing its shelter hold and
    reopening the original incident), and — when ``passengers > 0`` —
    creates a recovery :class:`Incident` at the failed boat's node
    (``urgency=5``, ``people=passengers``, ``kind="recovery"``,
    ``caused_by=<cancelled assignment_id>``) that flows through the normal
    propose/bid/safety/commit pipeline like any boat incident.

    A ``FAILED`` hull never returns to service implicitly: ``cancel()``'s
    ``_release_resource`` routes ``FAILED->RETURNING->AVAILABLE``, which
    would resurrect the boat, so after the cancel attempt the boat is
    forced back to ``FAILED`` (logged ``BOAT_TRANSITION``) with
    ``assignment_id=None`` and gets no new missions while ``FAILED``.

    Returns ``(incident, "OK")`` on recovery, ``(None,
    "OK:NO_PASSENGERS")`` for an empty failed boat, and ``(None, code)``
    when ``fail_boat`` reports an error (e.g. ``UNKNOWN_BOAT``).

    Step-05 transfer rule (documented here, wired there): the servicing
    boat boards ``min(seats, failed.passengers)`` AT the failed boat's
    node and decrements ``failed.passengers`` by the boarded count — the
    failed boat's people are never marked ``SERVED`` directly and never
    double-counted (each passenger is either still aboard the failed boat
    or aboard exactly one rescuer).
    """
    _ = proposals_seen  # registry passthrough; recovery commits reuse it downstream.
    outcome = manager.fail_boat(boat_id, tick, actor=actor)
    if "error" in outcome:
        return None, str(outcome["error"])
    boat = manager.world.boats.get(boat_id)
    if boat is None:
        return None, "UNKNOWN_BOAT"
    passengers = int(outcome.get("passengers", 0))
    had_assignment = outcome.get("had_assignment")
    if had_assignment is not None:
        cancel(
            manager, assignments, had_assignment, tick,
            actor=actor, reason="CANCELLED:RESOURCE_FAILED",
        )
    # cancel()'s release path would leave the hull AVAILABLE; a failed
    # boat stays FAILED with no owner until RETURNING/MAINTENANCE.
    if boat.status != "FAILED":
        manager.transition_boat(
            boat_id, "FAILED", "CANCELLED:RESOURCE_FAILED:force_failed",
            tick, actor=actor,
        )
    boat.assignment_id = None
    if passengers <= 0:
        return None, "OK:NO_PASSENGERS"
    incident_id = f"REC-{boat_id}-{tick:04d}"
    incident = Incident(
        incident_id=incident_id,
        node_id=boat.node_id,
        urgency=5,
        people=passengers,
        required_capabilities=["boat"],
        created_tick=tick,
        kind="recovery",
        caused_by=had_assignment,
    )
    manager.world.incidents[incident_id] = incident
    manager._log(
        tick,
        "RECOVERY_TRIGGERED",
        actor,
        {"incident_id": incident_id, "node": boat.node_id,
         "people": passengers, "caused_by": had_assignment},
    )
    manager._log(
        tick,
        "INCIDENT_STATUS",
        actor,
        {"incident_id": incident_id, "from": "NONE", "to": "OPEN",
         "reason": "RECOVERY_TRIGGERED"},
    )
    return incident, "OK"


def reassign_shelter(
    manager: Any,
    assignments: dict,
    assignment_id: str,
    new_shelter_id: str,
    new_route_edges: list[str],
    tick: int,
    actor: str = "dispatch",
) -> tuple[bool, str]:
    """Swap one assignment's shelter destination without losing its seats.

    Only assignments in ``COMMITTED``/``ACKNOWLEDGED``/``IN_PROGRESS``
    that still hold a reservation at their current shelter (passengers
    unarrived) may move. The new shelter is reserved FIRST under the same
    ``assignment_id`` with the same seat count; when that fails the old
    hold is untouched and ``(False, "REASSIGN_NO_SEATS")`` is returned
    (the caller emits ``UNRESOLVED:NO_SHELTER`` when no shelter fits —
    this helper never overbooks). On success the old reservation is
    released, ``assignment.shelter_id``/``route_edge_ids`` point at the
    new destination, the resource's route is reset to the new shelter
    node, and both a history entry and a ``SHELTER_REASSIGNED`` audit log
    record ``{old -> new}`` with reason, tick, and actor.
    """
    assignment = assignments.get(assignment_id)
    if assignment is None:
        return False, "REJECTED:UNKNOWN_ASSIGNMENT"
    if assignment.status not in _CANCELABLE:
        return False, "REJECTED:ILLEGAL_TRANSITION"
    old_shelter_id = assignment.shelter_id
    if not old_shelter_id:
        return False, "REJECTED:NO_SHELTER"
    old_shelter = manager.world.shelters.get(old_shelter_id)
    if old_shelter is None:
        return False, "REJECTED:UNKNOWN_SHELTER"
    if assignment_id not in old_shelter.reservations:
        return False, "REJECTED:ALREADY_ARRIVED"
    new_shelter = manager.world.shelters.get(new_shelter_id)
    if new_shelter is None:
        return False, "REJECTED:UNKNOWN_SHELTER"

    ok, _ = manager.reserve_shelter(
        new_shelter_id, assignment_id, assignment.seats, tick, actor=actor
    )
    if not ok:
        return False, "REASSIGN_NO_SEATS"

    manager.release_shelter(old_shelter_id, assignment_id, tick, actor=actor)

    assignment.shelter_id = new_shelter_id
    assignment.route_edge_ids = list(new_route_edges)
    if hasattr(assignment, "shelter_route_edge_ids"):
        assignment.shelter_route_edge_ids = list(new_route_edges)
    manager.set_route(
        assignment.resource_id, list(new_route_edges),
        new_shelter.node_id, tick=tick, actor=actor,
    )

    reason = f"SHELTER_FULL reassigned {old_shelter_id}->{new_shelter_id}"
    assignment.history.append(
        {"tick": tick, "from": old_shelter_id, "to": new_shelter_id,
         "reason": reason, "actor": actor}
    )
    manager._log(
        tick, "SHELTER_REASSIGNED", actor,
        {"assignment_id": assignment_id, "from": old_shelter_id,
         "to": new_shelter_id, "reason": reason},
    )
    return True, "OK"
