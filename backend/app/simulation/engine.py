"""Deterministic headless simulation loop (Phase 2 Step 05).

Must not import FastAPI, DB, or frontend code (AGENTS.md hard rule 1).
No wall-clock time and no unseeded randomness: ordering uses integer
``tick`` only, and every choice is a deterministic function of the world
state (sorted IDs, shortest-time routes, ranked incidents, lowest cost).
"""

from __future__ import annotations

import copy
from typing import Any

from ..dispatch.bid_evaluator import check_feasible
from ..dispatch.centralized_scheduler import CentralizedScheduler
from ..dispatch.commitment_manager import (
    acknowledge,
    cancel,
    commit_assignment,
    complete,
    reassign_shelter,
    start_progress,
    trigger_recovery,
)
from ..dispatch.conflict_resolver import resolve
from ..dispatch.report_store import ReportStore
from ..dispatch.route_replanner import replan, shelter_options
from ..dispatch.safety_validator import validate
from ..dispatch.scheduler_interface import (
    Assignment,
    ProposedAssignment,
    Scheduler,
)
from ..routing.pathfinder import find_route
from .clock import Clock
from .snapshots import restore, take_snapshot
from .state_manager import StateManager
from .world import World

_ACTIVE_INCIDENT_STATUSES = ("OPEN", "ASSIGNED", "IN_PROGRESS")

_ACTIVE_ASSIGNMENT_STATUSES = ("COMMITTED", "ACKNOWLEDGED", "IN_PROGRESS")

# Phase 4 Step 05: validator codes that are EXPECTED for a healthy
# in-flight assignment and must not trigger replanning on their own:
# - RESOURCE_UNAVAILABLE: the resource is legitimately busy with this
#   very assignment (committed resources are never AVAILABLE).
# - OVER_CAPACITY: boarded passengers plus the assignment's own seats
#   double-count seats that are already aboard.
# - FUEL_INSUFFICIENT: fuel burns per hop while the validator prices the
#   full original leg, not the shorter remaining leg.
_INFLIGHT_EXPECTED_CODES = frozenset(
    {"RESOURCE_UNAVAILABLE", "OVER_CAPACITY", "FUEL_INSUFFICIENT"}
)

# Route-safety code prefixes (validate() route checks + replan failures).
_ROUTE_CODE_PREFIXES = (
    "EDGE_CLOSED:",
    "EDGE_DISPUTED:",
    "UNKNOWN_EDGE:",
    "ZERO_CAPACITY:",
    "REPLAN",
)


def _is_route_code(code: str) -> bool:
    """True when ``code`` names a route-safety problem (Step 05 (b))."""
    return code.startswith(_ROUTE_CODE_PREFIXES)


def _assignment_to_proposal(
    assignment: Assignment, route_edge_ids: list[str]
) -> ProposedAssignment:
    """Adapt a live assignment back into a proposal for re-validation.

    Tiny adapter for the Step 05 detect loop: reuses the assignment's own
    ``proposal_id`` (so the validator's conflict check skips itself),
    seats, shelter, and cost, with the caller-supplied live route (the
    remaining untraversed legs for in-flight resources, never the stale
    full legs). ``eta_ticks`` is 0: fuel math on a full original leg is
    meaningless in-flight (see ``_INFLIGHT_EXPECTED_CODES``).
    """
    return ProposedAssignment(
        proposal_id=assignment.proposal_id,
        incident_id=assignment.incident_id,
        resource_id=assignment.resource_id,
        resource_kind=assignment.resource_kind,
        shelter_id=assignment.shelter_id,
        seats=assignment.seats,
        route_edge_ids=list(route_edge_ids),
        eta_ticks=0,
        cost=assignment.cost,
        reasons=["REPLAN_CHECK"],
        created_tick=assignment.created_tick,
    )


class Simulation:
    """Headless time-stepped loop over a :class:`World`.

    Fixed per-tick order (a closure at tick T applies before movement in
    tick T):

    1. ``clock.advance()`` and sync ``world.tick`` to the new tick.
    2. ``pop_due`` scheduler events for the new tick, split by kind:
       ``BOAT_FAILURE`` goes straight to ``trigger_recovery`` (it fails
       the boat, cancels its assignment, and raises a recovery incident;
       it is NOT passed to ``apply_event``, whose ``fail_boat`` branch
       would double-fire); ``REPORT`` claims go to the reports store via
       ``ingest_report``; every other kind goes to ``apply_event``.
       Closures/incident arrivals land before movement.
    3. ``_detect_and_handle``: re-validate every active assignment
       (``COMMITTED``/``ACKNOWLEDGED``/``IN_PROGRESS``) against the live
       world and replan in place (shelter swap / route replan) or cancel
       with a ``pending_replans`` entry for same-tick re-linking.
    4. Progress active services: a resource whose route is exhausted
       (``routes[rid].next_index >= len(edge_ids)``) at its incident node
       boards/rescues (boat: ``board_boat``, incident ``OPEN/ASSIGNED``
       -> ``IN_PROGRESS``, ``RESCUING`` -> ``TRANSPORTING_TO_SHELTER``,
       route to the nearest shelter node with ``shelter_remaining > 0``,
       reserve seats, ``set_route`` to the shelter); a resource arriving
       at its shelter node checks in (incident -> ``SERVED``, boat
       ``RECOVERY`` -> ``AVAILABLE``, team ``RETURNING`` -> ``AVAILABLE``).
       Scene arrival advances the assignment lifecycle (``acknowledge`` +
       ``start_progress``); delivery ``complete``s it. Recovery
       incidents (``kind == "recovery"``) board by TRANSFER from the
       failed hull at their node instead of from ``incident.people``,
       so stranded passengers are never deleted or double-counted.
    5. ``advance_positions(tick)`` moves every routed resource one hop
       (holds + ``ROUTE_BLOCKED`` log when the next edge is closed).
    6. Dispatch (``CentralizedScheduler`` by default): ``propose`` ranks
       ``OPEN`` incidents and emits at most one proposal each (``PROPOSED``
       log per proposal with ``alternatives_considered``; ``REJECTED`` log
       per ``scheduler.last_rejections`` entry); ``resolve`` arbitrates
       same-tick contention (``REJECTED`` per conflict); each winner
       passes the ``check_feasible`` gate and the authoritative
       ``safety_validator.validate`` (``REJECTED`` with the exact code(s)
       on refusal) before ``commit_assignment`` commits it; committed
       winners get ``set_route`` + ``EN_ROUTE_TO_INCIDENT`` (boats) and
       ``_service``/``_incident_owner`` bookkeeping.
    7. ``_link_pending_replans``: incidents cancelled by the detect step
       (or by a boat-failure recovery) that now hold a fresh assignment
       get ``replaces``/``replaced_by`` history links both ways plus a
       ``REPLAN_CHAIN`` audit entry; still-``OPEN`` orphans with no
       route/shelter anywhere log one ``REPLAN_FAILED``; the rest stay
       pending for the next tick's normal propose cycle.
    8. Every ``snapshot_every`` ticks, ``take_snapshot`` into
       ``.snapshots`` keyed by tick, plus routes, pending scheduler
       events, in-flight service state, assignments, proposals_seen, and
       the reports store dump (see ``from_snapshot``).

    All resource transitions go through ``manager.transition_boat`` /
    ``manager.transition_team`` and every incident/shelter/dispatch state
    change is logged with reason + tick + actor, so history/audit is kept.
    """

    def __init__(
        self,
        world: World,
        seed: int = 42,
        snapshot_every: int = 10,
        scheduler: Scheduler | None = None,
    ) -> None:
        self.world = world
        self.seed = seed
        self.snapshot_every = snapshot_every
        self.clock = Clock(start=world.tick)
        self.manager = StateManager(world, seed=seed)
        self.scheduler: Scheduler = (
            scheduler if scheduler is not None else CentralizedScheduler()
        )
        self.snapshots: dict[int, dict] = {}
        self._assignment_seq = 0
        self.assignments: dict[str, Assignment] = {}
        self.proposals_seen: dict[str, str] = {}
        # resource_id -> {incident_id, phase, shelter_id, assignment_id,
        #                 mode, picked_up}
        self._service: dict[str, dict] = {}
        # incident_id -> resource_id (reverse index of _service).
        self._incident_owner: dict[str, str] = {}
        # Step 05 replanning pipeline: incident_id -> {old_asn, reason,
        # tick, seats, resource_kind} for assignments cancelled by
        # _detect_and_handle or by boat-failure recovery, awaiting a
        # replacement commit. Engine-transient only: rebuilt fresh on
        # __init__/from_snapshot (same-tick lifecycle in the common
        # case; a mid-pending resume loses the link — documented in
        # from_snapshot).
        self.pending_replans: dict[str, dict] = {}
        # incident_ids already given one terminal REPLAN_FAILED log.
        self._replan_failed_logged: set[str] = set()

    @property
    def tick(self) -> int:
        """Current simulation tick (mirrors ``clock.tick``/``world.tick``)."""
        return self.clock.tick

    @classmethod
    def from_snapshot(cls, data: dict, snapshot_every: int = 10) -> Simulation:
        """Rebuild a runnable simulation from a :meth:`step` snapshot.

        Restores world, event log, routes, pending scheduler events, and
        the engine's in-flight service bookkeeping, so ``run()`` continues
        exactly as the uninterrupted run would (same tick + seed + state).
        The continued run's own ``.snapshots`` starts empty; equality with
        the uninterrupted run holds over world, event log, and tick.
        Snapshots taken before this format carry no engine state and
        restore as an idle world (routes/services default to empty).
        """
        world, event_log = restore(data)
        simulation = cls(
            world,
            seed=int(data.get("seed", world.seed)),
            snapshot_every=snapshot_every,
        )
        simulation.manager.event_log = event_log
        simulation.manager.routes = copy.deepcopy(data.get("routes", {}))
        for pending_event in data.get("pending_events", []):
            simulation.manager.scheduler.push(
                int(pending_event["tick"]),
                str(pending_event["kind"]),
                dict(pending_event.get("payload", {})),
                str(pending_event["event_id"]),
            )
        simulation._service = copy.deepcopy(data.get("service", {}))
        simulation._incident_owner = copy.deepcopy(
            data.get("incident_owner", {})
        )
        simulation._assignment_seq = int(data.get("assignment_seq", 0))
        simulation.assignments = {
            str(aid): Assignment.model_validate(payload)
            for aid, payload in dict(data.get("assignments", {})).items()
        }
        simulation.proposals_seen = copy.deepcopy(data.get("proposals_seen", {}))
        simulation.manager.reports = ReportStore.from_dict(
            dict(data.get("reports", {"threshold": 0.5, "claims": []}))
        )
        return simulation

    # -- helpers ------------------------------------------------------
    def _next_assignment_id(self) -> str:
        self._assignment_seq += 1
        return f"ASN-{self._assignment_seq:05d}"

    def _set_incident(
        self, incident_id: str, to: str, reason: str, tick: int
    ) -> None:
        incident = self.world.incidents[incident_id]
        frm = incident.status
        incident.status = to  # type: ignore[assignment]
        self.manager._log(
            tick,
            "INCIDENT_STATUS",
            "engine",
            {
                "incident_id": incident_id,
                "from": frm,
                "to": to,
                "reason": reason,
            },
        )

    def _has_active_incidents(self) -> bool:
        return any(
            incident.status in _ACTIVE_INCIDENT_STATUSES
            for incident in self.world.incidents.values()
        )

    # -- main loop ----------------------------------------------------
    def step(self) -> int:
        """Advance exactly one tick in the fixed order from the docstring."""
        tick = self.clock.advance()
        self.world.tick = tick
        due = self.manager.scheduler.pop_due(tick)
        for event in due:
            kind = event.get("kind")
            if kind == "BOAT_FAILURE":
                # Recovery owns the failure: fail the boat, cancel its
                # assignment, raise the recovery incident. Never pass
                # these to apply_event (its fail_boat branch would fire
                # the BOAT_FAILED transition/logs a second time).
                self._handle_boat_failure_event(tick, event)
            elif kind == "REPORT":
                self._handle_report_event(tick, event)
            else:
                self.manager.apply_event(event, actor="scheduler")
        self._detect_and_handle(tick)
        self._progress_services(tick)
        self.manager.advance_positions(tick, actor="engine")
        self._dispatch(tick)
        self._link_pending_replans(tick)
        if self.snapshot_every > 0 and tick % self.snapshot_every == 0:
            snapshot = take_snapshot(
                self.world, self.manager.event_log, self.seed
            )
            # Engine-level state required by from_snapshot() so a restore
            # continues exactly like the uninterrupted run.
            snapshot["routes"] = copy.deepcopy(self.manager.routes)
            snapshot["pending_events"] = self.manager.scheduler.pending()
            snapshot["service"] = copy.deepcopy(self._service)
            snapshot["incident_owner"] = copy.deepcopy(self._incident_owner)
            snapshot["assignment_seq"] = self._assignment_seq
            snapshot["assignments"] = {
                aid: assignment.model_dump()
                for aid, assignment in self.assignments.items()
            }
            snapshot["proposals_seen"] = copy.deepcopy(self.proposals_seen)
            snapshot["reports"] = self.manager.reports.to_dict()
            self.snapshots[tick] = snapshot
        return tick

    def run(self, max_ticks: int) -> int:
        """Step until ``max_ticks`` or no ``OPEN/ASSIGNED/IN_PROGRESS``
        incidents remain (and no scheduler events are still pending)."""
        while self.tick < max_ticks:
            if not self._has_active_incidents() and len(self.manager.scheduler) == 0:
                break
            self.step()
        return self.tick

    # -- scheduler-event branches (Step 05) --------------------------------
    def _handle_boat_failure_event(self, tick: int, event: dict) -> None:
        """Route a due ``BOAT_FAILURE`` event through recovery.

        Calls ``trigger_recovery`` (fail + cancel + recovery incident),
        drops the failed boat's engine-side mission state so it never
        drifts on a stale route, and records a ``pending_replans`` entry
        for the cancelled assignment's incident so its replacement
        commit links back with a ``REPLAN_CHAIN`` (same rule as the
        detect-step cancels). Malformed payloads log ``IGNORED``.
        """
        payload = event.get("payload", {})
        if not isinstance(payload, dict):
            payload = {}
        boat_id = payload.get("boat_id")
        if not isinstance(boat_id, str):
            self.manager._log(
                tick, "IGNORED", "scheduler",
                {
                    "reason": "boat_failure_missing_boat_id",
                    "event_id": event.get("event_id", ""),
                },
            )
            return
        boat = self.world.boats.get(boat_id)
        old_aid = boat.assignment_id if boat is not None else None
        old = self.assignments.get(old_aid) if isinstance(old_aid, str) else None
        trigger_recovery(
            self.manager, self.assignments, self.proposals_seen, boat_id, tick
        )
        self._drop_resource_mission(boat_id)
        if old is not None and old.status == "CANCELLED":
            self.pending_replans[old.incident_id] = {
                "old_asn": old.assignment_id,
                "reason": "CANCELLED:RESOURCE_FAILED",
                "tick": tick,
                "seats": old.seats,
                "resource_kind": old.resource_kind,
            }

    def _handle_report_event(self, tick: int, event: dict) -> None:
        """File a due ``REPORT`` event's claim in the reports store.

        The claim rides either nested (``payload.claim``) or flat (the
        payload itself is the claim). Malformed claims log ``IGNORED``
        and never raise.
        """
        payload = event.get("payload", {})
        if not isinstance(payload, dict):
            payload = {}
        nested = payload.get("claim")
        claim = nested if isinstance(nested, dict) else payload
        try:
            self.manager.reports.ingest_report(
                self.manager, claim, tick, actor="scheduler"
            )
        except Exception as exc:
            self.manager._log(
                tick, "IGNORED", "scheduler",
                {
                    "reason": f"report_bad_claim:{exc}",
                    "event_id": event.get("event_id", ""),
                },
            )

    def _drop_resource_mission(self, resource_id: str) -> None:
        """Forget engine-side mission state for ``resource_id``.

        Pops ``_service``/``_incident_owner`` entries and the manager
        route, so a cancelled or failed resource never drifts on a stale
        route via ``advance_positions``. The assignment registry itself
        (``CANCELLED`` history) is untouched.
        """
        service = self._service.get(resource_id)
        if service is not None:
            incident_id = service.get("incident_id")
            self._service.pop(resource_id, None)
            if (
                incident_id is not None
                and self._incident_owner.get(incident_id) == resource_id
            ):
                del self._incident_owner[incident_id]
        self.manager.routes.pop(resource_id, None)

    # -- replanning pipeline (Step 05) -------------------------------------
    def _live_route_for(self, assignment: Assignment) -> list[str]:
        """Remaining untraversed legs for an active assignment's resource.

        Uses the manager route's ``edge_ids[next_index:]`` when the
        engine holds matching service state (so an already-crossed edge
        whose closure lands later never flags); falls back to the
        assignment's recorded legs for legacy/restored entries without
        service state.
        """
        service = self._service.get(assignment.resource_id)
        if (
            service is not None
            and service.get("assignment_id") == assignment.assignment_id
        ):
            route = self.manager.routes.get(assignment.resource_id)
            if route is not None:
                edge_ids = route.get("edge_ids", [])
                return list(edge_ids[route.get("next_index", 0):])
        return list(assignment.route_edge_ids)

    def _detect_and_handle(self, tick: int) -> None:
        """Re-validate active assignments; replan in place or cancel.

        Collects every ``COMMITTED``/``ACKNOWLEDGED``/``IN_PROGRESS``
        assignment whose adapted proposal fails ``validate`` (minus
        in-flight-expected codes, with the assignment's own shelter hold
        credited back while its shelter still accepts), then handles
        each in deterministic ``assignment_id`` order via
        :meth:`_handle_invalid`.
        """
        invalid: list[tuple[str, Assignment, list[str]]] = []
        for aid in sorted(self.assignments):
            assignment = self.assignments[aid]
            if assignment.status not in _ACTIVE_ASSIGNMENT_STATUSES:
                continue
            proposal = _assignment_to_proposal(
                assignment, self._live_route_for(assignment)
            )
            _, violations = validate(
                self.world, proposal, tick, self.assignments
            )
            codes = [
                code for code in violations
                if code not in _INFLIGHT_EXPECTED_CODES
            ]
            # The holder's own seats are not someone else's shortfall:
            # while the shelter still accepts, credit the live hold back
            # so a half-full shelter never flags its own reservation.
            # (A shelter that stopped accepting always flags: delivery
            # must move elsewhere — see _handle_invalid (a).)
            if "SHELTER_FULL" in codes and assignment.shelter_id is not None:
                shelter = self.world.shelters.get(assignment.shelter_id)
                if shelter is not None and shelter.accepting:
                    own = shelter.reservations.get(aid, 0)
                    remaining = self.world.shelter_remaining(
                        assignment.shelter_id
                    )
                    if remaining + own >= assignment.seats:
                        codes = [
                            code for code in codes if code != "SHELTER_FULL"
                        ]
            if codes:
                invalid.append((aid, assignment, codes))
        for aid, assignment, codes in invalid:
            self._handle_invalid(tick, aid, assignment, codes)

    def _handle_invalid(
        self, tick: int, aid: str, assignment: Assignment, codes: list[str]
    ) -> None:
        """Handle one invalid assignment.

        (a) Pure ``SHELTER_FULL`` with passengers unarrived: swap the
        destination via :meth:`_try_shelter_swap`; swap exhaustion falls
        through to (c). (b) Pure route codes: replan the live leg via
        :meth:`_try_reroute` (assignment persists, NO cancel); when no
        alternate exists the assignment SUSPENDS — route and commitment
        are kept, ``advance_positions`` holds with ``ROUTE_BLOCKED``,
        and the replan is retried the next ticks (a later ``EDGE_REOPEN``
        resumes it). Anything else falls through to (c) cancel with
        reason ``CANCELLED:<first code>`` (commitment cancel frees the
        resource and reopens the incident) plus a ``pending_replans``
        entry so the replacement commit links back; ``CANCELLED`` stands
        as the chain start.
        """
        if set(codes) <= {"SHELTER_FULL"} and self._passengers_unarrived(
            assignment
        ):
            if self._try_shelter_swap(tick, assignment):
                return
        elif all(_is_route_code(code) for code in codes):
            if self._try_reroute(tick, assignment, codes):
                return
            # No alternate: suspend (hold + retry), never strand by
            # cancelling a mission that may resume on reopen.
            return
        reason = f"CANCELLED:{codes[0]}"
        ok, _ = cancel(
            self.manager, self.assignments, aid, tick,
            actor="engine", reason=reason,
        )
        if not ok:
            self.manager._log(
                tick, "IGNORED", "engine",
                {"assignment_id": aid, "reason": f"cancel_failed:{reason}"},
            )
            return
        self._drop_resource_mission(assignment.resource_id)
        self.pending_replans[assignment.incident_id] = {
            "old_asn": aid,
            "reason": reason,
            "tick": tick,
            "seats": assignment.seats,
            "resource_kind": assignment.resource_kind,
        }

    def _passengers_unarrived(self, assignment: Assignment) -> bool:
        """True while the assignment's people still need a destination.

        ``to_incident`` service (or unknown service state) is always
        unarrived; ``to_shelter`` counts only while the shelter still
        holds this assignment's seats (checked-in arrivals are done and
        must not move).
        """
        service = self._service.get(assignment.resource_id)
        if service is None or service.get("phase") != "to_shelter":
            return True
        if assignment.shelter_id is None:
            return False
        shelter = self.world.shelters.get(assignment.shelter_id)
        if shelter is None:
            return False
        return assignment.assignment_id in shelter.reservations

    def _try_shelter_swap(self, tick: int, assignment: Assignment) -> bool:
        """Move one assignment's destination off a full shelter.

        Best-ranked ``shelter_options`` alternative at the incident node
        (excluding the current shelter), reserved FIRST under the same
        assignment/seats so a failed swap never loses the old hold.
        ``to_shelter`` resources get a movement-correct route replanned
        from their actual position; ``to_incident`` resources keep their
        live incident-leg route (the shelter leg is routed at pickup).
        Success logs ``REPLAN`` (the helper already logged
        ``SHELTER_REASSIGNED``); exhaustion falls through to cancel.
        """
        aid = assignment.assignment_id
        incident = self.world.incidents.get(assignment.incident_id)
        if incident is None or not assignment.shelter_id:
            return False
        mode = "water" if assignment.resource_kind == "boat" else "road"
        options = shelter_options(
            self.world, incident.node_id, mode, assignment.seats
        )
        alternates = [
            (sid, route) for sid, route in options
            if sid != assignment.shelter_id
        ]
        if not alternates:
            return False
        service = self._service.get(assignment.resource_id)
        phase = service.get("phase", "to_incident") if service else "to_incident"
        resource = (
            self.world.boats.get(assignment.resource_id)
            if assignment.resource_kind == "boat"
            else self.world.teams.get(assignment.resource_id)
        )
        if resource is None:
            return False
        old_shelter = assignment.shelter_id
        if phase == "to_shelter":
            for new_shelter, _ in alternates:
                dest_node = self.world.shelters[new_shelter].node_id
                movement, code = replan(
                    self.world, resource.node_id, dest_node, mode
                )
                if code != "OK" or movement is None:
                    continue
                ok, _ = reassign_shelter(
                    self.manager, self.assignments, aid, new_shelter,
                    list(movement["edges"]), tick, actor="engine",
                )
                if ok:
                    self._sync_service_shelter(assignment, new_shelter)
                    self.manager._log(
                        tick, "REPLAN", "engine",
                        {
                            "assignment_id": aid,
                            "incident_id": assignment.incident_id,
                            "old_shelter": old_shelter,
                            "new_shelter": new_shelter,
                            "reason": f"SHELTER_FULL reassigned "
                            f"{old_shelter}->{new_shelter}",
                        },
                    )
                    return True
            return False
        # to_incident: swap the held seats but keep heading to the scene.
        saved_route = copy.deepcopy(
            self.manager.routes.get(assignment.resource_id)
        )
        for new_shelter, shelter_route in alternates:
            ok, _ = reassign_shelter(
                self.manager, self.assignments, aid, new_shelter,
                list(shelter_route["edges"]), tick, actor="engine",
            )
            if not ok:
                continue
            if saved_route is not None:
                self.manager.routes[assignment.resource_id] = saved_route
            else:
                self.manager.routes.pop(assignment.resource_id, None)
            self._sync_service_shelter(assignment, new_shelter)
            self.manager._log(
                tick, "REPLAN", "engine",
                {
                    "assignment_id": aid,
                    "incident_id": assignment.incident_id,
                    "old_shelter": old_shelter,
                    "new_shelter": new_shelter,
                    "reason": f"SHELTER_FULL reassigned "
                    f"{old_shelter}->{new_shelter}",
                },
            )
            return True
        return False

    def _sync_service_shelter(
        self, assignment: Assignment, new_shelter_id: str
    ) -> None:
        """Point engine service state at a swapped shelter destination.

        ``reassign_shelter`` (dispatch level) moves the seat hold and the
        manager route, but the engine's ``_service`` entry still names the
        old shelter node — without this sync ``_progress_services``
        would wait for arrival at the wrong node forever. No-op when no
        matching service entry exists.
        """
        service = self._service.get(assignment.resource_id)
        if service is not None and (
            service.get("assignment_id") == assignment.assignment_id
        ):
            shelter = self.world.shelters.get(new_shelter_id)
            if shelter is not None:
                service["shelter_id"] = shelter.node_id
                service["shelter_ref"] = new_shelter_id

    def _try_reroute(
        self, tick: int, assignment: Assignment, codes: list[str]
    ) -> bool:
        """Replan one assignment's live leg around closed/disputed edges.

        Destination is the incident node pre-pickup (``to_incident``) or
        the shelter node once transporting. The assignment persists (NO
        cancel): its legs, the manager route, a history entry, and a
        ``REPLAN`` audit entry all move to the new path.
        """
        service = self._service.get(assignment.resource_id)
        phase = service.get("phase", "to_incident") if service else "to_incident"
        mode = "water" if assignment.resource_kind == "boat" else "road"
        resource = (
            self.world.boats.get(assignment.resource_id)
            if assignment.resource_kind == "boat"
            else self.world.teams.get(assignment.resource_id)
        )
        incident = self.world.incidents.get(assignment.incident_id)
        if resource is None or incident is None:
            return False
        if phase == "to_shelter":
            dest_node = service.get("shelter_id") if service else None
            if not isinstance(dest_node, str):
                shelter = self.world.shelters.get(assignment.shelter_id or "")
                if shelter is None:
                    return False
                dest_node = shelter.node_id
        else:
            dest_node = incident.node_id
        route, code = replan(self.world, resource.node_id, dest_node, mode)
        if code != "OK" or route is None:
            return False
        old_edges = list(assignment.route_edge_ids)
        new_edges = list(route["edges"])
        assignment.route_edge_ids = new_edges
        self.manager.set_route(
            assignment.resource_id, new_edges, dest_node,
            tick=tick, actor="engine",
        )
        reason = f"REPLAN:{';'.join(codes)}"
        assignment.history.append(
            {
                "tick": tick,
                "from": old_edges,
                "to": new_edges,
                "reason": reason,
                "actor": "engine",
            }
        )
        self.manager._log(
            tick, "REPLAN", "engine",
            {
                "assignment_id": assignment.assignment_id,
                "incident_id": assignment.incident_id,
                "resource_id": assignment.resource_id,
                "old_route": old_edges,
                "new_route": new_edges,
                "reason": reason,
            },
        )
        return True

    def _link_pending_replans(self, tick: int) -> None:
        """Resolve ``pending_replans`` after dispatch each tick.

        A fresh active assignment (different id) for the orphan incident
        links both histories (``replaces``/``replaced_by``) plus a
        ``REPLAN_CHAIN`` audit entry. A still-``OPEN`` orphan that no
        compatible resource can reach (or with no shelter holding its
        seats) logs one terminal ``REPLAN_FAILED``. Anything else stays
        pending for the next tick's normal propose cycle.
        """
        for incident_id in sorted(list(self.pending_replans)):
            entry = self.pending_replans[incident_id]
            old_asn = entry["old_asn"]
            reason = entry["reason"]
            new_asn: str | None = None
            for aid in sorted(self.assignments):
                candidate = self.assignments[aid]
                if (
                    aid != old_asn
                    and candidate.incident_id == incident_id
                    and candidate.status in _ACTIVE_ASSIGNMENT_STATUSES
                ):
                    new_asn = aid
                    break
            if new_asn is not None:
                self.assignments[new_asn].history.append(
                    {
                        "tick": tick,
                        "replaces": old_asn,
                        "reason": reason,
                        "actor": "dispatch",
                    }
                )
                old = self.assignments.get(old_asn)
                if old is not None:
                    old.history.append(
                        {
                            "tick": tick,
                            "replaced_by": new_asn,
                            "reason": reason,
                            "actor": "dispatch",
                        }
                    )
                self.manager._log(
                    tick, "REPLAN_CHAIN", "dispatch",
                    {
                        "old_assignment_id": old_asn,
                        "new_assignment_id": new_asn,
                        "incident_id": incident_id,
                        "reason": reason,
                    },
                )
                del self.pending_replans[incident_id]
                continue
            incident = self.world.incidents.get(incident_id)
            if incident is None or incident.status != "OPEN":
                del self.pending_replans[incident_id]
                continue
            terminal, terminal_reason = self._terminally_unservable(
                incident, entry
            )
            if terminal:
                if incident_id not in self._replan_failed_logged:
                    self._replan_failed_logged.add(incident_id)
                    self.manager._log(
                        tick, "REPLAN_FAILED", "dispatch",
                        {
                            "incident_id": incident_id,
                            "old_assignment_id": old_asn,
                            "reason": terminal_reason,
                        },
                    )
                del self.pending_replans[incident_id]
            # else: leave for next tick (busy resources free up via the
            # normal propose cycle).

    def _terminally_unservable(
        self, incident: Any, entry: dict
    ) -> tuple[bool, str]:
        """True when no compatible resource can ever reach ``incident``.

        Scans EVERY kind-compatible resource including busy ones (only
        ``FAILED`` hulls are excluded — they never return implicitly)
        for any ``find_route``; then requires a shelter holding the
        pending seats reachable from the incident node (boat missions
        only). Deterministic, read-only.
        """
        caps = incident.required_capabilities or []
        wants_boat = "boat" in caps or not caps
        wants_ground = "ground" in caps
        reachable = False
        if wants_boat:
            for boat_id in sorted(self.world.boats):
                boat = self.world.boats[boat_id]
                if boat.status == "FAILED":
                    continue
                if (
                    find_route(
                        self.world, boat.node_id, incident.node_id, "water"
                    )
                    is not None
                ):
                    reachable = True
                    break
        if not reachable and wants_ground:
            for team_id in sorted(self.world.teams):
                team = self.world.teams[team_id]
                if (
                    find_route(
                        self.world, team.node_id, incident.node_id, "road"
                    )
                    is not None
                ):
                    reachable = True
                    break
        if not reachable:
            return True, "NO_ROUTE"
        if entry.get("resource_kind", "boat") == "boat":
            seats = int(entry.get("seats") or incident.people)
            if not shelter_options(self.world, incident.node_id, "water", seats):
                return True, "NO_SHELTER"
        return False, ""

    # -- dispatch ------------------------------------------------------
    def _dispatch(self, tick: int) -> None:
        """Run one propose -> resolve -> gate -> validate -> commit cycle.

        Every proposal is logged ``PROPOSED`` (with
        ``alternatives_considered`` = rejected candidates for the same
        incident); every refusal — scheduler-level, conflict-level,
        feasibility-gate, safety-validator, or commit-level — is logged
        ``REJECTED`` with a machine-readable reason. Committed winners
        get movement setup (route + ``EN_ROUTE_TO_INCIDENT`` for boats).
        """
        proposals = self.scheduler.propose(self.world, tick)
        scheduler_rejections: list[dict] = list(
            getattr(self.scheduler, "last_rejections", [])
        )
        for proposal in proposals:
            alternatives = sum(
                1
                for entry in scheduler_rejections
                if entry.get("incident_id") == proposal.incident_id
            )
            self.manager._log(
                tick,
                "PROPOSED",
                "dispatch",
                {
                    "proposal_id": proposal.proposal_id,
                    "incident_id": proposal.incident_id,
                    "resource_id": proposal.resource_id,
                    "cost": proposal.cost,
                    "eta_ticks": proposal.eta_ticks,
                    "alternatives_considered": alternatives,
                    "reasons": list(proposal.reasons),
                },
            )
        for entry in scheduler_rejections:
            self.manager._log(
                tick,
                "REJECTED",
                "dispatch",
                {
                    "incident_id": entry.get("incident_id"),
                    "resource_id": entry.get("resource_id"),
                    "reason": entry.get("reason", ""),
                },
            )
        winners, conflicts = resolve(proposals, self.world, tick)
        for conflict in conflicts:
            self.manager._log(
                tick,
                "REJECTED",
                "dispatch",
                {
                    "proposal_id": conflict.get("proposal_id"),
                    "incident_id": conflict.get("incident_id"),
                    "resource_id": conflict.get("resource_id"),
                    "reason": conflict.get("reason", ""),
                },
            )
        for winner in winners:
            ok, code = check_feasible(
                self.world,
                winner.incident_id,
                winner.resource_id,
                winner.shelter_id,
                list(winner.route_edge_ids),
                tick,
                winner.seats,
            )
            if not ok:
                self.manager._log(
                    tick,
                    "REJECTED",
                    "dispatch",
                    {
                        "proposal_id": winner.proposal_id,
                        "incident_id": winner.incident_id,
                        "resource_id": winner.resource_id,
                        "reason": code,
                    },
                )
                continue
            passed, violations = validate(
                self.world, winner, tick, self.assignments
            )
            if not passed:
                self.manager._log(
                    tick,
                    "REJECTED",
                    "dispatch",
                    {
                        "proposal_id": winner.proposal_id,
                        "incident_id": winner.incident_id,
                        "resource_id": winner.resource_id,
                        "reason": ";".join(violations),
                    },
                )
                continue
            assignment, commit_code = commit_assignment(
                self.manager,
                winner,
                tick,
                self._next_assignment_id(),
                self.assignments,
                self.proposals_seen,
            )
            if assignment is None:
                self.manager._log(
                    tick,
                    "REJECTED",
                    "dispatch",
                    {
                        "proposal_id": winner.proposal_id,
                        "incident_id": winner.incident_id,
                        "resource_id": winner.resource_id,
                        "reason": commit_code,
                    },
                )
                continue
            # commit_assignment already emitted the COMMITTED audit entry;
            # only movement setup remains.
            self._setup_movement(tick, winner, assignment)

    def _setup_movement(
        self, tick: int, proposal: ProposedAssignment, assignment: Assignment
    ) -> None:
        """Route a freshly committed winner toward its incident."""
        incident = self.world.incidents[proposal.incident_id]
        reason = (
            f"dispatch {assignment.assignment_id} "
            f"{proposal.resource_id}->{proposal.incident_id} en route"
        )
        self.manager.set_route(
            proposal.resource_id,
            list(proposal.route_edge_ids),
            incident.node_id,
            tick=tick,
            actor="engine",
        )
        if proposal.resource_kind == "boat":
            self.manager.transition_boat(
                proposal.resource_id,
                "EN_ROUTE_TO_INCIDENT",
                reason,
                tick,
                actor="engine",
            )
        mode = "water" if proposal.resource_kind == "boat" else "road"
        self._service[proposal.resource_id] = {
            "incident_id": proposal.incident_id,
            "phase": "to_incident",
            "shelter_id": None,
            "assignment_id": assignment.assignment_id,
            "mode": mode,
            "picked_up": False,
        }
        self._incident_owner[proposal.incident_id] = proposal.resource_id

    # -- assignment lifecycle helpers ----------------------------------
    def _assignment_started(
        self, service: dict, resource_id: str, tick: int, reason: str
    ) -> None:
        """Advance the service's assignment COMMITTED -> ACKNOWLEDGED -> IN_PROGRESS.

        Tolerates restored/legacy service entries with no known
        assignment: logs ``LIFECYCLE_SKIP`` and never raises, so restore
        paths keep working. Already-advanced assignments are left
        untouched (no log spam on repeat ticks).
        """
        aid = service.get("assignment_id")
        assignment = self.assignments.get(aid) if isinstance(aid, str) else None
        if assignment is None:
            self.manager._log(
                tick,
                "LIFECYCLE_SKIP",
                "engine",
                {
                    "assignment_id": aid,
                    "resource_id": resource_id,
                    "reason": "unknown_assignment",
                },
            )
            return
        if assignment.status == "COMMITTED":
            ok, code = acknowledge(
                self.manager, self.assignments, aid, tick,
                actor="engine", reason=reason,
            )
            if not ok:
                self.manager._log(
                    tick, "LIFECYCLE_SKIP", "engine",
                    {
                        "assignment_id": aid,
                        "resource_id": resource_id,
                        "reason": code,
                    },
                )
                return
        if assignment.status == "ACKNOWLEDGED":
            ok, code = start_progress(
                self.manager, self.assignments, aid, tick,
                actor="engine", reason=reason,
            )
            if not ok:
                self.manager._log(
                    tick, "LIFECYCLE_SKIP", "engine",
                    {
                        "assignment_id": aid,
                        "resource_id": resource_id,
                        "reason": code,
                    },
                )

    def _assignment_completed(
        self, service: dict, resource_id: str, tick: int, reason: str
    ) -> None:
        """Advance the service's assignment IN_PROGRESS -> COMPLETED.

        Same missing/legacy tolerance as :meth:`_assignment_started`.
        """
        aid = service.get("assignment_id")
        assignment = self.assignments.get(aid) if isinstance(aid, str) else None
        if assignment is None:
            self.manager._log(
                tick,
                "LIFECYCLE_SKIP",
                "engine",
                {
                    "assignment_id": aid,
                    "resource_id": resource_id,
                    "reason": "unknown_assignment",
                },
            )
            return
        if assignment.status == "COMPLETED":
            return
        if assignment.status != "IN_PROGRESS":
            self.manager._log(
                tick,
                "LIFECYCLE_SKIP",
                "engine",
                {
                    "assignment_id": aid,
                    "resource_id": resource_id,
                    "reason": f"REJECTED:ILLEGAL_TRANSITION:{assignment.status}->COMPLETED",
                },
            )
            return
        ok, code = complete(
            self.manager, self.assignments, aid, tick,
            actor="engine", reason=reason,
        )
        if not ok:
            self.manager._log(
                tick, "LIFECYCLE_SKIP", "engine",
                {
                    "assignment_id": aid,
                    "resource_id": resource_id,
                    "reason": code,
                },
            )

    # -- service progression -------------------------------------------
    def _progress_services(self, tick: int) -> None:
        for resource_id in sorted(self._service):
            service = self._service[resource_id]
            route = self.manager.routes.get(resource_id)
            if route is None:
                continue
            if route.get("next_index", 0) < len(route.get("edge_ids", [])):
                continue
            incident = self.world.incidents.get(service["incident_id"])
            if incident is None:
                continue
            is_boat = resource_id in self.world.boats
            resource = (
                self.world.boats.get(resource_id)
                if is_boat
                else self.world.teams.get(resource_id)
            )
            if resource is None:
                continue
            if service["phase"] == "to_incident":
                if resource.node_id != incident.node_id:
                    continue
                if is_boat:
                    self._boat_pickup(tick, resource_id, service, service["incident_id"])
                else:
                    self._team_service(tick, resource_id, service, service["incident_id"])
            elif service["phase"] == "to_shelter":
                if resource.node_id != service["shelter_id"]:
                    continue
                if is_boat:
                    self._boat_dropoff(tick, resource_id, service)
                # Ground teams never enter the to_shelter phase.

    def _boat_pickup(
        self, tick: int, boat_id: str, service: dict, incident_id: str
    ) -> None:
        boat = self.world.boats[boat_id]
        incident = self.world.incidents[incident_id]
        if boat.status not in ("EN_ROUTE_TO_INCIDENT", "RESCUING"):
            return
        if not service["picked_up"] and incident.kind == "recovery":
            # Step 05 transfer rule (from Step 02): recovery people ARE
            # the failed hull's stranded passengers — board from the
            # hull, never from incident.people (which would conjure
            # phantom passengers and double-count). The hull's count
            # drops by exactly what the rescuer boards.
            if not self._recovery_board(tick, boat_id, service, incident):
                return
        elif not service["picked_up"]:
            seats = min(incident.people, boat.capacity - boat.passengers)
            if seats <= 0:
                self.manager._log(
                    tick,
                    "BOARD_SKIPPED",
                    "engine",
                    {
                        "boat_id": boat_id,
                        "incident_id": incident_id,
                        "reason": "no free seats",
                    },
                )
                return
            ok, _ = self.manager.board_boat(boat_id, seats, tick, actor="engine")
            if not ok:
                return
            service["picked_up"] = True
            service["seats"] = seats
            if incident.status in ("OPEN", "ASSIGNED"):
                self._set_incident(
                    incident_id,
                    "IN_PROGRESS",
                    f"boat {boat_id} on scene, boarded {seats}",
                    tick,
                )
            if boat.status == "EN_ROUTE_TO_INCIDENT":
                self.manager.transition_boat(
                    boat_id,
                    "RESCUING",
                    f"boat {boat_id} rescuing at {incident_id}",
                    tick,
                    actor="engine",
                )
            if boat.status == "RESCUING":
                self._assignment_started(
                    service,
                    boat_id,
                    tick,
                    f"boat {boat_id} rescuing at {incident_id}",
                )
        if boat.status != "RESCUING":
            return
        shelter_id = self._route_to_best_shelter(tick, boat_id, service)
        if shelter_id is None:
            self.manager._log(
                tick,
                "SHELTER_FULL",
                "engine",
                {
                    "boat_id": boat_id,
                    "incident_id": incident_id,
                    "reason": "no shelter with free seats",
                },
            )
            return
        self.manager.transition_boat(
            boat_id,
            "TRANSPORTING_TO_SHELTER",
            f"boat {boat_id} transporting to {shelter_id}",
            tick,
            actor="engine",
        )
        service["phase"] = "to_shelter"

    def _recovery_board(
        self, tick: int, boat_id: str, service: dict, incident: Any
    ) -> bool:
        """Board stranded passengers off a failed hull (Step 05 transfer).

        Source is the first (sorted id) ``FAILED`` boat at the recovery
        incident's node still holding passengers; the rescuer takes
        ``min(free seats, hull passengers)``, the hull's count drops by
        exactly that (a ``TRANSFER`` audit entry names both hulls), and
        the service records the boarded count for the shelter leg. When
        no hull holds passengers (already evacuated) the pickup still
        completes with whatever is aboard and logs ``RECOVERY_EMPTY`` —
        the recovery people ARE the hull's passengers, so there is never
        a fallback boarding from ``incident.people``. Returns True when
        the scene transitions below may run.
        """
        boat = self.world.boats[boat_id]
        sources = sorted(
            bid
            for bid, hull in self.world.boats.items()
            if hull.status == "FAILED"
            and hull.node_id == incident.node_id
            and hull.passengers > 0
        )
        if not sources:
            service["picked_up"] = True
            service["seats"] = int(boat.passengers)
            self.manager._log(
                tick, "RECOVERY_EMPTY", "engine",
                {
                    "boat_id": boat_id,
                    "incident_id": incident.incident_id,
                    "reason": "no stranded passengers at node",
                },
            )
        else:
            source_id = sources[0]
            source = self.world.boats[source_id]
            count = min(boat.capacity - boat.passengers, source.passengers)
            if count <= 0:
                self.manager._log(
                    tick, "BOARD_SKIPPED", "engine",
                    {
                        "boat_id": boat_id,
                        "incident_id": incident.incident_id,
                        "reason": "no free seats",
                    },
                )
                return False
            ok, _ = self.manager.board_boat(boat_id, count, tick, actor="engine")
            if not ok:
                return False
            source.passengers -= count
            if source.passengers == 0:
                source.needs_recovery = False
            self.manager._log(
                tick, "TRANSFER", "engine",
                {
                    "from_boat": source_id,
                    "to_boat": boat_id,
                    "people": count,
                    "incident_id": incident.incident_id,
                    "reason": f"transferred {count} from {source_id} "
                    f"to {boat_id}",
                },
            )
            service["picked_up"] = True
            service["seats"] = count
            if incident.status in ("OPEN", "ASSIGNED"):
                self._set_incident(
                    incident.incident_id,
                    "IN_PROGRESS",
                    f"boat {boat_id} transferred {count} from {source_id}",
                    tick,
                )
        if boat.status == "EN_ROUTE_TO_INCIDENT":
            self.manager.transition_boat(
                boat_id,
                "RESCUING",
                f"boat {boat_id} rescuing at {incident.incident_id}",
                tick,
                actor="engine",
            )
        if boat.status == "RESCUING":
            self._assignment_started(
                service,
                boat_id,
                tick,
                f"boat {boat_id} rescuing at {incident.incident_id}",
            )
        return True

    def _route_to_best_shelter(
        self, tick: int, boat_id: str, service: dict
    ) -> str | None:
        boat = self.world.boats[boat_id]
        aid = service.get("assignment_id")
        assignment = self.assignments.get(aid) if isinstance(aid, str) else None
        commit_shelter = assignment.shelter_id if assignment is not None else None
        seats = int(service.get("seats", 1))
        # The commit already holds seats at the proposal shelter; exchange
        # that hold for one at the actual delivery shelter so seats are
        # never held twice (which would leak when the shelters differ).
        # Legacy/restored entries without a known assignment keep the old
        # reserve-only behavior.
        if commit_shelter is not None:
            self.manager.release_shelter(
                commit_shelter, aid, tick, actor="engine"
            )
        options: list[tuple[int, str, dict]] = []
        for shelter_id in sorted(self.world.shelters):
            if self.world.shelter_remaining(shelter_id) <= 0:
                continue
            shelter = self.world.shelters[shelter_id]
            route = find_route(self.world, boat.node_id, shelter.node_id, "water")
            if route is None:
                continue
            options.append((route["eta_ticks"], shelter_id, route))
        options.sort(key=lambda item: (item[0], item[1]))
        for _, shelter_id, route in options:
            shelter = self.world.shelters[shelter_id]
            ok, _ = self.manager.reserve_shelter(
                shelter_id, service["assignment_id"], seats, tick, actor="engine"
            )
            if not ok:
                continue
            service["shelter_id"] = shelter.node_id
            service["shelter_ref"] = shelter_id
            self.manager.set_route(
                boat_id, route["edges"], shelter.node_id, tick=tick, actor="engine"
            )
            return shelter_id
        # No delivery shelter fits: restore the commit-time hold so the
        # seats are not lost while the boat waits (single-threaded tick, so
        # the freed seats are still free and this always succeeds).
        if commit_shelter is not None:
            self.manager.reserve_shelter(
                commit_shelter, aid, seats, tick, actor="engine"
            )
        return None

    def _boat_dropoff(self, tick: int, boat_id: str, service: dict) -> None:
        boat = self.world.boats[boat_id]
        if boat.status != "TRANSPORTING_TO_SHELTER":
            return
        shelter_id = service.get("shelter_ref")
        if shelter_id is None:
            return
        self.manager.checkin_shelter(
            shelter_id, service["assignment_id"], tick, actor="engine"
        )
        dropped = boat.passengers
        boat.passengers = 0
        self.manager._log(
            tick,
            "DISEMBARK",
            "engine",
            {
                "boat_id": boat_id,
                "shelter_id": shelter_id,
                "passengers": dropped,
                "reason": f"disembarked {dropped} at {shelter_id}",
            },
        )
        incident_id = service["incident_id"]
        incident = self.world.incidents.get(incident_id)
        if incident is not None and incident.status != "SERVED":
            self._set_incident(
                incident_id,
                "SERVED",
                f"boat {boat_id} delivered to {shelter_id}",
                tick,
            )
        self._assignment_completed(
            service,
            boat_id,
            tick,
            f"boat {boat_id} delivered {incident_id} to {shelter_id}",
        )
        self.manager.transition_boat(
            boat_id,
            "RECOVERY",
            f"boat {boat_id} completed {incident_id}",
            tick,
            actor="engine",
        )
        self.manager.transition_boat(
            boat_id,
            "AVAILABLE",
            f"boat {boat_id} recovered after {incident_id}",
            tick,
            actor="engine",
        )
        boat.assignment_id = None
        self._clear_service(boat_id, incident_id)

    def _team_service(
        self, tick: int, team_id: str, service: dict, incident_id: str
    ) -> None:
        team = self.world.teams[team_id]
        incident = self.world.incidents[incident_id]
        if team.status == "ASSIGNED" and incident.status in ("OPEN", "ASSIGNED"):
            self.manager.transition_team(
                team_id,
                "ON_SCENE",
                f"team {team_id} on scene at {incident_id}",
                tick,
                actor="engine",
            )
            self._set_incident(
                incident_id,
                "IN_PROGRESS",
                f"team {team_id} servicing {incident_id}",
                tick,
            )
            self._assignment_started(
                service,
                team_id,
                tick,
                f"team {team_id} on scene at {incident_id}",
            )
        elif team.status == "ON_SCENE" and incident.status == "IN_PROGRESS":
            self._set_incident(
                incident_id,
                "SERVED",
                f"team {team_id} resolved {incident_id}",
                tick,
            )
            self._assignment_completed(
                service,
                team_id,
                tick,
                f"team {team_id} resolved {incident_id}",
            )
            self.manager.transition_team(
                team_id,
                "RETURNING",
                f"team {team_id} completed {incident_id}",
                tick,
                actor="engine",
            )
            self.manager.transition_team(
                team_id,
                "AVAILABLE",
                f"team {team_id} available after {incident_id}",
                tick,
                actor="engine",
            )
            team.assignment_id = None
            self._clear_service(team_id, incident_id)

    def _clear_service(self, resource_id: str, incident_id: str) -> None:
        self._service.pop(resource_id, None)
        if self._incident_owner.get(incident_id) == resource_id:
            del self._incident_owner[incident_id]
