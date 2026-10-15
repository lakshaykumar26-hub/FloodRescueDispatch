"""GET assignments: registry + dispatch history (COMMITTED/REJECTED/...)."""

from __future__ import annotations

from fastapi import APIRouter

from ..schemas.api import AssignmentsResponse
from . import store

router = APIRouter()


@router.get(
    "/api/simulations/{sim_id}/assignments", response_model=AssignmentsResponse
)
def get_assignments(sim_id: str) -> dict:
    return store.assignments_view(store.get_entry(sim_id))
