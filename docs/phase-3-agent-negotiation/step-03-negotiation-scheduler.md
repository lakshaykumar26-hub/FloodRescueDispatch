# Phase 3 / Step 03 — Negotiation Scheduler Flow

## Goal

Implement §7.2 pipeline: publish → bids → conflict-resolve → safety-validate → commit → acknowledge.

## Files

- `backend/app/dispatch/negotiation_scheduler.py` (implements `Scheduler` protocol)
- Reuse `bid_evaluator.py`, `conflict_resolver.py`, `commitment_manager.py`, `safety_validator.py` — extend, don't duplicate.
- `backend/tests/test_negotiation.py` (flow tests)

## Implementation

1. `propose(world, tick)`: incident agents publish; eligible resource agents bid (Step 02); collect `{bid, reason}` pairs.
2. `conflict_resolver` picks lowest-cost feasible bid per incident (same cost fn as Phase 2, now with `O` opportunity cost = second-best cost delta — document).
3. `safety_validator` gates; `commitment_manager.commit()` commits; resource agent `acknowledge()` flips `COMMITTED→ACKNOWLEDGED` (log `ACK` separately — accepted ≠ acked ≠ completed).
4. Cancellation path: `cancel(assignment, reason)` → notify both agents → history.
5. Keep synchronous in-process for MVP (asyncio gateway arrives Phase 5). Note in docstring where `await gateway.send()` will slot in.

## What to test

- [ ] 2 boats bid same incident → lower-cost wins; loser reason preserved (`HIGHER_COST: winner BOAT-02 cost 14.2 vs 18.7`).
- [ ] Winning bid failing safety (edge closed globally after bid) → `REJECTED:EDGE_CLOSED`, no commit, incident stays OPEN.
- [ ] Ack: after commit, resource status `ACKNOWLEDGED` logged distinct from `COMMITTED`.
- [ ] Manual: run with `--strategy negotiation`, compare commit count vs centralized (may differ — both must be valid).
