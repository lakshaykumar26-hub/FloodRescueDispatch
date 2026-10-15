"""World models: single source of truth for simulation entities.

Must not import FastAPI, SQLAlchemy, DB, or frontend code (AGENTS.md hard rule 1).
Deterministic ordering uses integer ``tick``; wall-clock timestamps are
audit/display only.
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field

NodeKind = Literal["intersection", "incident_site", "shelter", "station", "transfer"]
EdgeMode = Literal["road", "water"]
EdgeStatus = Literal["open", "closed", "disputed"]
IncidentStatus = Literal["OPEN", "ASSIGNED", "IN_PROGRESS", "SERVED", "CANCELLED", "UNRESOLVED"]
BoatStatus = Literal[
    "AVAILABLE",
    "ASSIGNED",
    "EN_ROUTE_TO_INCIDENT",
    "RESCUING",
    "TRANSPORTING_TO_SHELTER",
    "RECOVERY",
    "UNAVAILABLE",
    "FAILED",
    "STRANDED",
    "RETURNING",
    "MAINTENANCE",
]
GroundTeamStatus = Literal["AVAILABLE", "ASSIGNED", "ON_SCENE", "RETURNING", "UNAVAILABLE"]


class Node(BaseModel):
    node_id: str
    neighborhood: str
    kind: NodeKind
    x: float
    y: float


class Edge(BaseModel):
    edge_id: str
    from_node: str
    to_node: str
    mode: EdgeMode
    travel_time: int = Field(ge=1)
    status: EdgeStatus
    risk_level: float = Field(ge=0.0, le=1.0)
    capacity: int = Field(gt=0)
    last_updated_tick: int = Field(default=0, ge=0)


class Incident(BaseModel):
    incident_id: str
    node_id: str
    urgency: int = Field(ge=1, le=5)
    people: int = Field(ge=1)
    required_capabilities: list[str] = Field(default_factory=list)
    created_tick: int = Field(default=0, ge=0)
    status: IncidentStatus = "OPEN"
    report_confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class Boat(BaseModel):
    boat_id: str
    node_id: str
    capacity: int = Field(gt=0)
    fuel: float = Field(ge=0.0)
    fuel_reserve: float = Field(ge=0.0)
    speed: float = Field(default=1.0, gt=0.0)
    status: BoatStatus = "AVAILABLE"
    assignment_id: Optional[str] = None
    passengers: int = Field(default=0, ge=0)
    needs_recovery: bool = False
    history: list[dict] = Field(default_factory=list)


class GroundTeam(BaseModel):
    team_id: str
    node_id: str
    capabilities: list[str] = Field(default_factory=list)
    status: GroundTeamStatus = "AVAILABLE"
    assignment_id: Optional[str] = None
    history: list[dict] = Field(default_factory=list)


class Shelter(BaseModel):
    shelter_id: str
    node_id: str
    capacity: int = Field(gt=0)
    occupancy: int = Field(default=0, ge=0)
    reservations: dict[str, int] = Field(default_factory=dict)
    history: list[dict] = Field(default_factory=list)

    def remaining(self) -> int:
        """Seats left: capacity - occupancy - sum(reservations). May be negative."""
        return self.capacity - self.occupancy - sum(self.reservations.values())

    def reserve(self, assignment_id: str, seats: int, tick: int = 0) -> bool:
        """Promise ``seats`` to ``assignment_id`` unless it would overbook.

        Returns True and records the reservation on success; returns False
        (no mutation) when seats <= 0 or occupancy + reservations + seats
        would exceed capacity. Both outcomes append a history entry carrying
        ``tick`` and ``reason`` so failures are auditable.
        """
        if seats <= 0:
            self.history.append(
                {"tick": tick, "actor": "shelter", "event": "reserve_failed",
                 "assignment_id": assignment_id, "seats": seats,
                 "reason": "REJECTED:INVALID_SEATS"}
            )
            return False
        if self.occupancy + sum(self.reservations.values()) + seats > self.capacity:
            self.history.append(
                {"tick": tick, "actor": "shelter", "event": "reserve_failed",
                 "assignment_id": assignment_id, "seats": seats,
                 "reason": "REJECTED:OVER_CAPACITY"}
            )
            return False
        self.reservations[assignment_id] = self.reservations.get(assignment_id, 0) + seats
        self.history.append(
            {"tick": tick, "actor": "shelter", "event": "reserved",
             "assignment_id": assignment_id, "seats": seats, "reason": "OK"}
        )
        return True

    def checkin(self, assignment_id: str, tick: int = 0) -> int:
        """Move a reservation into occupancy (arrival). Returns seats checked in.

        Unknown ``assignment_id`` returns 0 (falsy) and logs the reason;
        occupancy is never mutated on failure and never goes negative.
        """
        seats = self.reservations.pop(assignment_id, 0)
        if seats:
            self.occupancy += seats
            self.history.append(
                {"tick": tick, "actor": "shelter", "event": "checkin",
                 "assignment_id": assignment_id, "seats": seats,
                 "reason": "OK"}
            )
            return seats
        self.history.append(
            {"tick": tick, "actor": "shelter", "event": "checkin_failed",
             "assignment_id": assignment_id, "seats": 0,
             "reason": "REJECTED:UNKNOWN_ASSIGNMENT"}
        )
        return 0

    def release(self, assignment_id: str, tick: int = 0) -> int:
        """Drop a reservation without changing occupancy. Returns seats released.

        Unknown ``assignment_id`` returns 0 (falsy) and logs the reason.
        """
        seats = self.reservations.pop(assignment_id, 0)
        if seats:
            self.history.append(
                {"tick": tick, "actor": "shelter", "event": "released",
                 "assignment_id": assignment_id, "seats": seats,
                 "reason": "OK"}
            )
            return seats
        self.history.append(
            {"tick": tick, "actor": "shelter", "event": "release_failed",
             "assignment_id": assignment_id, "seats": 0,
             "reason": "REJECTED:UNKNOWN_ASSIGNMENT"}
        )
        return 0


class World(BaseModel):
    nodes: dict[str, Node] = Field(default_factory=dict)
    edges: dict[str, Edge] = Field(default_factory=dict)
    incidents: dict[str, Incident] = Field(default_factory=dict)
    boats: dict[str, Boat] = Field(default_factory=dict)
    teams: dict[str, GroundTeam] = Field(default_factory=dict)
    shelters: dict[str, Shelter] = Field(default_factory=dict)
    tick: int = Field(default=0, ge=0)
    seed: int = 42

    def get_edge(self, edge_id: str) -> Edge:
        return self.edges[edge_id]

    def neighbors(self, node_id: str, mode: EdgeMode) -> list[tuple[str, Edge]]:
        """Adjacent (neighbor_id, edge) pairs for ``node_id`` filtered by ``mode``.

        Edges are treated as undirected for adjacency.
        """
        out: list[tuple[str, Edge]] = []
        for edge in self.edges.values():
            if edge.mode != mode:
                continue
            if edge.from_node == node_id:
                out.append((edge.to_node, edge))
            elif edge.to_node == node_id:
                out.append((edge.from_node, edge))
        return out

    def shelter_remaining(self, shelter_id: str) -> int:
        """capacity - occupancy - sum(reservations); may be negative (overbooked)."""
        shelter = self.shelters[shelter_id]
        return shelter.capacity - shelter.occupancy - sum(shelter.reservations.values())

    def to_dict(self) -> dict:
        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, data: dict) -> "World":
        return cls.model_validate(data)
