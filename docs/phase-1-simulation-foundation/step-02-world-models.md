# Phase 1 / Step 02 — World Models + Schemas

## Goal

Single source of truth for every entity. All later code (engine, dispatch, API, mobile) uses these shapes.

Spec: §§5, 11.

## Files

- `backend/app/simulation/world.py` (dataclasses or Pydantic models for in-memory state)
- `backend/app/schemas/{incidents.py,resources.py,assignments.py,messages.py}` (Pydantic validation — may live here early, used by API later)
- `backend/tests/test_world_models.py`

## Implementation

1. **Node:** `{node_id, neighborhood, kind: intersection|incident_site|shelter|station|transfer, x, y}` — x/y synthetic coords for SVG/Leaflet.
2. **Edge:** `{edge_id, from_node, to_node, mode: road|water, travel_time:int ticks, status: open|closed|disputed, risk_level:0-1, capacity:int, last_updated_tick}`.
3. **Incident:** `{incident_id, node_id, urgency 1-5, people:int, required_capabilities:[boat|ground|medical...], created_tick, status: OPEN|ASSIGNED|IN_PROGRESS|SERVED|CANCELLED|UNRESOLVED, report_confidence:0-1}`.
4. **Boat:** `{boat_id, node_id, capacity, fuel, fuel_reserve_policy, speed, status lifecycle, assignment_id?, passengers}`.
5. **GroundTeam:** `{team_id, node_id, capabilities, status, assignment_id?}`.
6. **Shelter:** `{shelter_id, node_id, capacity, occupancy, reservations: {assignment_id: seats}, incoming}` — keep `occupancy` (bodies inside) separate from `reservations` (seats promised).
7. Validation rules in schemas: `capacity>0`, `0<=risk<=1`, `travel_time>=1`, `occupancy+reservations<=capacity` checked at commit time (not just model time — validator lives in Phase 2, but model exposes helper `remaining_capacity()`).
8. `World` class: dicts of nodes/edges/incidents/boats/teams/shelters + `tick:int` + `seed`. Methods: `get_edge()`, `neighbors(node, mode)`, `shelter_remaining()`.

## What to test

- [ ] `pytest backend/tests/test_world_models.py -q`: construct each entity from JSON, invalid payload (negative capacity, risk 2.0, travel_time 0) raises `ValidationError`.
- [ ] Shelter helper: occupancy 8 + reservations 3, capacity 10 → `remaining== -1` flagged (or `reserve(seats)` returns False, no silent overbook).
- [ ] Serialize `World` → JSON → reload preserves all IDs and tick.
- [ ] Manual: load a hand-written 4-node dict, print it — no FastAPI import in traceback (`grep import backend/app/simulation/world.py`).
