"""GET metrics: recorded-data-only summary (reuses run.summarize)."""

from __future__ import annotations

from fastapi import APIRouter

from ..schemas.api import MetricsResponse
from . import store

router = APIRouter()


@router.get("/api/simulations/{sim_id}/metrics", response_model=MetricsResponse)
def get_metrics(sim_id: str) -> dict:
    return store.metrics_view(store.get_entry(sim_id))
