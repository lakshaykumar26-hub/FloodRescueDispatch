# Phase 4 / Step 03 — Shelter Overflow + Reassignment

## Goal

Full shelters reroute arrivals without overbooking.

## Files

- `state_manager.py` (`shelter_full` event), `dispatch` (destination swap), `scenarios/shelter_overflow.json`

## Implementation

1. Event `SHELTER_FULL {shelter_id}` (or occupancy reaching capacity via checkins): mark shelter unavailable for new reservations; scan `COMMITTED/IN_PROGRESS` assignments targeting it with unarrived passengers → `REQUIRES_RECONCILIATION:SHELTER_FULL`.
2. Reassignment: nearest shelter with `remaining>=people` via normal propose→validate→commit; old reservation released only after new commit succeeds (no gap where seats double-held or lost). History links `replaces: ASN-old`.
3. If no shelter fits → incident stays served-at-scene or `UNRESOLVED: NO_SHELTER` (explicit, never overbook).

## What to test

- [ ] Fill shelter mid-transport → affected assignments rerouted, `occupancy+reservations<=capacity` holds on both shelters every tick (assert in test loop).
- [ ] Two boats racing last bed → one wins, other rerouted (no over-reserve).
- [ ] No capacity anywhere → explicit `NO_SHELTER`, no commit to full shelter.
