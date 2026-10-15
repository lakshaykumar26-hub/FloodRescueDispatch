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
    flag_reconciliation,
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

# Phase 5 Step 05: engine publishes belief snapshots through the
# store-and-forward gateway; mirror agents hold the only beliefs the
# negotiation scheduler may bid from. simulation/ must still import no
# FastAPI/DB/frontend code — agents + communications are allowed.
from ..agents.boat_agent import BoatAgent
from ..agents.ground_team_agent import GroundTeamAgent
from ..communications.deduplicator import Deduplicator
from ..communications.gateway import Gateway
from ..communications.simulated_network import SimulatedNetwork
from ..dispatch.negotiation_scheduler import world_to_belief_snapshot

try:
    from ..communications.comms_bridge import (
        COORDINATOR_ID,
        belief_payload_from_snapshot,
        build_agent_report,
        build_authority,
        deliver_to_agent,
        make_belief_message,
        to_belief_update,
    )
except ImportError:  # comms_bridge.py not yet present: local fallbacks.
    import copy as _copy

    COORDINATOR_ID = "DISPATCH-01"

    def belief_payload_from_snapshot(snapshot: dict, world_tick: int) -> dict:
        return {
            "edges": _copy.deepcopy(snapshot.get("edges", {})),
            "shelters": _copy.deepcopy(snapshot.get("shelters", {})),
            "assignments": _copy.deepcopy(snapshot.get("assignments", [])),
            "world_tick": int(world_tick),
        }

    def make_belief_message(
        sender: str,
        recipient: str,
        snapshot: dict,
        tick: int,
        version: int,
        seq: int,
        simulation_id: str = "SIM-001",
        ttl: int = 10,
    ) -> dict:
        tick_i = int(tick)
        try:
            world_tick = int(snapshot.get("tick", snapshot.get("world_tick", tick_i)))
        except (TypeError, ValueError):
            world_tick = tick_i
        payload = belief_payload_from_snapshot(snapshot, world_tick)
        payload = {"assignment_id": "-", "reason": "BELIEF_SYNC", **payload}
        return {
            "message_id": f"MSG-BELIEF-{tick_i:04d}-{int(seq):04d}",
            "type": "BOAT_STATUS_CHANGED",
            "sender_id": str(sender),
            "recipient_id": str(recipient),
            "simulation_id": str(simulation_id),
            "created_at_tick": tick_i,
            "expires_at_tick": tick_i + int(ttl),
            "version": int(version),
            "payload": payload,
        }

    def to_belief_update(msg_dict: dict) -> dict:
        payload = msg_dict.get("payload", {}) or {}
        try:
            created = int(msg_dict.get("created_at_tick", 0))
        except (TypeError, ValueError):
            created = 0
        world_tick = payload.get("world_tick", created)
        try:
            world_tick = int(world_tick)
        except (TypeError, ValueError):
            world_tick = created
        try:
            version = int(msg_dict.get("version", 0))
        except (TypeError, ValueError):
            version = 0
        return {
            "message_id": msg_dict.get("message_id"),
            "type": msg_dict.get("type"),
            "version": version,
            "edges": _copy.deepcopy(payload.get("edges") or {}),
            "shelters": _copy.deepcopy(payload.get("shelters") or {}),
            "assignments": _copy.deepcopy(payload.get("assignments") or []),
            "tick": created,
            "world_tick": world_tick,
        }

    def build_agent_report(
        agent: Any, service_entry: dict | None, assignment_registry: dict
    ) -> dict:
        agent_id = str(getattr(agent, "id", "?"))
        belief = getattr(agent, "local_belief", {}) or {}
        if not isinstance(belief, dict):
            belief = {}
        assignment_id = None
        if isinstance(service_entry, dict):
            aid = service_entry.get("assignment_id")
            if isinstance(aid, str):
                assignment_id = aid
        assignment_version = None
        assignment = (assignment_registry or {}).get(assignment_id)
        if assignment is not None:
            raw = (
                assignment.get("version")
                if isinstance(assignment, dict)
                else getattr(assignment, "version", None)
            )
            try:
                assignment_version = int(raw) if raw is not None else None
            except (TypeError, ValueError):
                assignment_version = None
        return {
            "agent_id": agent_id,
            "resource_id": agent_id,
            "belief_version": int(belief.get("belief_version", 0) or 0),
            "assignment_id": assignment_id,
            "assignment_version": assignment_version,
            "local_claims": [],
        }

    def build_authority(
        assignments: dict,
        routes: dict,
        tick: int,
        partition_started_tick: int | None,
    ) -> dict:
        auth: dict[str, dict] = {}
        for aid, rec in (assignments or {}).items():
            if isinstance(rec, dict):
                auth[str(aid)] = {
                    "status": str(rec.get("status")),
                    "version": int(rec.get("version", 0) or 0),
                    "resource_id": str(rec.get("resource_id", "")),
                    "incident_id": str(rec.get("incident_id", "")),
                }
            else:
                auth[str(aid)] = {
                    "status": str(getattr(rec, "status", "")),
                    "version": int(getattr(rec, "version", 0) or 0),
                    "resource_id": str(getattr(rec, "resource_id", "")),
                    "incident_id": str(getattr(rec, "incident_id", "")),
                }
        auth_routes: dict[str, dict] = {}
        for rid, route in (routes or {}).items():
            if isinstance(route, dict):
                edges = route.get("edge_ids", route.get("route_edge_ids", []))
                try:
                    edge_list = [str(e) for e in (edges or [])]
                except TypeError:
                    edge_list = []
                auth_routes[str(rid)] = {"edge_ids": edge_list, "next_index": 0}
        return {
            "tick": int(tick),
            "assignments": auth,
            "routes": auth_routes,
            "partition_started_tick": partition_started_tick,
        }

    def deliver_to_agent(agent: Any, msg_dict: dict, dedup: Any, tick: int) -> str:
        _ = tick
        message_id = str(msg_dict.get("message_id", "?"))
        if dedup.check(message_id) == "DUPLICATE":
            return "DUPLICATE"
        applied = agent.update_belief(to_belief_update(msg_dict))
        return "APPLIED" if applied else "STALE_IGNORED"

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
        network_config: dict | None = None,
        enable_comms: bool = True,
    ) -> None:
        self.world = world
        self.seed = seed
        self.snapshot_every = snapshot_every
        self.clock = Clock(start=world.tick)
        self.manager = StateManager(world, seed=seed)
        self.scheduler: Scheduler = (
            scheduler if scheduler is not None else CentralizedScheduler()
        )
        # Phase 5 Step 05: store-and-forward comms. The engine publishes
        # one belief message per mirror agent per tick through the gateway;
        # beliefs reach scheduler agents only via gateway delivery (never
        # via a direct global read).
        self.network = SimulatedNetwork(
            seed=seed, config=dict(network_config) if network_config else {}
        )
        self.gateway = Gateway(self.network, simulation_id="SIM-001")
        self.enable_comms = bool(enable_comms)
        # Lightweight BoatAgent/GroundTeamAgent mirrors for belief
        # tracking, independent of the scheduler's own agents.
        self.comms_agents: dict[str, Any] = {}
        # Consumer-side dedup, one per mirror agent.
        self._consumer_dedup: dict[str, Deduplicator] = {}
        # agent_id -> tick its current partition span started.
        self._partition_started: dict[str, int] = {}
        self._msg_seq = 0
        self.reconciliation_log: list[dict] = []
        if self.enable_comms:
            self._comms_patch_scheduler()
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
        simulation._restore_comms(data)
        return simulation

    def _restore_comms(self, data: dict) -> None:
        """Restore gateway/network/mirror beliefs from a step snapshot.

        Backward compatible: keys absent in pre-comms snapshots fall back
        to a fresh network/gateway and freshly ensured mirrors.
        """
        network: Any = None
        raw_network = data.get("network")
        if isinstance(raw_network, dict):
            try:
                network = SimulatedNetwork.from_dict(raw_network)
            except Exception:
                network = None
        if network is None:
            try:
                embedded = (data.get("gateway") or {}).get("network")
            except Exception:
                embedded = None
            if isinstance(embedded, dict):
                try:
                    network = SimulatedNetwork.from_dict(embedded)
                except Exception:
                    network = None
        if network is None:
            network = SimulatedNetwork(
                seed=int(data.get("seed", self.seed)), config={}
            )
        self.network = network
        raw_gateway = data.get("gateway")
        if isinstance(raw_gateway, dict):
            try:
                self.gateway = Gateway.from_dict(raw_gateway, self.network)
            except Exception:
                self.gateway = Gateway(self.network, simulation_id="SIM-001")
        try:
            self._msg_seq = int(data.get("msg_seq", 0) or 0)
        except (TypeError, ValueError):
            self._msg_seq = 0
        try:
            self.reconciliation_log = copy.deepcopy(
                data.get("reconciliation_log", [])
            )
        except Exception:
            self.reconciliation_log = []
        restored_spans = data.get("partition_started", {})
        if isinstance(restored_spans, dict):
            try:
                self._partition_started = {
                    str(aid): int(tick)
                    for aid, tick in restored_spans.items()
                }
            except (TypeError, ValueError):
                self._partition_started = {}
        else:
            self._partition_started = {}
        self._consumer_dedup = {}
        restored_dedup = data.get("consumer_dedup", {})
        if isinstance(restored_dedup, dict):
            for aid, payload in restored_dedup.items():
                try:
                    self._consumer_dedup[str(aid)] = Deduplicator.from_dict(
                        dict(payload)
                    )
                except Exception:
                    self._consumer_dedup[str(aid)] = Deduplicator()
        try:
            self._comms_ensure_agents()
        except Exception:
            pass
        saved_agents = data.get("comms_agents", {})
        if isinstance(saved_agents, dict):
            for aid, payload in saved_agents.items():
                agent = self.comms_agents.get(str(aid))
                if agent is None or not isinstance(payload, dict):
                    continue
                try:
                    agent.local_belief = copy.deepcopy(
                        payload.get("local_belief", agent.local_belief)
                    )
                    agent.world_tick_at_read = int(
                        payload.get("world_tick_at_read", 0) or 0
                    )
                except (TypeError, ValueError):
                    continue
                except Exception:
                    continue

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

    # -- comms wiring (Phase 5 Step 05) -----------------------------------
    def _comms_patch_scheduler(self) -> None:
        """Gate negotiation beliefs through the gateway mirrors.

        Replaces the negotiation scheduler's ``_sync_agents`` so boat/team
        position + status still refresh from ``world`` (movement truth),
        but their ``local_belief`` comes from this engine's gateway-fed
        mirror agents (deep-copied) instead of a fresh global snapshot.
        Incident/shelter agents keep the original behavior (they never
        bid from belief edges). Idempotent; no-op for schedulers without
        ``_sync_agents`` (e.g. centralized). Never raises.
        """
        try:
            sched = self.scheduler
            if not hasattr(sched, "_sync_agents"):
                return
            if getattr(sched, "_sync_agents_patched_by_engine", False):
                return
            original = sched._sync_agents
            engine = self

            def _patched(world: Any, tick: int) -> None:
                try:
                    original(world, tick)
                except Exception:
                    return
                try:
                    engine._comms_sync_scheduler_beliefs(tick)
                except Exception:
                    pass

            sched._sync_agents = _patched  # type: ignore[method-assign]
            try:
                sched._sync_agents_patched_by_engine = True  # type: ignore[attr-defined]
            except Exception:
                pass
        except Exception:
            pass

    def _comms_sync_scheduler_beliefs(self, tick: int) -> None:
        """Push gateway mirror beliefs into scheduler resource agents.

        For every scheduler agent whose id has a comms mirror, replace
        its ``local_belief`` (deep copy) and ``world_tick_at_read`` with
        the mirror's. A partitioned mirror's belief stays frozen, so the
        scheduler bids from stale belief — never from fresh global state.
        No-op when the scheduler holds no ``agents`` dict. Never raises.
        """
        _ = tick
        try:
            agents = getattr(self.scheduler, "agents", None)
            if not isinstance(agents, dict):
                return
            for aid, sched_agent in agents.items():
                mirror = self.comms_agents.get(aid)
                if mirror is None or sched_agent is None:
                    continue
                try:
                    sched_agent.local_belief = copy.deepcopy(mirror.local_belief)
                    sched_agent.world_tick_at_read = int(
                        getattr(mirror, "world_tick_at_read", 0) or 0
                    )
                except Exception:
                    continue
        except Exception:
            pass

    def _comms_ensure_agents(self) -> None:
        """Ensure one mirror agent per world boat/team.

        Creates missing ``BoatAgent``/``GroundTeamAgent`` mirrors and
        refreshes position/status (plus capacity/fuel/passengers/
        capabilities) from the world each tick BEFORE publish, so beliefs
        track movement truth while edge/shelter knowledge arrives only
        via gateway delivery. Never calls ``sense()`` here. Never raises.
        """
        try:
            for boat_id in sorted(self.world.boats):
                boat = self.world.boats[boat_id]
                agent = self.comms_agents.get(boat_id)
                if not isinstance(agent, BoatAgent):
                    fresh = BoatAgent(
                        boat.boat_id,
                        boat.capacity,
                        float(boat.fuel),
                        float(boat.fuel_reserve),
                        float(getattr(boat, "speed", 1.0)),
                        node_id=boat.node_id,
                        status=boat.status,
                        passengers=int(getattr(boat, "passengers", 0)),
                    )
                    if agent is not None:
                        try:
                            fresh.local_belief = getattr(
                                agent, "local_belief", fresh.local_belief
                            )
                            fresh.world_tick_at_read = int(
                                getattr(agent, "world_tick_at_read", 0) or 0
                            )
                        except Exception:
                            pass
                    self.comms_agents[boat_id] = fresh
                else:
                    try:
                        agent.capacity = boat.capacity
                        agent.fuel = float(boat.fuel)
                        agent.fuel_reserve = float(boat.fuel_reserve)
                        agent.speed = float(getattr(boat, "speed", 1.0))
                        agent.node_id = boat.node_id
                        agent.status = boat.status
                        agent.passengers = int(
                            getattr(boat, "passengers", 0)
                        )
                    except Exception:
                        continue
            for team_id in sorted(self.world.teams):
                team = self.world.teams[team_id]
                agent = self.comms_agents.get(team_id)
                if not isinstance(agent, GroundTeamAgent):
                    fresh = GroundTeamAgent(
                        team.team_id,
                        team.node_id,
                        list(team.capabilities or []),
                        status=team.status,
                    )
                    if agent is not None:
                        try:
                            fresh.local_belief = getattr(
                                agent, "local_belief", fresh.local_belief
                            )
                            fresh.world_tick_at_read = int(
                                getattr(agent, "world_tick_at_read", 0) or 0
                            )
                        except Exception:
                            pass
                    self.comms_agents[team_id] = fresh
                else:
                    try:
                        agent.node_id = team.node_id
                        agent.capabilities = list(team.capabilities or [])
                        agent.status = team.status
                    except Exception:
                        continue
        except Exception:
            pass

    def _comms_publish(self, tick: int) -> None:
        """Publish one belief message per mirror agent via the gateway.

        The snapshot is taken once per tick (``tick``/``version`` stamped)
        and fanned out in sorted agent-id order with a per-message
        sequence number. Comms failures never break the simulation.
        """
        try:
            snapshot = world_to_belief_snapshot(self.world)
            snapshot["tick"] = int(tick)
            snapshot["version"] = int(tick)
            for aid in sorted(self.comms_agents):
                try:
                    msg = make_belief_message(
                        COORDINATOR_ID,
                        aid,
                        snapshot,
                        int(tick),
                        version=int(tick),
                        seq=self._msg_seq,
                        ttl=10,
                    )
                    self._msg_seq += 1
                    self.gateway.send(msg, int(tick))
                except Exception:
                    continue
        except Exception:
            pass

    def _comms_deliver(self, tick: int) -> None:
        """Pump due messages into mirror beliefs; track partition spans.

        Groups gateway ``pump`` deliveries by recipient and feeds each
        through the recipient's consumer ``Deduplicator`` into
        ``deliver_to_agent``. Then records newly partitioned agents in
        ``_partition_started`` and reconciles agents whose partition just
        cleared. A partitioned agent receives zero deliveries, so its
        ``world_tick_at_read`` stays frozen behind the global tick.
        Never raises.
        """
        try:
            deliveries = self.gateway.pump(int(tick))
        except Exception:
            deliveries = []
        try:
            grouped: dict[str, list[dict]] = {}
            for delivery in deliveries or []:
                if not isinstance(delivery, dict):
                    continue
                msg = delivery.get("message", {})
                if not isinstance(msg, dict):
                    continue
                rid = str(msg.get("recipient_id", ""))
                grouped.setdefault(rid, []).append(msg)
            for rid in sorted(grouped):
                agent = self.comms_agents.get(rid)
                if agent is None:
                    continue
                try:
                    dedup = self._consumer_dedup.setdefault(rid, Deduplicator())
                except Exception:
                    continue
                for msg in grouped[rid]:
                    try:
                        deliver_to_agent(agent, msg, dedup, int(tick))
                    except Exception:
                        continue
        except Exception:
            pass
        try:
            for aid in sorted(self.comms_agents):
                try:
                    partitioned = not self.network.can_deliver(
                        COORDINATOR_ID, aid, int(tick)
                    )
                except Exception:
                    continue
                if partitioned:
                    if aid not in self._partition_started:
                        self._partition_started[aid] = int(tick)
                elif aid in self._partition_started:
                    try:
                        self._comms_reconcile_agent(aid, int(tick))
                    except Exception:
                        self._partition_started.pop(aid, None)
        except Exception:
            pass

    def _comms_reconcile_agent(self, aid: str, tick: int) -> None:
        """Reconcile one reconnected agent against authoritative state.

        Builds the gateway ``report``/``authority`` pair, runs
        ``gateway.reconcile``, sends any returned actions, surfaces stale
        or conflicting ownership via ``flag_reconciliation`` + a
        ``RECONCILED`` audit entry, and appends the outcome to
        ``reconciliation_log``. Route pushes are log-only: the agent
        holds position until re-ack (never force-moved). Never raises.
        """
        try:
            agent = self.comms_agents.get(aid)
            if agent is None:
                return
            report = build_agent_report(
                agent, self._service.get(aid), self.assignments
            )
            authority = build_authority(
                self.assignments,
                self.manager.routes,
                int(tick),
                self._partition_started.get(aid),
            )
            outcome, actions, detail = self.gateway.reconcile(
                report, authority, int(tick)
            )
            for action in actions or []:
                try:
                    if isinstance(action, dict):
                        self.gateway.send(action, int(tick))
                except Exception:
                    continue
            if not isinstance(detail, dict):
                detail = {"detail": detail}
            if outcome == "STALE_OWNERSHIP":
                claimed = report.get("assignment_id")
                if isinstance(claimed, str):
                    try:
                        flag_reconciliation(
                            self.assignments,
                            claimed,
                            int(tick),
                            "superseded while partitioned",
                        )
                    except Exception:
                        pass
                self.manager._log(
                    int(tick),
                    "RECONCILED",
                    "engine",
                    {
                        "agent_id": aid,
                        "outcome": outcome,
                        "detail": detail,
                    },
                )
            elif outcome == "STALE_ROUTE":
                self.manager._log(
                    int(tick),
                    "RECONCILED",
                    "engine",
                    {
                        "agent_id": aid,
                        "outcome": outcome,
                        "note": "route push issued; "
                        "hold position until re-ack",
                        "detail": detail,
                    },
                )
            elif outcome == "CONFLICT":
                self.manager._log(
                    int(tick),
                    "RECONCILED",
                    "engine",
                    {
                        "agent_id": aid,
                        "outcome": outcome,
                        "detail": detail,
                    },
                )
            else:  # IN_SYNC (or unknown code): quiet audit entry.
                self.manager._log(
                    int(tick),
                    "RECONCILED",
                    "engine",
                    {"agent_id": aid, "outcome": outcome},
                )
            try:
                self.reconciliation_log.append(
                    {
                        "tick": int(tick),
                        "agent_id": aid,
                        "outcome": outcome,
                        "detail": copy.deepcopy(detail),
                    }
                )
            except Exception:
                self.reconciliation_log.append(
                    {
                        "tick": int(tick),
                        "agent_id": aid,
                        "outcome": outcome,
                        "detail": {},
                    }
                )
        except Exception:
            pass
        finally:
            try:
                self._partition_started.pop(aid, None)
            except Exception:
                pass

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
        # Phase 5 Step 05: beliefs flow only through the gateway. Mirrors
        # refresh position/status, one belief message per agent is
        # published, and only due (non-partitioned, non-delayed) messages
        # update beliefs — all before detection/movement/dispatch. A
        # partitioned agent gets zero deliveries, so its
        # world_tick_at_read freezes behind the global tick. Wrapped so
        # comms never breaks the simulation; on a reliable network every
        # message delivers same-tick and behavior matches the baseline.
        if self.enable_comms:
            self._comms_ensure_agents()
            self._comms_publish(tick)
            self._comms_deliver(tick)
        self._detect_and_handle(tick)
        self._progress_services(tick)
        self.manager.advance_positions(tick, actor="engine")
        if self.enable_comms:
            # Belt-and-braces push (the patched _sync_agents inside
            # propose() repeats this deterministically).
            self._comms_sync_scheduler_beliefs(tick)
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
            # Comms state so a restore resumes deterministically.
            try:
                snapshot["gateway"] = self.gateway.to_dict()
            except Exception:
                snapshot["gateway"] = {}
            try:
                snapshot["network"] = self.network.to_dict()
            except Exception:
                snapshot["network"] = {}
            try:
                snapshot["comms_agents"] = {
                    aid: {
                        "kind": str(getattr(agent, "kind", "")),
                        "local_belief": copy.deepcopy(agent.local_belief),
                        "world_tick_at_read": int(
                            getattr(agent, "world_tick_at_read", 0) or 0
                        ),
                    }
                    for aid, agent in self.comms_agents.items()
                }
            except Exception:
                snapshot["comms_agents"] = {}
            try:
                snapshot["consumer_dedup"] = {
                    aid: dedup.to_dict()
                    for aid, dedup in self._consumer_dedup.items()
                }
            except Exception:
                snapshot["consumer_dedup"] = {}
            try:
                snapshot["partition_started"] = dict(self._partition_started)
            except Exception:
                snapshot["partition_started"] = {}
            snapshot["msg_seq"] = self._msg_seq
            try:
                snapshot["reconciliation_log"] = copy.deepcopy(
                    self.reconciliation_log
                )
            except Exception:
                snapshot["reconciliation_log"] = []
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
