"""Pydantic v2 request/response models for the Phase 6 REST API.

Only pydantic + stdlib. Handlers validate with these, then delegate to
the engine/gateway via ``api.store`` (thin-handler rule).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Strategy = Literal["centralized", "negotiation"]
SimStatus = Literal["created", "running", "paused", "completed"]


class CreateSimulationRequest(BaseModel):
    scenario_name: str = "baseline"
    # Inline scenario document (dict) — or, for robustness against older
    # dashboard builds, a scenario file name as a plain string, which is
    # coerced to ``scenario_name`` by ``api.store._resolve_scenario``.
    scenario: dict[str, Any] | str | None = None
    strategy: Strategy = "centralized"
    seed: int | None = None
    ticks: int | None = Field(default=None, ge=1, le=1000)


class CreateSimulationResponse(BaseModel):
    simulation_id: str
    scenario_name: str
    strategy: str
    seed: int
    max_ticks: int
    tick: int
    status: str


class StepRequest(BaseModel):
    steps: int = Field(default=1, ge=1, le=500)


class StepResponse(BaseModel):
    simulation_id: str
    tick: int
    status: str
    steps_taken: int


class StateResponse(BaseModel):
    simulation_id: str
    tick: int
    status: str
    world: dict[str, Any]
    snapshots: list[int]


class EventsResponse(BaseModel):
    simulation_id: str
    tick: int
    count: int
    events: list[dict[str, Any]]


class AssignmentsResponse(BaseModel):
    simulation_id: str
    tick: int
    assignments: list[dict[str, Any]]
    history: list[dict[str, Any]]


class IncidentsResponse(BaseModel):
    simulation_id: str
    tick: int
    incidents: list[dict[str, Any]]


class MetricsResponse(BaseModel):
    simulation_id: str
    tick: int
    strategy: str
    served: int
    unserved: int
    committed: int
    rejected_by_reason: dict[str, int]
    snapshots: list[int]


class CommsResponse(BaseModel):
    simulation_id: str
    tick: int
    queued: int
    total_messages: int
    by_status: dict[str, int]
    messages: list[dict[str, Any]]
    reconciliation_log: list[dict[str, Any]]
    partitions_active: list[dict[str, Any]]
    partitions_started: dict[str, int]
    belief_ticks: dict[str, int]


class InjectRequest(BaseModel):
    kind: str
    payload: dict[str, Any] = Field(default_factory=dict)
    event_id: str | None = None
    tick: int | None = Field(default=None, ge=0)


class InjectResponse(BaseModel):
    simulation_id: str
    tick: int
    event_id: str
    kind: str
    scheduled_tick: int


class ReplayRequest(BaseModel):
    from_snapshot_tick: int | None = Field(default=None, ge=0)


class ReplayResponse(BaseModel):
    simulation_id: str
    tick: int
    from_tick: int | None
    summary: dict[str, Any]


class ErrorResponse(BaseModel):
    reason: str
    message: str = ""
