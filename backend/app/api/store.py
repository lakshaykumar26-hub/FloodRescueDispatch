"""In-memory simulation registry + thin service layer for the REST/WS API.

Handlers validate with ``schemas.api`` then call the helpers here, which in
turn call the engine/gateway — no scheduling logic lives in routes
(AGENTS.md hard rule 1, CONVENTIONS §6).

Entry shape: ``{id, simulation, scenario_name, scenario_data, strategy,
seed, max_ticks, status, started, injections, created_at, ...}``.
``status`` is one of ``created|running|paused|completed``; ``created_at``
is wall-clock (audit/display only). Ordering always uses integer ``tick``.
"""

from __future__ import annotations

import copy
import datetime as _dt
import itertools
import threading
from pathlib import Path
from typing import Any

from ..config import from_env
from ..schemas.api import CreateSimulationRequest
from ..simulation.engine import Simulation
from ..simulation.replay import apply_injection, replay_simulation
from ..simulation.run import build_simulation, load_scenario, summarize
from ..simulation.world import Incident


class ApiError(Exception):
    """Domain error with a machine-readable reason code."""

    def __init__(self, status: int, reason: str, message: str = "") -> None:
        super().__init__(message or reason)
        self.status = int(status)
        self.reason = str(reason)
        self.message = str(message or reason)


_lock = threading.Lock()
_store: dict[str, dict[str, Any]] = {}
_counter = itertools.count(1)

# Injection kinds accepted by POST /events. Aliases are normalized before
# they reach the scheduler.
SCHEDULER_KINDS = frozenset(
    {
        "CLOSURE",
        "BRIDGE_CLOSURE",
        "EDGE_REOPEN",
        "FLOOD_RISE",
        "INCIDENT_ARRIVAL",
        "BOAT_FAILURE",
        "SHELTER_FULL",
        "SHELTER_OVERFLOW",
        "REPORT",
        "COMMS_NOTE",
        "PARTITION",
    }
)

# SHELTER_OVERFLOW is the operator-facing alias of the engine SHELTER_FULL.
KIND_ALIASES = {"SHELTER_OVERFLOW": "SHELTER_FULL"}

# Assignment-audit kinds surfaced by GET /assignments (registry + history).
ASSIGNMENT_KINDS = frozenset(
    {
        "COMMITTED",
        "ACKNOWLEDGED",
        "IN_PROGRESS",
        "COMPLETED",
        "REJECTED",
        "EXPIRED",
        "CANCELLED",
        "REQUIRES_RECONCILIATION",
        "REPLAN_CHAIN",
        "REPLAN_FAILED",
        "REPLAN",
        "RECONCILED",
        "PROPOSED",
    }
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _resolve_scenario(req: CreateSimulationRequest) -> tuple[str, dict[str, Any]]:
    if isinstance(req.scenario, dict):
        data = copy.deepcopy(req.scenario)
        return str(data.get("scenario_name", "inline")), data
    name = (req.scenario_name or "baseline").strip() or "baseline"
    if isinstance(req.scenario, str) and req.scenario.strip():
        # Older dashboard builds sent the file name in `scenario` (string).
        name = req.scenario.strip()
    name = name.removesuffix(".json")
    if "/" in name or "\\" in name or ".." in name:
        raise ApiError(422, "UNKNOWN_SCENARIO", f"bad scenario name: {name!r}")
    path = _repo_root() / "scenarios" / f"{name}.json"
    if not path.exists():
        raise ApiError(422, "UNKNOWN_SCENARIO", f"no scenario file: {name}.json")
    return name, load_scenario(path)


def _now_iso() -> str:
    return _dt.datetime.now(_dt.UTC).isoformat()


# -- registry ----------------------------------------------------------


def create_entry(req: CreateSimulationRequest) -> dict[str, Any]:
    """Validate, build the engine simulation, register and persist it."""
    scenario_name, data = _resolve_scenario(req)
    if req.strategy not in ("centralized", "negotiation"):
        raise ApiError(422, "UNKNOWN_STRATEGY", f"strategy: {req.strategy!r}")
    seed = req.seed if req.seed is not None else int(data.get("random_seed", from_env().sim_seed))
    max_ticks = req.ticks if req.ticks is not None else int(data.get("ticks", 120))
    try:
        sim = build_simulation(
            copy.deepcopy(data), seed=seed, snapshot_every=from_env().snapshot_every, strategy=req.strategy
        )
    except ValueError as exc:
        raise ApiError(422, "BAD_SCENARIO", str(exc)) from exc
    with _lock:
        sim_id = f"SIM-{next(_counter):03d}"
        entry: dict[str, Any] = {
            "id": sim_id,
            "simulation": sim,
            "scenario_name": scenario_name,
            "scenario_data": copy.deepcopy(data),
            "strategy": req.strategy,
            "seed": int(seed),
            "max_ticks": int(max_ticks),
            "status": "created",
            "started": False,
            "injections": [],
            "created_at": _now_iso(),
            "persisted_log_len": 0,
            "inject_seq": 0,
        }
        _store[sim_id] = entry
    _persist_create(entry)
    return entry


def get_entry(sim_id: str) -> dict[str, Any]:
    with _lock:
        entry = _store.get(sim_id)
    if entry is None:
        raise ApiError(404, "UNKNOWN_SIMULATION", f"no such simulation: {sim_id!r}")
    return entry


def list_entries() -> list[dict[str, Any]]:
    with _lock:
        return list(_store.values())


def clear_entries() -> None:
    """Test-only reset of the registry (fresh SIM-xxx sequence)."""
    global _counter
    with _lock:
        _store.clear()
        _counter = itertools.count(1)


# -- lifecycle ---------------------------------------------------------


def start_entry(entry: dict[str, Any]) -> dict[str, Any]:
    if entry["status"] == "completed":
        raise ApiError(409, "SIM_COMPLETED", "simulation already completed")
    entry["status"] = "running"
    entry["started"] = True
    _persist_run(entry)
    return entry


def pause_entry(entry: dict[str, Any]) -> dict[str, Any]:
    if not entry["started"]:
        raise ApiError(409, "NOT_STARTED", "simulation never started")
    if entry["status"] == "completed":
        raise ApiError(409, "SIM_COMPLETED", "simulation already completed")
    entry["status"] = "paused"
    _persist_run(entry)
    return entry


def step_entry(entry: dict[str, Any], steps: int = 1) -> dict[str, Any]:
    if not entry["started"]:
        raise ApiError(409, "NOT_STARTED", "call start before step")
    if entry["status"] == "completed":
        raise ApiError(409, "SIM_COMPLETED", "simulation already completed")
    if steps < 1:
        raise ApiError(422, "BAD_STEPS", "steps must be >= 1")
    sim: Simulation = entry["simulation"]
    taken = 0
    for _ in range(int(steps)):
        if sim.tick >= int(entry["max_ticks"]):
            break
        sim.step()
        taken += 1
    if sim.tick >= int(entry["max_ticks"]):
        entry["status"] = "completed"
    _persist_after_step(entry)
    return {"tick": sim.tick, "status": entry["status"], "steps_taken": taken}


# -- inject ------------------------------------------------------------


def _require_edge(sim: Simulation, edge_id: Any) -> str:
    if not isinstance(edge_id, str) or edge_id not in sim.world.edges:
        raise ApiError(422, "UNKNOWN_EDGE", f"unknown edge: {edge_id!r}")
    return edge_id


def inject_event(
    entry: dict[str, Any],
    kind: str,
    payload: dict[str, Any] | None,
    event_id: str | None = None,
    tick: int | None = None,
) -> dict[str, Any]:
    """Validate an operator injection and schedule it on the simulation."""
    sim: Simulation = entry["simulation"]
    raw_kind = str(kind or "").upper()
    if raw_kind not in SCHEDULER_KINDS:
        raise ApiError(422, "UNKNOWN_KIND", f"unknown inject kind: {kind!r}")
    norm_kind = KIND_ALIASES.get(raw_kind, raw_kind)
    data = dict(payload or {})
    sched_tick = int(tick) if tick is not None else sim.tick + 1
    if sched_tick < sim.tick:
        raise ApiError(
            422, "STALE_TICK", f"inject tick {sched_tick} is behind sim tick {sim.tick}"
        )

    if norm_kind in ("CLOSURE", "BRIDGE_CLOSURE", "EDGE_REOPEN"):
        _require_edge(sim, data.get("edge_id"))
    elif norm_kind == "BOAT_FAILURE":
        boat_id = data.get("boat_id")
        if not isinstance(boat_id, str) or boat_id not in sim.world.boats:
            raise ApiError(422, "UNKNOWN_BOAT", f"unknown boat: {boat_id!r}")
    elif norm_kind == "SHELTER_FULL":
        shelter_id = data.get("shelter_id")
        if not isinstance(shelter_id, str) or shelter_id not in sim.world.shelters:
            raise ApiError(422, "UNKNOWN_SHELTER", f"unknown shelter: {shelter_id!r}")
    elif norm_kind == "INCIDENT_ARRIVAL":
        _validate_incident_payload(sim, data)
    elif norm_kind == "FLOOD_RISE":
        edge_ids = data.get("edge_ids")
        if not isinstance(edge_ids, list) or not edge_ids:
            raise ApiError(422, "BAD_PAYLOAD", "FLOOD_RISE needs edge_ids + risk_delta")
        for eid in edge_ids:
            _require_edge(sim, eid)
        if not isinstance(data.get("risk_delta"), (int, float)):
            raise ApiError(422, "BAD_PAYLOAD", "FLOOD_RISE needs numeric risk_delta")
    elif norm_kind == "REPORT":
        claim = data.get("claim") if isinstance(data.get("claim"), dict) else data
        if not isinstance(claim, dict) or "subject_id" not in claim:
            raise ApiError(422, "BAD_PAYLOAD", "REPORT needs a claim with subject_id")
    elif norm_kind == "COMMS_NOTE":
        if not isinstance(data.get("message"), str):
            raise ApiError(422, "BAD_PAYLOAD", "COMMS_NOTE needs a message string")
    elif norm_kind == "PARTITION":
        agents = data.get("agents")
        if not isinstance(agents, list) or not agents:
            raise ApiError(422, "BAD_PAYLOAD", "PARTITION needs agents + ticks")
        try:
            from_tick = int(data.get("from_tick", sim.tick))
            to_tick = int(data.get("to_tick", from_tick))
        except (TypeError, ValueError):
            raise ApiError(422, "BAD_PAYLOAD", "PARTITION ticks must be ints") from None
        if from_tick > to_tick:
            raise ApiError(422, "BAD_PAYLOAD", "PARTITION from_tick > to_tick")
        data = {"agents": list(agents), "from_tick": from_tick, "to_tick": to_tick}

    entry["inject_seq"] = int(entry.get("inject_seq", 0)) + 1
    eid = event_id or f"EVT-INJECT-{entry['inject_seq']:04d}"
    record = {
        "tick": int(sched_tick),
        "kind": norm_kind,
        "payload": copy.deepcopy(data),
        "event_id": str(eid),
    }
    # Partition spans apply to the live network now (absolute tick bounds,
    # so immediate application == replay application); everything else rides
    # the deterministic tick scheduler and fires before movement that tick.
    apply_injection(sim, norm_kind, data, int(sched_tick), str(eid))
    entry["injections"].append(record)
    _persist_inject(entry, record)
    return {
        "tick": sim.tick,
        "event_id": str(eid),
        "kind": norm_kind,
        "scheduled_tick": int(sched_tick),
    }


def _validate_incident_payload(sim: Simulation, data: dict[str, Any]) -> None:
    for key in ("incident_id", "node_id"):
        if key not in data:
            raise ApiError(422, "BAD_PAYLOAD", f"INCIDENT_ARRIVAL needs {key}")
    if data["incident_id"] in sim.world.incidents:
        raise ApiError(
            422, "DUPLICATE_INCIDENT", f"incident exists: {data['incident_id']!r}"
        )
    if data["node_id"] not in sim.world.nodes:
        raise ApiError(422, "UNKNOWN_NODE", f"unknown node: {data['node_id']!r}")
    record = dict(data)
    record.setdefault("created_tick", sim.tick + 1)
    try:
        Incident.model_validate(record)
    except Exception as exc:
        raise ApiError(422, "BAD_PAYLOAD", f"bad incident payload: {exc}") from exc


# -- views -------------------------------------------------------------


def state_view(entry: dict[str, Any]) -> dict[str, Any]:
    sim: Simulation = entry["simulation"]
    return {
        "simulation_id": entry["id"],
        "tick": sim.tick,
        "status": entry["status"],
        "world": sim.world.to_dict(),
        "snapshots": sorted(sim.snapshots),
    }


def events_view(
    entry: dict[str, Any], since_tick: int = 0, kind: str | None = None
) -> dict[str, Any]:
    sim: Simulation = entry["simulation"]
    events = [
        e
        for e in sim.manager.event_log
        if int(e.get("tick", 0)) >= int(since_tick)
        and (kind is None or e.get("kind") == kind)
    ]
    return {
        "simulation_id": entry["id"],
        "tick": sim.tick,
        "count": len(events),
        "events": copy.deepcopy(events),
    }


def assignments_view(entry: dict[str, Any]) -> dict[str, Any]:
    sim: Simulation = entry["simulation"]
    assignments = [
        a.model_dump() for _, a in sorted(sim.assignments.items())
    ]
    history = [
        e
        for e in sim.manager.event_log
        if e.get("kind") in ASSIGNMENT_KINDS
    ]
    return {
        "simulation_id": entry["id"],
        "tick": sim.tick,
        "assignments": copy.deepcopy(assignments),
        "history": copy.deepcopy(history),
    }


def incidents_view(entry: dict[str, Any]) -> dict[str, Any]:
    sim: Simulation = entry["simulation"]
    return {
        "simulation_id": entry["id"],
        "tick": sim.tick,
        "incidents": [i.model_dump() for _, i in sorted(sim.world.incidents.items())],
    }


def metrics_view(entry: dict[str, Any]) -> dict[str, Any]:
    """Computed from recorded data only (reuses ``run.summarize``)."""
    sim: Simulation = entry["simulation"]
    summary = summarize(sim)
    _persist_metrics(entry, summary)
    return {
        "simulation_id": entry["id"],
        "tick": sim.tick,
        "strategy": summary["strategy"],
        "served": summary["served"],
        "unserved": summary["unserved"],
        "committed": summary["committed"],
        "rejected_by_reason": summary["rejected_by_reason"],
        "snapshots": summary["snapshots"],
    }


def comms_view(entry: dict[str, Any]) -> dict[str, Any]:
    sim: Simulation = entry["simulation"]
    gateway = sim.gateway
    by_status: dict[str, int] = {}
    messages: list[dict[str, Any]] = []
    for mid, stored in sorted(gateway.store.items()):
        status = gateway.tracker.status_of(mid) or "UNKNOWN"
        by_status[status] = by_status.get(status, 0) + 1
        msg = stored.get("message", {})
        messages.append(
            {
                "message_id": mid,
                "type": msg.get("type"),
                "sender_id": msg.get("sender_id"),
                "recipient_id": msg.get("recipient_id"),
                "created_at_tick": msg.get("created_at_tick"),
                "expires_at_tick": msg.get("expires_at_tick"),
                "status": status,
            }
        )
    belief_ticks = {}
    for aid in sorted(sim.comms_agents):
        try:
            belief_ticks[aid] = int(
                getattr(sim.comms_agents[aid], "world_tick_at_read", 0) or 0
            )
        except (TypeError, ValueError):
            belief_ticks[aid] = 0
    return {
        "simulation_id": entry["id"],
        "tick": sim.tick,
        "queued": len(gateway.queue),
        "total_messages": len(gateway.store),
        "by_status": by_status,
        "messages": messages[-200:],
        "reconciliation_log": copy.deepcopy(sim.reconciliation_log),
        "partitions_active": sim.network.partitions_at(sim.tick),
        "partitions_started": dict(sim._partition_started),
        "belief_ticks": belief_ticks,
    }


# -- replay ------------------------------------------------------------


def replay_entry(
    entry: dict[str, Any], from_snapshot_tick: int | None = None
) -> dict[str, Any]:
    sim: Simulation = entry["simulation"]
    target = sim.tick
    snapshot = None
    if from_snapshot_tick is not None:
        snapshot = sim.snapshots.get(int(from_snapshot_tick))
        if snapshot is None:
            raise ApiError(
                404,
                "UNKNOWN_SNAPSHOT",
                f"no snapshot at tick {from_snapshot_tick}",
            )
    fresh = replay_simulation(
        entry["scenario_data"],
        int(entry["seed"]),
        str(entry["strategy"]),
        list(entry["injections"]),
        int(target),
        from_snapshot=snapshot,
    )
    summary = summarize(fresh)
    summary["tick"] = fresh.tick
    return {
        "simulation_id": entry["id"],
        "tick": fresh.tick,
        "from_tick": from_snapshot_tick,
        "summary": summary,
    }


# -- persistence hooks (best-effort; never break the sim) --------------


def _db() -> Any | None:
    try:
        from ..persistence import database as _database

        return _database.get_shared()
    except Exception:  # noqa: BLE001 — persistence is best-effort
        return None


def _persist_create(entry: dict[str, Any]) -> None:
    try:
        from ..persistence import repositories as _repos

        db = _db()
        if db is None:
            return
        _repos.save_run(
            db,
            entry["id"],
            entry["scenario_name"],
            entry["strategy"],
            entry["seed"],
            entry["status"],
            entry["simulation"].tick,
            entry["max_ticks"],
        )
    except Exception:  # noqa: BLE001, S110 — best-effort; never break the sim
        pass


def _persist_run(entry: dict[str, Any]) -> None:
    _persist_create(entry)


def _persist_after_step(entry: dict[str, Any]) -> None:
    try:
        from ..persistence import repositories as _repos

        db = _db()
        if db is None:
            return
        sim: Simulation = entry["simulation"]
        _repos.save_run(
            db,
            entry["id"],
            entry["scenario_name"],
            entry["strategy"],
            entry["seed"],
            entry["status"],
            sim.tick,
            entry["max_ticks"],
        )
        for tick, snapshot in sorted(sim.snapshots.items()):
            _repos.save_snapshot(db, entry["id"], int(tick), snapshot)
        new_log = sim.manager.event_log[int(entry.get("persisted_log_len", 0)) :]
        _repos.save_events_batch(db, entry["id"], new_log)
        _repos.sync_assignments(db, entry["id"], sim.tick, sim.assignments, new_log)
        _repos.sync_messages(db, entry["id"], sim.tick, sim.gateway)
        entry["persisted_log_len"] = len(sim.manager.event_log)
    except Exception:  # noqa: BLE001, S110 — best-effort; never break the sim
        pass


def _persist_inject(entry: dict[str, Any], record: dict[str, Any]) -> None:
    try:
        from ..persistence import repositories as _repos

        db = _db()
        if db is None:
            return
        _repos.save_events_batch(
            db,
            entry["id"],
            [
                {
                    "tick": record["tick"],
                    "kind": "INJECT_SCHEDULED",
                    "actor": "api",
                    "detail": {
                        "event_id": record["event_id"],
                        "kind": record["kind"],
                        "payload": record["payload"],
                    },
                }
            ],
        )
    except Exception:  # noqa: BLE001, S110 — best-effort; never break the sim
        pass


def _persist_metrics(entry: dict[str, Any], summary: dict[str, Any]) -> None:
    try:
        from ..persistence import repositories as _repos

        db = _db()
        if db is None:
            return
        _repos.save_metrics(db, entry["id"], entry["simulation"].tick, summary)
    except Exception:  # noqa: BLE001, S110 — best-effort; never break the sim
        pass


__all__ = [
    "ASSIGNMENT_KINDS",
    "SCHEDULER_KINDS",
    "ApiError",
    "assignments_view",
    "clear_entries",
    "comms_view",
    "create_entry",
    "events_view",
    "get_entry",
    "incidents_view",
    "inject_event",
    "list_entries",
    "metrics_view",
    "pause_entry",
    "replay_entry",
    "start_entry",
    "state_view",
    "step_entry",
]
