"""GET communications: queue/outbox digest + reconciliation + partitions."""

from __future__ import annotations

from fastapi import APIRouter

from ..schemas.api import CommsResponse
from . import store

router = APIRouter()


@router.get(
    "/api/simulations/{sim_id}/communications", response_model=CommsResponse
)
def get_communications(sim_id: str) -> dict:
    return store.comms_view(store.get_entry(sim_id))
