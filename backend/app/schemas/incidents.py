"""Incident API schemas (thin wrappers over simulation world models)."""

from pydantic import BaseModel, Field

from ..simulation.world import Incident


class IncidentCreate(BaseModel):
    node_id: str
    urgency: int = Field(ge=1, le=5)
    people: int = Field(ge=1)
    required_capabilities: list[str] = Field(default_factory=list)
    report_confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class IncidentRead(Incident):
    pass
