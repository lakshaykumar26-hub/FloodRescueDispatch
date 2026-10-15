# Phase 2 / Step 05 — Safety Validator + Event Logging + Engine Wiring

## Goal

Last gate before commit + auditable history. Wire scheduler into the tick loop, deleting the Phase-1 stub.

Spec §10 (all invariants), §7.1 steps 6–8.

## Files

- `backend/app/dispatch/safety_validator.py`
- `backend/app/simulation/engine.py` (wire propose→resolve→validate→commit each tick)
- `backend/tests/test_safety_invariants.py`

## Implementation

1. `validate(world, proposal, tick) -> (bool, [violations])` checks, in order: route safety (no prohibited edge), resource available, exclusive assignment (no conflicting active), capacity, shelter `occupancy+reservations<=capacity`, transport compatibility, fuel reserve, assignment validity (not expired/cancelled). Each violation string-coded.
2. Engine wiring per tick (after movement, before queueing): `proposals=propose() → resolved=resolve() → for each: feasible? → validate? → commit()`. Rejections logged with reason + tick. Delete stub assigner.
3. Event log entries: `PROPOSED/COMMITTED/REJECTED/CANCELLED` with `{assignment_id, incident, resource, reason, cost, alternatives_considered}` — alternatives feed the dashboard explanation panel (Phase 6).

## What to test

- [ ] `pytest backend/tests/test_safety_invariants.py -q`: one test per invariant row — each crafts a violating proposal, asserts `validate()==False` + correct code, and engine refuses to commit it (no assignment created).
- [ ] Baseline 60 ticks: every `COMMITTED` has a preceding `PROPOSED`; every `REJECTED` has a reason; zero `COMMITTED` routes use a closed edge (scan log).
- [ ] Determinism: fixed seed → identical commit order + winners across two runs.
- [ ] Manual: `run --scenario baseline.json` summary now shows assignments + rejection breakdown by reason code.
