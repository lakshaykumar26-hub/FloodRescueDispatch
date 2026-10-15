"""Authoritative in-memory state owner: applies events and moves resources.

Every mutation appends one ``{tick, kind, actor, detail}`` record to
``event_log`` (AGENTS.md hard rule 10). Unknown scheduler kinds are logged
as ``IGNORED`` and never raise.
"""

from __future__ import annotations

from typing import Any

from .event_scheduler import EventScheduler
from ..dispatch.report_store import ReportStore
from .world import Incident, World

# -- resource lifecycles (Phase 1 Step 05) --------------------------------
# Boat happy path: AVAILABLE -> ASSIGNED -> EN_ROUTE_TO_INCIDENT ->
# RESCUING -> TRANSPORTING_TO_SHELTER -> RECOVERY -> AVAILABLE.
# Exception states UNAVAILABLE/FAILED/STRANDED/RETURNING/MAINTENANCE are
# reachable from any state; recovery is RETURNING/MAINTENANCE/UNAVAILABLE
# -> AVAILABLE. FAILED is allowed as a target from any state.
_BOAT_EXCEPTIONS: frozenset[str] = frozenset(
    {"UNAVAILABLE", "FAILED", "STRANDED", "RETURNING", "MAINTENANCE"}
)

# Cancel path: cancel returns the resource to AVAILABLE
# (commitment_manager._release_resource). Direct cancel edges exist for
# pre-scene states, but there is deliberately no direct RESCUING->AVAILABLE
# edge: a mid-rescue boat must not teleport to AVAILABLE (the same
# skip-ahead the FSM guards against elsewhere). cancel() therefore routes
# that state via RETURNING — the honest state for a boat heading back,
# possibly with passengers aboard.
_BOAT_ALLOWED: dict[str, set[str]] = {
    "AVAILABLE": {"ASSIGNED"} | set(_BOAT_EXCEPTIONS),
    "ASSIGNED": {"EN_ROUTE_TO_INCIDENT", "AVAILABLE"} | set(_BOAT_EXCEPTIONS),
    "EN_ROUTE_TO_INCIDENT": {"RESCUING", "AVAILABLE"} | set(_BOAT_EXCEPTIONS),
    "RESCUING": {"TRANSPORTING_TO_SHELTER"} | set(_BOAT_EXCEPTIONS),
    "TRANSPORTING_TO_SHELTER": {"RECOVERY"} | set(_BOAT_EXCEPTIONS),
    "RECOVERY": {"AVAILABLE"} | set(_BOAT_EXCEPTIONS),
    "RETURNING": {"AVAILABLE", "UNAVAILABLE", "FAILED", "STRANDED", "MAINTENANCE"},
    "MAINTENANCE": {"AVAILABLE", "UNAVAILABLE", "FAILED", "STRANDED", "RETURNING"},
    "UNAVAILABLE": {"AVAILABLE", "FAILED", "STRANDED", "RETURNING", "MAINTENANCE"},
    "FAILED": {"UNAVAILABLE", "STRANDED", "RETURNING", "MAINTENANCE"},
    "STRANDED": {"UNAVAILABLE", "FAILED", "RETURNING", "MAINTENANCE"},
}

# States from which a new ASSIGNED mission is refused outright.
_BOAT_ASSIGNED_BLOCKED: frozenset[str] = frozenset(
    {"FAILED", "UNAVAILABLE", "MAINTENANCE", "STRANDED"}
)

# Ground-team simplified FSM (cancel returns resource to AVAILABLE).
_TEAM_ALLOWED: dict[str, set[str]] = {
    "AVAILABLE": {"ASSIGNED", "UNAVAILABLE"},
    "ASSIGNED": {"ON_SCENE", "UNAVAILABLE", "AVAILABLE"},
    "ON_SCENE": {"RETURNING", "UNAVAILABLE", "AVAILABLE"},
    "RETURNING": {"AVAILABLE", "UNAVAILABLE"},
    "UNAVAILABLE": {"AVAILABLE"},
}


class StateManager:
    """Owns a :class:`World`, its scheduler, routes, and audit log."""

    def __init__(self, world: World, seed: int = 42) -> None:
        self.world = world
        self.seed = seed
        self.scheduler = EventScheduler(seed=seed)
        self.event_log: list[dict] = []
        # resource_id -> {edge_ids: [...], next_index: int, dest: str}
        self.routes: dict[str, dict] = {}
        # Phase 4 Step 04/05: append-only store for contradictory edge
        # reports (scheduler REPORT events file claims here via the
        # engine; never auto-closes edges — see ReportStore).
        self.reports = ReportStore()

    # -- logging --------------------------------------------------------
    def _log(self, tick: int, kind: str, actor: str, detail: dict) -> dict:
        entry = {"tick": tick, "kind": kind, "actor": actor, "detail": detail}
        self.event_log.append(entry)
        return entry

    # -- events ---------------------------------------------------------
    @staticmethod
    def _coerce(event: Any) -> tuple[int | None, Any, dict, str, Any]:
        """Return (tick, kind, payload, event_id, raw) for dict/object events."""
        if isinstance(event, dict):
            tick = event.get("tick")
            kind = event.get("kind")
            payload = event.get("payload", event.get("data", {}))
            if not isinstance(payload, dict):
                payload = {}
            event_id = event.get("event_id", "")
            return tick, kind, payload, event_id, event
        tick = getattr(event, "tick", None)
        kind = getattr(event, "kind", None)
        payload = getattr(event, "payload", getattr(event, "data", {}))
        if not isinstance(payload, dict):
            payload = {}
        event_id = getattr(event, "event_id", "")
        return tick, kind, payload, event_id, event

    def apply_event(self, event: Any, actor: str = "scheduler") -> None:
        """Dispatch one scheduler event onto the world.

        ``CLOSURE`` -> :meth:`apply_closure`,
        ``BRIDGE_CLOSURE`` -> :meth:`apply_closure` (reason ``bridge``),
        ``EDGE_REOPEN`` -> :meth:`apply_reopen`,
        ``FLOOD_RISE`` -> :meth:`apply_flood_rise`,
        ``INCIDENT_ARRIVAL`` -> :meth:`apply_incident`,
        ``BOAT_FAILURE`` -> :meth:`fail_boat`,
        ``SHELTER_FULL`` -> :meth:`apply_shelter_full`,
        ``COMMS_NOTE`` -> audit-only ``COMMS_NOTE`` log (no state change);
        anything else is logged as ``IGNORED`` and never raises.

        Tick ordering: a closure/reopen/rise at tick T applies before
        movement in tick T (the engine pops due events first each tick).
        Assignment-status transitions for affected routes
        (``REQUIRES_RECONCILIATION``/``CANCELLED``) belong to the Step 05
        pipeline, which calls the :mod:`dispatch.route_replanner`
        detection/replan primitives provided here.
        """
        tick, kind, payload, event_id, raw = self._coerce(event)
        if tick is None:
            tick = self.world.tick
        if kind == "CLOSURE":
            edge_id = payload.get("edge_id")
            if edge_id is None and isinstance(raw, dict):
                edge_id = raw.get("edge_id")
            if edge_id is None:
                self._log(
                    tick, "IGNORED", actor,
                    {"reason": "closure_missing_edge_id", "event_id": event_id},
                )
                return
            self.apply_closure(edge_id, tick, actor)
        elif kind == "BRIDGE_CLOSURE":
            edge_id = payload.get("edge_id")
            if edge_id is None and isinstance(raw, dict):
                edge_id = raw.get("edge_id")
            if edge_id is None:
                self._log(
                    tick, "IGNORED", actor,
                    {"reason": "closure_missing_edge_id", "event_id": event_id},
                )
                return
            self.apply_closure(edge_id, tick, actor, reason="bridge")
        elif kind == "EDGE_REOPEN":
            edge_id = payload.get("edge_id")
            if edge_id is None and isinstance(raw, dict):
                edge_id = raw.get("edge_id")
            if edge_id is None:
                self._log(
                    tick, "IGNORED", actor,
                    {"reason": "reopen_missing_edge_id", "event_id": event_id},
                )
                return
            self.apply_reopen(edge_id, tick, actor)
        elif kind == "FLOOD_RISE":
            edge_ids = payload.get("edge_ids")
            if edge_ids is None and isinstance(raw, dict):
                edge_ids = raw.get("edge_ids")
            risk_delta = payload.get("risk_delta")
            if risk_delta is None and isinstance(raw, dict):
                risk_delta = raw.get("risk_delta")
            if (
                not isinstance(edge_ids, list)
                or not all(isinstance(eid, str) for eid in edge_ids)
                or isinstance(risk_delta, bool)
                or not isinstance(risk_delta, (int, float))
            ):
                self._log(
                    tick, "IGNORED", actor,
                    {"reason": "flood_rise_bad_payload", "event_id": event_id},
                )
                return
            self.apply_flood_rise(edge_ids, float(risk_delta), tick, actor)
        elif kind == "INCIDENT_ARRIVAL":
            data = dict(payload)
            if not data and isinstance(raw, dict):
                data = {
                    k: v for k, v in raw.items()
                    if k not in ("tick", "kind", "payload", "event_id", "data")
                }
            self.apply_incident(data, tick, actor)
        elif kind == "BOAT_FAILURE":
            boat_id = payload.get("boat_id")
            if boat_id is None and isinstance(raw, dict):
                boat_id = raw.get("boat_id")
            if not isinstance(boat_id, str):
                self._log(
                    tick, "IGNORED", actor,
                    {"reason": "boat_failure_missing_boat_id", "event_id": event_id},
                )
                return
            self.fail_boat(boat_id, tick, actor)
        elif kind == "SHELTER_FULL":
            shelter_id = payload.get("shelter_id")
            if shelter_id is None and isinstance(raw, dict):
                shelter_id = raw.get("shelter_id")
            if not isinstance(shelter_id, str):
                self._log(
                    tick, "IGNORED", actor,
                    {"reason": "shelter_full_missing_shelter_id", "event_id": event_id},
                )
                return
            self.apply_shelter_full(shelter_id, tick, actor)
        elif kind == "COMMS_NOTE":
            # Phase 4 Step 05: operator/comms annotation (e.g. simulated
            # partition cue for Phase 5). Audit-only: no state change.
            # Malformed payloads (missing/non-string message) are IGNORED.
            message = payload.get("message")
            if message is None and isinstance(raw, dict):
                message = raw.get("message")
            if not isinstance(message, str):
                self._log(
                    tick, "IGNORED", actor,
                    {"reason": "comms_note_bad_payload", "event_id": event_id},
                )
                return
            self._log(tick, "COMMS_NOTE", actor, {"message": message})
        else:
            self._log(
                tick, "IGNORED", actor,
                {"reason": "unknown_kind", "kind": kind, "event_id": event_id},
            )

    def apply_closure(
        self, edge_id: str, tick: int, actor: str = "scheduler",
        reason: str | None = None,
    ) -> None:
        """Close one edge and record when it changed.

        ``reason`` (e.g. ``"bridge"`` for ``BRIDGE_CLOSURE`` events) is
        recorded in the ``CLOSURE`` log detail when given; plain
        ``CLOSURE`` events log exactly ``{"edge_id": ...}`` as before.
        """
        edge = self.world.edges.get(edge_id)
        if edge is None:
            self._log(
                tick, "IGNORED", actor,
                {"reason": "unknown_edge", "edge_id": edge_id},
            )
            return
        edge.status = "closed"
        edge.last_updated_tick = tick
        detail: dict = {"edge_id": edge_id}
        if reason is not None:
            detail["reason"] = reason
        self._log(tick, "CLOSURE", actor, detail)

    def apply_reopen(self, edge_id: str, tick: int, actor: str = "scheduler") -> None:
        """Reopen one edge and record when it changed.

        Unknown edges log ``IGNORED`` and never raise. Detection of which
        routes may reuse the edge, and any assignment-status transitions,
        belong to the Step 05 pipeline (see
        :mod:`dispatch.route_replanner` primitives).
        """
        edge = self.world.edges.get(edge_id)
        if edge is None:
            self._log(
                tick, "IGNORED", actor,
                {"reason": "unknown_edge", "edge_id": edge_id},
            )
            return
        edge.status = "open"
        edge.last_updated_tick = tick
        self._log(tick, "EDGE_REOPENED", actor, {"edge_id": edge_id})

    def apply_flood_rise(
        self, edge_ids: list[str], risk_delta: float, tick: int,
        actor: str = "scheduler",
    ) -> None:
        """Raise ``risk_level`` by ``risk_delta`` on each listed edge.

        Levels clamp to ``[0, 1]`` and ``last_updated_tick`` advances on
        every touched edge; exactly one ``FLOOD_RISE`` log records
        ``{edge_ids, risk_delta}``. Unknown edge IDs are skipped (they
        cannot be bumped) and never raise.
        """
        for edge_id in edge_ids:
            edge = self.world.edges.get(edge_id)
            if edge is None:
                continue
            edge.risk_level = min(1.0, max(0.0, edge.risk_level + risk_delta))
            edge.last_updated_tick = tick
        self._log(
            tick, "FLOOD_RISE", actor,
            {"edge_ids": list(edge_ids), "risk_delta": risk_delta},
        )

    def apply_incident(self, data: dict, tick: int, actor: str = "scheduler") -> None:
        """Construct an :class:`Incident` from ``data`` and add it to the world."""
        record = dict(data)
        record.setdefault("created_tick", tick)
        incident = Incident.model_validate(record)
        self.world.incidents[incident.incident_id] = incident
        self._log(
            tick, "INCIDENT_ARRIVAL", actor,
            {"incident_id": incident.incident_id, "node_id": incident.node_id},
        )

    # -- boat failure (Phase 4 Step 02) ---------------------------------
    def fail_boat(self, boat_id: str, tick: int, actor: str = "scheduler") -> dict:
        """Fail a boat, keeping its passengers aboard for recovery.

        Sets status ``FAILED`` via :meth:`transition_boat` (which sets
        ``needs_recovery`` when ``passengers > 0`` and never zeroes them).
        The active assignment (if any) is NOT cancelled here — the caller
        (``dispatch.commitment_manager.trigger_recovery``) owns that — so
        this only flags: the outcome records ``had_assignment`` (the
        ``assignment_id`` the boat held, or ``None``) and ``passengers``,
        and logs ``BOAT_FAILED`` with reason + tick + actor.

        Recovery incidents are created by the caller, hence
        ``recovery_incident_id`` is always ``None`` at this level (the key
        exists so Step 05's engine wiring can fill it in). Unknown boats
        log ``IGNORED`` and return ``{"error": "UNKNOWN_BOAT"}``; never
        raises.
        """
        boat = self.world.boats.get(boat_id)
        if boat is None:
            self._log(
                tick, "IGNORED", actor,
                {"reason": "unknown_boat", "boat_id": boat_id},
            )
            return {
                "boat_id": boat_id,
                "had_assignment": None,
                "passengers": 0,
                "recovery_incident_id": None,
                "error": "UNKNOWN_BOAT",
            }
        had_assignment = boat.assignment_id
        passengers = boat.passengers
        self.transition_boat(
            boat_id, "FAILED", f"boat {boat_id} failed", tick, actor=actor
        )
        self._log(
            tick, "BOAT_FAILED", actor,
            {"boat_id": boat_id, "passengers": passengers,
             "assignment_id": had_assignment},
        )
        return {
            "boat_id": boat_id,
            "had_assignment": had_assignment,
            "passengers": passengers,
            "recovery_incident_id": None,
        }

    # -- routes / movement ----------------------------------------------
    def apply_shelter_full(
        self, shelter_id: str, tick: int, actor: str = "scheduler"
    ) -> None:
        """Mark a shelter full: it stops accepting new reservations.

        Sets ``accepting=False`` (existing holds and occupancy are
        untouched) and logs ``SHELTER_FULL`` with ``{shelter_id,
        occupancy, capacity}``. Unknown shelters log ``IGNORED`` and never
        raise. Detection of affected assignments and any reassignment
        belong to the Step 05 pipeline, which calls the
        :mod:`dispatch.commitment_manager` destination-swap helper.
        """
        shelter = self.world.shelters.get(shelter_id)
        if shelter is None:
            self._log(
                tick, "IGNORED", actor,
                {"reason": "unknown_shelter", "shelter_id": shelter_id},
            )
            return
        shelter.accepting = False
        self._log(
            tick, "SHELTER_FULL", actor,
            {"shelter_id": shelter_id, "occupancy": shelter.occupancy,
             "capacity": shelter.capacity},
        )
    def set_route(
        self,
        resource_id: str,
        edge_ids: list[str],
        dest: str,
        tick: int | None = None,
        actor: str = "engine",
    ) -> None:
        """Store a route for later one-hop-per-tick movement."""
        self.routes[resource_id] = {
            "edge_ids": list(edge_ids),
            "next_index": 0,
            "dest": dest,
        }
        self._log(
            self.world.tick if tick is None else tick,
            "ROUTE_SET",
            actor,
            {"resource_id": resource_id, "edge_ids": list(edge_ids), "dest": dest},
        )

    def advance_positions(self, tick: int, actor: str = "engine") -> None:
        """Move every routed boat/team one hop along its next open edge.

        Open edges are traversed normally; ``disputed`` edges are still
        traversed but emit an extra warning log first. Closed, missing, or
        off-route edges hold the resource in place and log ``ROUTE_BLOCKED``
        with the offending ``edge_id``. Boat fuel drops by 1 per hop
        (floored at 0); ground teams carry no fuel.
        """
        if tick > self.world.tick:
            self.world.tick = tick
        for resource_id, route in self.routes.items():
            edge_ids = route.get("edge_ids", [])
            index = route.get("next_index", 0)
            if index >= len(edge_ids):
                continue
            resource = self.world.boats.get(resource_id)
            is_boat = resource is not None
            if resource is None:
                resource = self.world.teams.get(resource_id)
            if resource is None:
                self._log(
                    tick, "ROUTE_BLOCKED", actor,
                    {"resource_id": resource_id, "reason": "unknown_resource"},
                )
                continue
            edge_id = edge_ids[index]
            edge = self.world.edges.get(edge_id)
            if edge is None or edge.status == "closed":
                self._log(
                    tick, "ROUTE_BLOCKED", actor,
                    {
                        "resource_id": resource_id,
                        "edge_id": edge_id,
                        "reason": "unknown_edge" if edge is None else "edge_closed",
                    },
                )
                continue
            current = resource.node_id
            if edge.from_node == current:
                nxt = edge.to_node
            elif edge.to_node == current:
                nxt = edge.from_node
            else:
                self._log(
                    tick, "ROUTE_BLOCKED", actor,
                    {
                        "resource_id": resource_id,
                        "edge_id": edge_id,
                        "reason": "route_mismatch",
                        "node_id": current,
                    },
                )
                continue
            if edge.status == "disputed":
                self._log(
                    tick, "DISPUTED_EDGE_WARNING", actor,
                    {
                        "resource_id": resource_id,
                        "edge_id": edge_id,
                        "warning": "disputed_edge",
                    },
                )
            previous = resource.node_id
            resource.node_id = nxt
            route["next_index"] = index + 1
            if is_boat:
                resource.fuel = max(0.0, resource.fuel - 1)
            self._log(
                tick, "MOVE", actor,
                {
                    "resource_id": resource_id,
                    "edge_id": edge_id,
                    "from_node": previous,
                    "to_node": nxt,
                },
            )

    # -- resource lifecycles ------------------------------------------
    def transition_boat(
        self, boat_id: str, to: str, reason: str, tick: int, actor: str = "engine"
    ) -> tuple[bool, str]:
        """Guarded boat FSM transition.

        Returns ``(True, "OK")`` on success, else ``(False, <code>)`` where
        ``<code>`` is ``REJECTED:ILLEGAL_TRANSITION``,
        ``REJECTED:RESOURCE_UNAVAILABLE`` or ``REJECTED:UNKNOWN_RESOURCE``.
        Every attempt appends ``{tick, transition, actor, reason}`` to
        ``boat.history`` and ``{tick, kind, actor, detail}`` to
        ``event_log``; refused transitions never mutate ``status``.
        ``FAILED`` with ``passengers > 0`` sets ``needs_recovery`` and
        keeps passengers (never zeroed).
        """
        boat = self.world.boats.get(boat_id)
        if boat is None:
            self._log(
                tick, "IGNORED", actor,
                {"reason": "unknown_resource", "resource_id": boat_id, "to": to},
            )
            return False, "REJECTED:UNKNOWN_RESOURCE"
        frm = boat.status
        if to == "ASSIGNED" and frm in _BOAT_ASSIGNED_BLOCKED:
            boat.history.append(
                {"tick": tick, "transition": f"{frm}->{to}",
                 "actor": actor, "reason": reason,
                 "ok": False, "result": "REJECTED:RESOURCE_UNAVAILABLE"}
            )
            self._log(
                tick, "BOAT_TRANSITION", actor,
                {"boat_id": boat_id, "from": frm, "to": to,
                 "reason": reason, "ok": False,
                 "result": "REJECTED:RESOURCE_UNAVAILABLE"},
            )
            return False, "REJECTED:RESOURCE_UNAVAILABLE"
        allowed = _BOAT_ALLOWED.get(frm, set())
        if to not in allowed:
            boat.history.append(
                {"tick": tick, "transition": f"{frm}->{to}",
                 "actor": actor, "reason": reason,
                 "ok": False, "result": "REJECTED:ILLEGAL_TRANSITION"}
            )
            self._log(
                tick, "BOAT_TRANSITION", actor,
                {"boat_id": boat_id, "from": frm, "to": to,
                 "reason": reason, "ok": False,
                 "result": "REJECTED:ILLEGAL_TRANSITION"},
            )
            return False, "REJECTED:ILLEGAL_TRANSITION"
        if to == "FAILED" and boat.passengers > 0:
            boat.needs_recovery = True
        boat.status = to  # type: ignore[assignment]
        boat.history.append(
            {"tick": tick, "transition": f"{frm}->{to}",
             "actor": actor, "reason": reason, "ok": True, "result": "OK"}
        )
        self._log(
            tick, "BOAT_TRANSITION", actor,
            {"boat_id": boat_id, "from": frm, "to": to,
             "reason": reason, "ok": True, "result": "OK"},
        )
        return True, "OK"

    def transition_team(
        self, team_id: str, to: str, reason: str, tick: int, actor: str = "engine"
    ) -> tuple[bool, str]:
        """Guarded ground-team FSM transition.

        Allowed: ``AVAILABLE->ASSIGNED->ON_SCENE->RETURNING->AVAILABLE``
        plus ``->UNAVAILABLE`` from any non-terminal state and
        ``UNAVAILABLE->AVAILABLE``. Illegal jumps return
        ``(False, "REJECTED:ILLEGAL_TRANSITION")``. Every attempt is
        logged to ``team.history`` and ``event_log``.
        """
        team = self.world.teams.get(team_id)
        if team is None:
            self._log(
                tick, "IGNORED", actor,
                {"reason": "unknown_resource", "resource_id": team_id, "to": to},
            )
            return False, "REJECTED:UNKNOWN_RESOURCE"
        frm = team.status
        allowed = _TEAM_ALLOWED.get(frm, set())
        if to not in allowed:
            team.history.append(
                {"tick": tick, "transition": f"{frm}->{to}",
                 "actor": actor, "reason": reason,
                 "ok": False, "result": "REJECTED:ILLEGAL_TRANSITION"}
            )
            self._log(
                tick, "TEAM_TRANSITION", actor,
                {"team_id": team_id, "from": frm, "to": to,
                 "reason": reason, "ok": False,
                 "result": "REJECTED:ILLEGAL_TRANSITION"},
            )
            return False, "REJECTED:ILLEGAL_TRANSITION"
        team.status = to  # type: ignore[assignment]
        team.history.append(
            {"tick": tick, "transition": f"{frm}->{to}",
             "actor": actor, "reason": reason, "ok": True, "result": "OK"}
        )
        self._log(
            tick, "TEAM_TRANSITION", actor,
            {"team_id": team_id, "from": frm, "to": to,
             "reason": reason, "ok": True, "result": "OK"},
        )
        return True, "OK"

    def board_boat(
        self, boat_id: str, count: int, tick: int, actor: str = "engine"
    ) -> tuple[bool, str]:
        """Board ``count`` passengers onto a boat.

        Refuses ``FAILED`` boats with ``REJECTED:RESOURCE_UNAVAILABLE``
        and over-capacity loads with ``REJECTED:OVER_CAPACITY``; both
        leave ``passengers`` unchanged but still log history + event_log.
        """
        boat = self.world.boats.get(boat_id)
        if boat is None:
            self._log(
                tick, "IGNORED", actor,
                {"reason": "unknown_resource", "resource_id": boat_id},
            )
            return False, "REJECTED:UNKNOWN_RESOURCE"
        if boat.status == "FAILED":
            boat.history.append(
                {"tick": tick, "transition": f"BOARD+{count}",
                 "actor": actor, "reason": "REJECTED:RESOURCE_UNAVAILABLE",
                 "ok": False, "result": "REJECTED:RESOURCE_UNAVAILABLE",
                 "count": count}
            )
            self._log(
                tick, "BOARD", actor,
                {"boat_id": boat_id, "count": count,
                 "passengers": boat.passengers, "capacity": boat.capacity,
                 "reason": "REJECTED:RESOURCE_UNAVAILABLE",
                 "ok": False, "result": "REJECTED:RESOURCE_UNAVAILABLE"},
            )
            return False, "REJECTED:RESOURCE_UNAVAILABLE"
        if count <= 0:
            boat.history.append(
                {"tick": tick, "transition": f"BOARD+{count}",
                 "actor": actor, "reason": "REJECTED:ILLEGAL_COUNT",
                 "ok": False, "result": "REJECTED:ILLEGAL_COUNT",
                 "count": count}
            )
            self._log(
                tick, "BOARD", actor,
                {"boat_id": boat_id, "count": count,
                 "passengers": boat.passengers, "capacity": boat.capacity,
                 "reason": "REJECTED:ILLEGAL_COUNT",
                 "ok": False, "result": "REJECTED:ILLEGAL_COUNT"},
            )
            return False, "REJECTED:ILLEGAL_COUNT"
        if boat.passengers + count > boat.capacity:
            boat.history.append(
                {"tick": tick, "transition": f"BOARD+{count}",
                 "actor": actor, "reason": "REJECTED:OVER_CAPACITY",
                 "ok": False, "result": "REJECTED:OVER_CAPACITY",
                 "count": count}
            )
            self._log(
                tick, "BOARD", actor,
                {"boat_id": boat_id, "count": count,
                 "passengers": boat.passengers, "capacity": boat.capacity,
                 "reason": "REJECTED:OVER_CAPACITY",
                 "ok": False, "result": "REJECTED:OVER_CAPACITY"},
            )
            return False, "REJECTED:OVER_CAPACITY"
        boat.passengers += count
        board_reason = f"boarded {count} passengers"
        boat.history.append(
            {"tick": tick, "transition": f"BOARD+{count}",
             "actor": actor, "reason": board_reason,
             "ok": True, "result": "OK", "count": count}
        )
        self._log(
            tick, "BOARD", actor,
            {"boat_id": boat_id, "count": count,
             "passengers": boat.passengers, "capacity": boat.capacity,
             "reason": board_reason, "ok": True, "result": "OK"},
        )
        return True, "OK"

    def can_depart(self, boat_id: str, route_eta: int) -> tuple[bool, str]:
        """Check fuel feasibility without mutating fuel.

        Returns ``(True, "OK")`` iff
        ``boat.fuel >= route_eta + boat.fuel_reserve``, else
        ``(False, "FUEL_INSUFFICIENT")``.
        """
        boat = self.world.boats.get(boat_id)
        if boat is None:
            return False, "REJECTED:UNKNOWN_RESOURCE"
        if boat.fuel >= route_eta + boat.fuel_reserve:
            return True, "OK"
        return False, "FUEL_INSUFFICIENT"

    # -- shelter accounting (StateManager-audited wrappers) ---------------
    def reserve_shelter(
        self, shelter_id: str, assignment_id: str, seats: int,
        tick: int, actor: str = "engine",
    ) -> tuple[bool, str]:
        """Reserve shelter seats with ``event_log`` auditing.

        Delegates capacity math to :meth:`Shelter.reserve` (which refuses
        overbooking and logs to ``shelter.history``) and mirrors the
        outcome into ``event_log``. ``occupancy + reservations`` never
        exceeds ``capacity`` on success.
        """
        shelter = self.world.shelters.get(shelter_id)
        if shelter is None:
            self._log(
                tick, "IGNORED", actor,
                {"reason": "unknown_shelter", "shelter_id": shelter_id},
            )
            return False, "REJECTED:UNKNOWN_SHELTER"
        ok = shelter.reserve(assignment_id, seats, tick=tick)
        code = "OK" if ok else "REJECTED:OVER_CAPACITY"
        if not ok and seats <= 0:
            code = "REJECTED:INVALID_SEATS"
        # Surface the world-layer reason in the event detail.
        world_reason = shelter.history[-1].get("reason", code) if shelter.history else code
        self._log(
            tick, "SHELTER_RESERVE", actor,
            {"shelter_id": shelter_id, "assignment_id": assignment_id,
             "seats": seats, "reason": world_reason,
             "ok": ok, "result": code if not ok else "OK"},
        )
        return ok, ("OK" if ok else world_reason)

    def checkin_shelter(
        self, shelter_id: str, assignment_id: str,
        tick: int, actor: str = "engine",
    ) -> tuple[bool, str]:
        """Move a shelter reservation into occupancy with auditing."""
        shelter = self.world.shelters.get(shelter_id)
        if shelter is None:
            self._log(
                tick, "IGNORED", actor,
                {"reason": "unknown_shelter", "shelter_id": shelter_id},
            )
            return False, "REJECTED:UNKNOWN_SHELTER"
        seats = shelter.checkin(assignment_id, tick=tick)
        if seats:
            self._log(
                tick, "SHELTER_CHECKIN", actor,
                {"shelter_id": shelter_id, "assignment_id": assignment_id,
                 "seats": seats, "reason": "OK", "ok": True, "result": "OK"},
            )
            return True, "OK"
        self._log(
            tick, "SHELTER_CHECKIN", actor,
            {"shelter_id": shelter_id, "assignment_id": assignment_id,
             "seats": 0, "reason": "REJECTED:UNKNOWN_ASSIGNMENT",
             "ok": False, "result": "REJECTED:UNKNOWN_ASSIGNMENT"},
        )
        return False, "REJECTED:UNKNOWN_ASSIGNMENT"

    def release_shelter(
        self, shelter_id: str, assignment_id: str,
        tick: int, actor: str = "engine",
    ) -> tuple[bool, str]:
        """Drop a shelter reservation with auditing (occupancy untouched)."""
        shelter = self.world.shelters.get(shelter_id)
        if shelter is None:
            self._log(
                tick, "IGNORED", actor,
                {"reason": "unknown_shelter", "shelter_id": shelter_id},
            )
            return False, "REJECTED:UNKNOWN_SHELTER"
        seats = shelter.release(assignment_id, tick=tick)
        if seats:
            self._log(
                tick, "SHELTER_RELEASE", actor,
                {"shelter_id": shelter_id, "assignment_id": assignment_id,
                 "seats": seats, "reason": "OK", "ok": True, "result": "OK"},
            )
            return True, "OK"
        self._log(
            tick, "SHELTER_RELEASE", actor,
            {"shelter_id": shelter_id, "assignment_id": assignment_id,
             "seats": 0, "reason": "REJECTED:UNKNOWN_ASSIGNMENT",
             "ok": False, "result": "REJECTED:UNKNOWN_ASSIGNMENT"},
        )
        return False, "REJECTED:UNKNOWN_ASSIGNMENT"
