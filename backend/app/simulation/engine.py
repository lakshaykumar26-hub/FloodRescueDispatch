"""Deterministic headless simulation loop (Phase 2 Step 05).

Must not import FastAPI, DB, or frontend code (AGENTS.md hard rule 1).
No wall-clock time and no unseeded randomness: ordering uses integer
``tick`` only, and every choice is a deterministic function of the world
state (sorted IDs, shortest-time routes, ranked incidents, lowest cost).
"""

from __future__ import annotations

import copy

from ..dispatch.bid_evaluator import check_feasible
from ..dispatch.centralized_scheduler import CentralizedScheduler
from ..dispatch.commitment_manager import (
    acknowledge,
    commit_assignment,
    complete,
    start_progress,
)
from ..dispatch.conflict_resolver import resolve
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


class Simulation:
    """Headless time-stepped loop over a :class:`World`.

    Fixed per-tick order (a closure at tick T applies before movement in
    tick T):

    1. ``clock.advance()`` and sync ``world.tick`` to the new tick.
    2. ``pop_due`` scheduler events for the new tick and ``apply_event``
       each of them (closures/incident arrivals land before movement).
    3. Progress active services: a resource whose route is exhausted
       (``routes[rid].next_index >= len(edge_ids)``) at its incident node
       boards/rescues (boat: ``board_boat``, incident ``OPEN/ASSIGNED``
       -> ``IN_PROGRESS``, ``RESCUING`` -> ``TRANSPORTING_TO_SHELTER``,
       route to the nearest shelter node with ``shelter_remaining > 0``,
       reserve seats, ``set_route`` to the shelter); a resource arriving
       at its shelter node checks in (incident -> ``SERVED``, boat
       ``RECOVERY`` -> ``AVAILABLE``, team ``RETURNING`` -> ``AVAILABLE``).
       Scene arrival advances the assignment lifecycle (``acknowledge`` +
       ``start_progress``); delivery ``complete``s it.
    4. ``advance_positions(tick)`` moves every routed resource one hop
       (holds + ``ROUTE_BLOCKED`` log when the next edge is closed).
    5. Dispatch (``CentralizedScheduler`` by default): ``propose`` ranks
       ``OPEN`` incidents and emits at most one proposal each (``PROPOSED``
       log per proposal with ``alternatives_considered``; ``REJECTED`` log
       per ``scheduler.last_rejections`` entry); ``resolve`` arbitrates
       same-tick contention (``REJECTED`` per conflict); each winner
       passes the ``check_feasible`` gate and the authoritative
       ``safety_validator.validate`` (``REJECTED`` with the exact code(s)
       on refusal) before ``commit_assignment`` commits it; committed
       winners get ``set_route`` + ``EN_ROUTE_TO_INCIDENT`` (boats) and
       ``_service``/``_incident_owner`` bookkeeping.
    6. Every ``snapshot_every`` ticks, ``take_snapshot`` into
       ``.snapshots`` keyed by tick, plus routes, pending scheduler
       events, in-flight service state, assignments, and proposals_seen
       (see ``from_snapshot``).

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
            self.manager.apply_event(event, actor="scheduler")
        self._progress_services(tick)
        self.manager.advance_positions(tick, actor="engine")
        self._dispatch(tick)
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
        if not service["picked_up"]:
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
