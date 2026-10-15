"""Incident agent: publishes rescue requests from its own reported state.

The request carries only the incident's own fields; routing, bidding, and
safety decisions happen elsewhere (resource agents / scheduler).
"""

from .base_agent import BaseAgent


class IncidentAgent(BaseAgent):
    """Owns reported location, urgency, demand, and required capabilities."""

    kind = "incident"

    def __init__(
        self,
        agent_id: str,
        node_id: str,
        urgency: int,
        people: int,
        capabilities: list,
        created_tick: int,
    ) -> None:
        super().__init__(agent_id)
        self.node_id = node_id
        self.urgency = urgency
        self.people = people
        self.capabilities = list(capabilities)
        self.created_tick = created_tick

    def publish_request(self) -> dict:
        """Return the rescue-request dict resource agents bid on.

        Exact keys (nothing else): ``incident_id, node_id, urgency, people,
        capabilities, created_tick``.
        """
        return {
            "incident_id": self.id,
            "node_id": self.node_id,
            "urgency": self.urgency,
            "people": self.people,
            "capabilities": list(self.capabilities),
            "created_tick": self.created_tick,
        }
