"""Scheduler contract: pure decision-makers; mutation only via commitment_manager + state_manager after safety validation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, Optional, Protocol, runtime_checkable

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from ..simulation.world import World


def rank_key(urgency: int, waiting_ticks: int, people: int, incident_id: str) -> tuple:
    """Return a sort key so ascending order yields rank order.

    Higher ``urgency`` first, then longer ``waiting_ticks``, then more
    ``people``, then ``incident_id`` ascending as a deterministic tiebreak.
    Negating the numeric fields lets callers use plain ``sorted(...)``.
    """
    return (-urgency, -waiting_ticks, -people, incident_id)


class ProposedAssignment(BaseModel):
    proposal_id: str
    incident_id: str
    resource_id: str
    resource_kind: Literal["boat", "team"]
    shelter_id: Optional[str] = None
    seats: int
    route_edge_ids: list[str]
    shelter_route_edge_ids: list[str] = Field(default_factory=list)
    eta_ticks: int
    shelter_eta_ticks: int = 0
    cost: float
    reasons: list[str] = Field(default_factory=list)
    created_tick: int


ASSIGNMENT_STATUSES: tuple[str, ...] = (
    "PROPOSED",
    "COMMITTED",
    "ACKNOWLEDGED",
    "IN_PROGRESS",
    "COMPLETED",
    "REJECTED",
    "EXPIRED",
    "CANCELLED",
    "REQUIRES_RECONCILIATION",
)


class Assignment(BaseModel):
    assignment_id: str
    version: int = 1
    proposal_id: str
    incident_id: str
    resource_id: str
    resource_kind: Literal["boat", "team"]
    shelter_id: Optional[str] = None
    seats: int
    route_edge_ids: list[str]
    status: Literal[
        "PROPOSED",
        "COMMITTED",
        "ACKNOWLEDGED",
        "IN_PROGRESS",
        "COMPLETED",
        "REJECTED",
        "EXPIRED",
        "CANCELLED",
        "REQUIRES_RECONCILIATION",
    ]
    cost: float = 0.0
    created_tick: int
    history: list[dict] = Field(default_factory=list)


class Weights(BaseModel):
    w_t: float = 1.0
    w_r: float = 2.0
    w_f: float = 0.5
    w_o: float = 0.3


DEFAULT_WEIGHTS = Weights()


@runtime_checkable
class Scheduler(Protocol):
    """Strategy-agnostic dispatch contract (centralized now, negotiation later)."""

    strategy: str

    def propose(self, world: World, tick: int) -> list[ProposedAssignment]:
        """Rank incidents and return feasible proposals; never mutate the world."""
        ...

    def commit(
        self,
        world: World,
        proposal: ProposedAssignment,
        tick: int,
        *,
        manager: Any,
        assignments: dict,
        proposals_seen: dict,
    ) -> tuple[Assignment | None, str]:
        """Thin wrapper around commitment_manager; engine passes state_manager + registries."""
        ...
