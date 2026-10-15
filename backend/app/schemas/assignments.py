"""Assignment stub. TODO(P2): full lifecycle, owner, history (dispatch phase)."""

from typing import Literal

from pydantic import BaseModel, Field

AssignmentStatus = Literal[
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


class Assignment(BaseModel):
    # TODO(P2): extend with resource/incident/destination IDs, version checks,
    # owner, and append-only history with reason + tick + actor.
    assignment_id: str
    version: int = Field(default=1, ge=1)
    status: AssignmentStatus = "PROPOSED"
