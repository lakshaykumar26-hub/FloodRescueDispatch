# Phase 3 / Step 02 — Resource Agents + Bid Generation

## Goal

Each agent type evaluates feasibility from its own belief and emits spec-shaped bids.

## Files

- `backend/app/agents/{incident_agent.py,boat_agent.py,ground_team_agent.py,shelter_agent.py,report_agent.py}`
- `backend/tests/test_negotiation.py` (bid cases)

## Implementation

1. `IncidentAgent.publish_request() -> {incident_id, urgency, people, capabilities, raffic_version}`.
2. `BoatAgent/GroundTeamAgent.evaluate(request) -> bid|None`: check mode, status AVAILABLE, route via `pathfinder` on **local belief graph**, fuel, capacity, shelter feasible (from belief). Bid: `{agent_id, incident_id, estimated_arrival, estimated_completion, risk_score, people_capacity, fuel_feasible, shelter_feasible, belief_version}`. Infeasible → return `(None, reason)`; caller logs it (feeds explanation panel).
3. `ShelterAgent.reserve_bid(people) -> (accept, remaining)`; `ReportAgent.submit_claim()` stub (full conflict logic Phase 4).
4. Boat example from spec §6 (`capacity, fuel, location, status, assignment_id, passengers, local_belief`) as constructor shape.

## What to test

- [ ] Boat with stale belief (edge open locally, closed globally) bids optimistically — bid flagged with old `belief_version` (reconciliation in Phase 5 catches it; for now validator may still reject at commit).
- [ ] Incompatible mode → no bid + reason `MODE_MISMATCH`; low fuel → `FUEL_INSUFFICIENT`.
- [ ] Shelter full from its own books → `SHELTER_FULL` accept=False.
- [ ] Manual: 1 incident + 3 boats → 2 bids + 1 rejection with distinct reasons.
