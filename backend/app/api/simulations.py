"""Simulation lifecycle + replay endpoints and the live WebSocket."""

from __future__ import annotations

import copy

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..schemas.api import (
    CreateSimulationRequest,
    CreateSimulationResponse,
    InjectRequest,
    ReplayRequest,
    ReplayResponse,
    StepRequest,
    StepResponse,
)
from . import store
from .store import ApiError

router = APIRouter()


@router.post("/api/simulations", response_model=CreateSimulationResponse)
def create_simulation(req: CreateSimulationRequest) -> dict:
    entry = store.create_entry(req)
    return {
        "simulation_id": entry["id"],
        "scenario_name": entry["scenario_name"],
        "strategy": entry["strategy"],
        "seed": entry["seed"],
        "max_ticks": entry["max_ticks"],
        "tick": entry["simulation"].tick,
        "status": entry["status"],
    }


@router.post("/api/simulations/{sim_id}/start")
def start_simulation(sim_id: str) -> dict:
    entry = store.get_entry(sim_id)
    store.start_entry(entry)
    return {
        "simulation_id": sim_id,
        "tick": entry["simulation"].tick,
        "status": entry["status"],
    }


@router.post("/api/simulations/{sim_id}/pause")
def pause_simulation(sim_id: str) -> dict:
    entry = store.get_entry(sim_id)
    store.pause_entry(entry)
    return {
        "simulation_id": sim_id,
        "tick": entry["simulation"].tick,
        "status": entry["status"],
    }


@router.post("/api/simulations/{sim_id}/step", response_model=StepResponse)
def step_simulation(sim_id: str, req: StepRequest) -> dict:
    entry = store.get_entry(sim_id)
    out = store.step_entry(entry, req.steps)
    return {
        "simulation_id": sim_id,
        "tick": out["tick"],
        "status": out["status"],
        "steps_taken": out["steps_taken"],
    }


@router.post("/api/simulations/{sim_id}/replay", response_model=ReplayResponse)
def replay_simulation(sim_id: str, req: ReplayRequest) -> dict:
    entry = store.get_entry(sim_id)
    return store.replay_entry(entry, req.from_snapshot_tick)


# -- WebSocket live view ----------------------------------------------


def _ws_frame(entry: dict, events_since: int) -> dict:
    sim = entry["simulation"]
    new_events = sim.manager.event_log[events_since:]
    digest = {
        "tick": sim.tick,
        "status": entry["status"],
        "incidents": {
            iid: inc.status for iid, inc in sorted(sim.world.incidents.items())
        },
        "active_assignments": sum(
            1
            for a in sim.assignments.values()
            if a.status in ("COMMITTED", "ACKNOWLEDGED", "IN_PROGRESS")
        ),
        "total_assignments": len(sim.assignments),
    }
    return {
        "tick": sim.tick,
        "state_digest": digest,
        "events": copy.deepcopy(new_events),
        "assignments_delta": {
            aid: a.status for aid, a in sorted(sim.assignments.items())
        },
        "comms_digest": {
            "queued": len(sim.gateway.queue),
            "total_messages": len(sim.gateway.store),
            "reconciliations": len(sim.reconciliation_log),
        },
    }


@router.websocket("/ws/simulations/{sim_id}")
async def ws_simulation(websocket: WebSocket, sim_id: str) -> None:
    await websocket.accept()
    try:
        entry = store.get_entry(sim_id)
    except ApiError as exc:
        await websocket.send_json({"reason": exc.reason, "message": exc.message})
        await websocket.close()
        return
    sim = entry["simulation"]
    events_since = len(sim.manager.event_log)
    await websocket.send_json(_ws_frame(entry, events_since))
    events_since = len(sim.manager.event_log)
    while True:
        try:
            msg = await websocket.receive_json()
        except WebSocketDisconnect:
            break
        except Exception:  # noqa: BLE001 — malformed frame ends the stream
            break
        action = str((msg or {}).get("action", "")).lower()
        try:
            if action == "pause":
                store.pause_entry(entry)
            elif action == "step":
                steps = int((msg or {}).get("steps", 1) or 1)
                store.step_entry(entry, max(1, steps))
            elif action == "inject":
                store.inject_event(
                    entry,
                    str((msg or {}).get("kind", "")),
                    dict((msg or {}).get("payload", {}) or {}),
                    (msg or {}).get("event_id"),
                    (msg or {}).get("tick"),
                )
            else:
                await websocket.send_json(
                    {"reason": "UNKNOWN_ACTION", "message": f"action: {action!r}"}
                )
                continue
        except ApiError as exc:
            await websocket.send_json(
                {"reason": exc.reason, "message": exc.message, "tick": sim.tick}
            )
            continue
        except Exception as exc:  # noqa: BLE001 — never drop the socket on a bad step
            await websocket.send_json(
                {"reason": "STEP_FAILED", "message": str(exc), "tick": sim.tick}
            )
            continue
        await websocket.send_json(_ws_frame(entry, events_since))
        events_since = len(sim.manager.event_log)


# Re-export for tests that import the inject schemas via this module.
__all__ = ["InjectRequest", "router"]
