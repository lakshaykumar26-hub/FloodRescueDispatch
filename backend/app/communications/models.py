"""Validated message envelopes (spec section 8). Only pydantic + stdlib."""

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

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

_REQUIRED_PAYLOAD_KEYS: dict[str, tuple[str, ...]] = {
    "ASSIGNMENT_OFFER": ("assignment_id", "incident_id"),
    "ASSIGNMENT_ACCEPTED": ("assignment_id",),
    "ASSIGNMENT_CANCELLED": ("assignment_id", "reason"),
    "MESSAGE_ACK": ("ack_of", "status"),
}


class Message(BaseModel):
    message_id: str
    type: MessageType
    sender_id: str
    recipient_id: str
    simulation_id: str = "SIM-001"
    created_at_tick: int = Field(ge=0)
    expires_at_tick: int = Field(ge=0)
    version: int = Field(ge=0)
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_expiry_and_payload(self) -> "Message":
        if self.expires_at_tick < self.created_at_tick:
            raise ValueError("expires_at_tick must be >= created_at_tick")
        required = _REQUIRED_PAYLOAD_KEYS.get(self.type, ())
        missing = [k for k in required if k not in self.payload]
        if missing:
            raise ValueError(f"type {self.type} payload missing keys: {missing}")
        return self


def validate_message(msg: Message, tick: int) -> tuple[bool, str]:
    """Check tick-based expiry. Returns (False, "EXPIRED") if tick > expires."""
    if tick > msg.expires_at_tick:
        return (False, "EXPIRED")
    return (True, "OK")


def validate_known(msg: Message, known_ids: set[str]) -> tuple[bool, str]:
    """Check ACK reference. Non-ACK messages pass; unknown ack_of is rejected."""
    if msg.type != "MESSAGE_ACK":
        return (True, "OK")
    ack_of = msg.payload.get("ack_of")
    if ack_of not in known_ids:
        return (False, "ACK_UNKNOWN_REFERENCE")
    return (True, "OK")
