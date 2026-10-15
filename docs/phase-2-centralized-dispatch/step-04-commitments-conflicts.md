# Phase 2 / Step 04 — Conflict Resolution + Commitment Manager

## Goal

At-most-one active assignment per resource, at-most-capacity per shelter, with explicit lifecycle and no silent overwrites.

Spec §§7.4, 10 (exclusive assignment, shelter capacity, validity).

## Files

- `backend/app/dispatch/{conflict_resolver.py,commitment_manager.py}`
- `backend/tests/test_dispatch.py` (contention cases)

## Implementation

1. `conflict_resolver.resolve(proposals, world)`: group by `resource_id` and by `shelter_id`. Resource contention → keep lowest cost, reject rest `RESOURCE_CONFLICT:WINNER=ASN-..`. Shelter over-subscription in same tick → keep in incident-rank order until seats run out, reject rest `SHELTER_CONFLICT`.
2. `commitment_manager.commit(world, proposal, tick)`: assign `ASN-xxxxx` + `version=1`, set incident `ASSIGNED`, resource `ASSIGNED`, `shelter.reserve()`, create history entry. State changes atomic per assignment (if shelter reserve fails at commit → whole commit rejected `SHELTER_FULL_AT_COMMIT`).
3. Lifecycle methods: `acknowledge/ac knowledge`, `start_progress`, `complete`, `cancel(reason)` — each validates allowed transition + appends history. `cancel` releases shelter reservation + frees resource (to `AVAILABLE` or `RECOVERY` as appropriate).
4. Idempotency: `commit` with same `proposal_id` twice returns existing assignment (no duplicate) — full dedup hardening in Phase 5, basic guard now.

## What to test

- [ ] Two proposals same boat same tick → exactly one `COMMITTED`, other `REJECTED:RESOURCE_CONFLICT`.
- [ ] Two boats → same last shelter bed → one `COMMITTED`, one `SHELTER_CONFLICT`; `occupancy+reservations` never exceeds capacity.
- [ ] `cancel()` frees boat and releases shelter seats (assert counts before/after).
- [ ] Double-`commit` same proposal → single `assignment_id`, version unchanged.
- [ ] Manual: contention fixture log shows winner + loser reason.
