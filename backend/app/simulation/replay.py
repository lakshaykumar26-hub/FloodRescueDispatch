"""Deterministic replay helper (Phase 6 Step 03).

Additive only: no change to :meth:`Simulation.step` ordering. Rebuilds a
run from the original scenario + seed + strategy and re-applies recorded
injections in ``(tick, event_id)`` order, so a fixed seed yields identical
event order and bid winners.

``simulation/`` must not import FastAPI, DB, or frontend code — this module
imports only the engine, world builders, and stdlib.
"""

from __future__ import annotations

import copy
from typing import Any

from ..dispatch.centralized_scheduler import CentralizedScheduler
from ..dispatch.negotiation_scheduler import NegotiationScheduler
from ..dispatch.scheduler_interface import Weights
from .engine import Simulation
from .run import build_simulation

# Scheduler factories mirror run.build_simulation (dispatch imports are
# allowed in simulation/; only FastAPI/DB/frontend are banned).
# Needed because from_snapshot always builds a centralized scheduler.

# Injection kinds applied straight to the network config (never through the
# tick scheduler, whose ``apply_event`` would log them IGNORED).
PARTITION_KINDS = frozenset({"PARTITION"})


def apply_partition(sim: Simulation, payload: dict) -> None:
    """Append a partition span to the simulated network (deduped).

    ``payload``: ``{agents: [...], from_tick: int, to_tick: int}``.
    Appending the same span twice is a no-op so snapshot-resume replays
    stay idempotent.
    """
    agents = list(payload.get("agents", []))
    span = {
        "agents": agents,
        "from_tick": int(payload.get("from_tick", 0)),
        "to_tick": int(payload.get("to_tick", 0)),
    }
    for existing in sim.network.partitions:
        if (
            existing.get("from_tick") == span["from_tick"]
            and existing.get("to_tick") == span["to_tick"]
            and sorted(existing.get("agents", [])) == sorted(span["agents"])
        ):
            return
    sim.network.partitions.append(span)


def apply_injection(
    sim: Simulation, kind: str, payload: dict, tick: int, event_id: str
) -> None:
    """Apply one recorded injection to ``sim`` (scheduler or network)."""
    if kind in PARTITION_KINDS:
        apply_partition(sim, payload)
        sim.manager._log(
            int(tick),
            "COMMS_NOTE",
            "replay",
            {"message": f"partition replay {event_id}", "event_id": event_id},
        )
        return
    sim.manager.scheduler.push(int(tick), str(kind), dict(payload), str(event_id))


def _scheduler_for(strategy: str, scenario_data: dict) -> Any:
    weights = Weights(**(scenario_data.get("weights", {}) or {}))
    if str(strategy) == "negotiation":
        return NegotiationScheduler(weights)
    return CentralizedScheduler(weights)


def replay_simulation(
    scenario_data: dict,
    seed: int,
    strategy: str,
    injections: list[dict],
    target_tick: int,
    from_snapshot: dict | None = None,
    snapshot_every: int = 10,
) -> Simulation:
    """Re-execute deterministically to ``target_tick``.

    Full path (``from_snapshot=None``): rebuild via ``build_simulation``
    from the original scenario + seed + strategy, push every recorded
    injection in ``(tick, event_id)`` order, then step to ``target_tick``.

    Snapshot path: restore via ``Simulation.from_snapshot`` and re-apply
    only injections scheduled after the snapshot tick (partition spans are
    deduped, so re-applying is safe), then step to ``target_tick``.
    """
    ordered = sorted(
        injections, key=lambda e: (int(e["tick"]), str(e["event_id"]))
    )
    if from_snapshot is not None:
        sim = Simulation.from_snapshot(
            copy.deepcopy(from_snapshot), snapshot_every=snapshot_every
        )
        # from_snapshot always builds a centralized scheduler: restore the
        # run's original strategy (fresh scheduler + engine belief patch).
        sim.scheduler = _scheduler_for(strategy, scenario_data)
        try:
            sim._comms_patch_scheduler()
        except Exception:  # noqa: BLE001, S110 — comms must never break replay
            pass
        snap_tick = int(from_snapshot.get("tick", 0))
        for entry in ordered:
            if int(entry["tick"]) <= snap_tick:
                continue
            apply_injection(
                sim,
                str(entry["kind"]),
                dict(entry.get("payload", {})),
                int(entry["tick"]),
                str(entry["event_id"]),
            )
        while sim.tick < int(target_tick):
            sim.step()
        return sim
    sim = build_simulation(
        copy.deepcopy(scenario_data),
        seed=int(seed),
        snapshot_every=snapshot_every,
        strategy=str(strategy),
    )
    for entry in ordered:
        apply_injection(
            sim,
            str(entry["kind"]),
            dict(entry.get("payload", {})),
            int(entry["tick"]),
            str(entry["event_id"]),
        )
    while sim.tick < int(target_tick):
        sim.step()
    return sim


def event_signature(sim: Simulation) -> list[tuple]:
    """Comparable event order signature: (tick, kind, stable detail key)."""
    sig: list[tuple] = []
    for entry in sim.manager.event_log:
        detail = entry.get("detail", {})
        key = (
            detail.get("proposal_id")
            or detail.get("assignment_id")
            or detail.get("incident_id")
            or detail.get("edge_id")
            or detail.get("boat_id")
            or detail.get("resource_id")
            or detail.get("event_id")
            or "",
        )
        sig.append((int(entry.get("tick", 0)), str(entry.get("kind")), key))
    return sig


def winners_signature(sim: Simulation) -> list[tuple]:
    """(proposal_id, assignment_id) pairs for every COMMITTED entry, in order."""
    out: list[tuple] = []
    for entry in sim.manager.event_log:
        if entry.get("kind") != "COMMITTED":
            continue
        detail = entry.get("detail", {})
        out.append(
            (str(detail.get("proposal_id", "")), str(detail.get("assignment_id", "")))
        )
    return out


__all__ = [
    "PARTITION_KINDS",
    "apply_injection",
    "apply_partition",
    "event_signature",
    "replay_simulation",
    "winners_signature",
]
