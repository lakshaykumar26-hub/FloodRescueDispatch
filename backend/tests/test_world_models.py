"""Phase 1 Step 02: world models + schemas (see docs/phase-1.../step-02)."""

import json

import pytest
from pydantic import ValidationError

from backend.app.schemas.assignments import Assignment
from backend.app.schemas.messages import Message
from backend.app.simulation.world import (
    Boat,
    Edge,
    GroundTeam,
    Incident,
    Node,
    Shelter,
    World,
)


def test_entities_construct_from_json() -> None:
    node = Node.model_validate(
        {"node_id": "N-01", "neighborhood": "North", "kind": "station", "x": 1.0, "y": 2.0}
    )
    assert node.node_id == "N-01"

    edge = Edge.model_validate(
        json.loads(
            '{"edge_id": "W-12", "from_node": "N-04", "to_node": "N-09",'
            ' "mode": "water", "travel_time": 8, "status": "open",'
            ' "risk_level": 0.2, "capacity": 1, "last_updated_tick": 14}'
        )
    )
    assert edge.travel_time == 8

    incident = Incident.model_validate(
        {"incident_id": "INC-08", "node_id": "N-04", "urgency": 4,
         "people": 6, "required_capabilities": ["boat"],
         "created_tick": 3, "status": "OPEN", "report_confidence": 0.9}
    )
    assert incident.urgency == 4

    boat = Boat.model_validate(
        {"boat_id": "BOAT-03", "node_id": "N-04", "capacity": 6,
         "fuel": 50.0, "fuel_reserve": 10.0}
    )
    assert boat.status == "AVAILABLE"

    team = GroundTeam.model_validate(
        {"team_id": "TEAM-02", "node_id": "N-01", "capabilities": ["medical"]}
    )
    assert team.status == "AVAILABLE"

    shelter = Shelter.model_validate(
        {"shelter_id": "SHELTER-02", "node_id": "N-09", "capacity": 10}
    )
    assert shelter.occupancy == 0

    assignment = Assignment.model_validate(
        {"assignment_id": "ASN-00031", "version": 1, "status": "PROPOSED"}
    )
    assert assignment.assignment_id == "ASN-00031"

    message = Message.model_validate(
        {"message_id": "MSG-00142", "type": "ASSIGNMENT_OFFER",
         "sender_id": "DISPATCH-01", "recipient_id": "BOAT-03",
         "simulation_id": "SIM-001", "created_at_tick": 42,
         "expires_at_tick": 52, "version": 3,
         "payload": {"assignment_id": "ASN-00031", "incident_id": "INC-08"}}
    )
    assert message.version == 3


def test_invalid_payloads_raise_validation_error() -> None:
    with pytest.raises(ValidationError):
        Boat.model_validate(
            {"boat_id": "B", "node_id": "N", "capacity": -1,
             "fuel": 10.0, "fuel_reserve": 1.0}
        )
    with pytest.raises(ValidationError):
        Edge.model_validate(
            {"edge_id": "E", "from_node": "A", "to_node": "B", "mode": "road",
             "travel_time": 2, "status": "open", "risk_level": 2.0, "capacity": 1}
        )
    with pytest.raises(ValidationError):
        Edge.model_validate(
            {"edge_id": "E", "from_node": "A", "to_node": "B", "mode": "road",
             "travel_time": 0, "status": "open", "risk_level": 0.1, "capacity": 1}
        )
    with pytest.raises(ValidationError):
        Incident.model_validate(
            {"incident_id": "I", "node_id": "N", "urgency": 6, "people": 2}
        )


def test_shelter_overbooking_refused() -> None:
    shelter = Shelter(
        shelter_id="SHELTER-01", node_id="N-09", capacity=10,
        occupancy=8, reservations={"ASN-1": 3},
    )
    assert shelter.remaining() == -1

    world = World(shelters={"SHELTER-01": shelter})
    assert world.shelter_remaining("SHELTER-01") == -1

    # Reserve-style check refuses: 8 occupied + 3 reserved, 1 more seat overbooks.
    assert shelter.reserve("ASN-2", 1) is False
    assert shelter.reservations == {"ASN-1": 3}

    # Helpers on a fresh shelter.
    fresh = Shelter(shelter_id="S", node_id="N", capacity=10, occupancy=8)
    assert fresh.reserve("ASN-9", 2) is True
    assert fresh.remaining() == 0
    assert fresh.reserve("ASN-10", 1) is False
    assert fresh.checkin("ASN-9") == 2
    assert fresh.occupancy == 10
    assert fresh.remaining() == 0
    assert fresh.reserve("ASN-11", 1) is False
    assert fresh.release("ASN-9") == 0  # already checked in, nothing reserved
    assert fresh.remaining() == 0

    held = Shelter(shelter_id="S2", node_id="N", capacity=10, occupancy=5)
    assert held.reserve("ASN-20", 3) is True
    assert held.remaining() == 2
    assert held.release("ASN-20") == 3
    assert held.remaining() == 5


def test_world_round_trip_preserves_ids_tick_seed() -> None:
    world = World(
        nodes={"N-01": Node(node_id="N-01", neighborhood="North",
                            kind="station", x=0.0, y=0.0)},
        edges={"W-12": Edge(edge_id="W-12", from_node="N-01", to_node="N-02",
                            mode="water", travel_time=8, status="open",
                            risk_level=0.2, capacity=1, last_updated_tick=14)},
        incidents={"INC-08": Incident(incident_id="INC-08", node_id="N-02",
                                      urgency=4, people=6,
                                      required_capabilities=["boat"])},
        boats={"BOAT-03": Boat(boat_id="BOAT-03", node_id="N-01",
                               capacity=6, fuel=50.0, fuel_reserve=10.0)},
        teams={"TEAM-02": GroundTeam(team_id="TEAM-02", node_id="N-01",
                                     capabilities=["medical"])},
        shelters={"SHELTER-02": Shelter(shelter_id="SHELTER-02",
                                        node_id="N-02", capacity=10)},
        tick=42,
        seed=7,
    )
    data = json.loads(json.dumps(world.to_dict()))
    reloaded = World.from_dict(data)
    assert set(reloaded.nodes) == {"N-01"}
    assert set(reloaded.edges) == {"W-12"}
    assert set(reloaded.incidents) == {"INC-08"}
    assert set(reloaded.boats) == {"BOAT-03"}
    assert set(reloaded.teams) == {"TEAM-02"}
    assert set(reloaded.shelters) == {"SHELTER-02"}
    assert reloaded.tick == 42
    assert reloaded.seed == 7
    assert reloaded.to_dict() == world.to_dict()
