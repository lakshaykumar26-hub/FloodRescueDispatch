"""GET incidents: world incident registry at the current tick."""

from __future__ import annotations

from fastapi import APIRouter

from ..schemas.api import IncidentsResponse
from . import store

router = APIRouter()


@router.get("/api/simulations/{sim_id}/incidents", response_model=IncidentsResponse)
def get_incidents(sim_id: str) -> dict:
    return store.incidents_view(store.get_entry(sim_id))
