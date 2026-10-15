# Phase 4 / Step 02 — Boat Failure + Passenger Recovery

## Goal

Failed boats never strand passengers silently; recovery is a first-class assignment.

## Files

- `state_manager.py` (`fail_boat`), `commitment_manager.py` (recovery path), `scenarios/boat_failure.json`

## Implementation

1. `BOAT_FAILURE {boat_id, tick}`: status→`FAILED`, current assignment→`CANCELLED:RESOURCE_FAILED`. If `passengers>0`: create `RECOVERY_REQUEST {stranded_node, people:passengers, priority: urgency 5}` + log `RECOVERY_TRIGGERED`.
2. Recovery request behaves like an incident (ranked top) but linked `caused_by: ASN-..`. Nearest capable boat + shelter assigned through normal pipeline (safety-checked).
3. Failed boat needs `RETURNING/MAINTENANCE` before reuse; test asserts it gets no new missions while `FAILED`.

## What to test

- [ ] Fail empty boat → clean cancel + reassign incident, no recovery request.
- [ ] Fail boat with 4 passengers → recovery request with 4 people, new boat dispatched, shelter reserved; original 4 never double-counted as served + stranded.
- [ ] FAILED boat offered new incident → rejected `RESOURCE_UNAVAILABLE`.
- [ ] Manual: `run --scenario boat_failure.json` — log shows `RESOURCE_FAILED → RECOVERY_TRIGGERED → RECOVERY_COMMITTED`.
