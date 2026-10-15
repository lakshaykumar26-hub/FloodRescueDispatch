"""GET events (filtered) + POST events (operator injection)."""

from __future__ import annotations

from fastapi import APIRouter

from ..schemas.api import EventsResponse, InjectRequest, InjectResponse
from . import store

router = APIRouter()


@router.get("/api/simulations/{sim_id}/events", response_model=EventsResponse)
def get_events(sim_id: str, since_tick: int = 0, kind: str | None = None) -> dict:
    return store.events_view(store.get_entry(sim_id), since_tick, kind)


@router.post("/api/simulations/{sim_id}/events", response_model=InjectResponse)
def inject(sim_id: str, req: InjectRequest) -> dict:
    out = store.inject_event(
        store.get_entry(sim_id), req.kind, req.payload, req.event_id, req.tick
    )
    return {
        "simulation_id": sim_id,
        "tick": out["tick"],
        "event_id": out["event_id"],
        "kind": out["kind"],
        "scheduled_tick": out["scheduled_tick"],
    }
