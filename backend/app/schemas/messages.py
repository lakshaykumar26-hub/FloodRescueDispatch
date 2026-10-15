"""Message envelope stub per CONVENTIONS section 5. TODO(P5): gateway completes this."""

from typing import Literal

from pydantic import BaseModel, Field

MessageType = Literal[
    "INCIDENT_CREATED",
    "ASSIGNMENT_OFFER",
    "ASSIGNMENT_ACCEPTED",
    "ASSIGNMENT_CANCELLED",
    "BOAT_POSITION",
    "BOAT_STATUS_CHANGED",
    "HAZARD_REPORTED",
    "SHELTER_CAPACITY_CHANGED",
    "MESSAGE_ACK",
]


class Message(BaseModel):
    # TODO(P5): delivery tracking, retry/dedup/expiry/reconcile live in
    # communications/gateway.py; this envelope is validation only.
    message_id: str
    type: MessageType
    sender_id: str
    recipient_id: str
    simulation_id: str
    created_at_tick: int = Field(ge=0)
    expires_at_tick: int = Field(ge=0)
    version: int = Field(default=1, ge=1)
    payload: dict = Field(default_factory=dict)
