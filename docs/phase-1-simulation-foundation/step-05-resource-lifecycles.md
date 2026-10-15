# Phase 1 / Step 05 — Resource Lifecycles (Boat / Team / Shelter)

## Goal

Correct state machines + capacity accounting before any dispatch intelligence. Catches overbooking and phantom-rescue bugs early.

Spec: §§5, 6, 10, 17.

## Files

- `backend/app/simulation/state_manager.py` (extend) or `backend/app/agents/base_agent.py` stub — keep logic in simulation for Phase 1 (agent beliefs split in Phase 3)
- `backend/tests/test_boat_lifecycle.py`

## Implementation

1. **Boat FSM:** `AVAILABLE → ASSIGNED → EN_ROUTE_TO_INCIDENT → RESCUING → TRANSPORTING_TO_SHELTER → RECOVERY → AVAILABLE`, plus `UNAVAILABLE/FAILED/STRANDED/RETURNING/MAINTENANCE`. Implement `transition(boat, to, reason, tick)` that rejects illegal jumps (e.g. `AVAILABLE→TRANSPORTING`) with explicit error/reason. `FAILED` while `passengers>0` sets flag `needs_recovery=True` (workflow in Phase 4 — for now just flag + log, do NOT delete passengers).
2. **Ground team FSM:** simplified `AVAILABLE→ASSIGNED→ON_SCENE→RETURNING→AVAILABLE` (+ `UNAVAILABLE`). Same guarded transition.
3. **Shelter accounting:** `reserve(shelter, assignment_id, seats, tick)` fails if `occupancy+reservations+seats>capacity`; `checkin()` moves reservation→occupancy; `release()` drops reservation (on cancel). Never allow negative.
4. **Fuel:** `can_depart(boat, route_eta)` checks `fuel >= eta + reserve`. Decrement per tick moved. Insufficient → transition refused with `FUEL_INSUFFICIENT`.
5. All transitions append to `event_log` + per-entity `history[]`.

## What to test

- [ ] `pytest backend/tests/test_boat_lifecycle.py -q`:
  - Full happy path AVAILABLE→…→AVAILABLE passes.
  - Illegal jump raises/returns `REJECTED:ILLEGAL_TRANSITION`.
  - `FAILED` with 4 passengers → `needs_recovery is True`, passengers still counted (not zeroed).
  - Over-capacity boarding (`passengers 7 > capacity 6`) rejected.
  - Shelter at 9/10, two concurrent `reserve(2)` → exactly one succeeds.
  - Low-fuel boat refused departure (`FUEL_INSUFFICIENT`), fuel unchanged.
  - Failed resource (`status FAILED`) refuses new `ASSIGNED`.
- [ ] Manual: print a boat's `history` after 3 transitions — each entry has tick + reason.
