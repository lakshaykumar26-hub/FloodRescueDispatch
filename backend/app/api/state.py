"""GET state: world snapshot + tick + status + snapshots available."""

from __future__ import annotations

from fastapi import APIRouter

from ..schemas.api import StateResponse
from . import store

router = APIRouter()


@router.get("/api/simulations/{sim_id}/state", response_model=StateResponse)
def get_state(sim_id: str) -> dict:
    return store.state_view(store.get_entry(sim_id))
