# Phase 2 / Step 02 — Centralized Greedy Scheduler

## Goal

Rank incidents → compatible candidates → routes → ranked proposals (commit in Step 04).

Spec §7.1 steps 1–5.

## Files

- `backend/app/dispatch/centralized_scheduler.py`
- `backend/tests/test_dispatch.py` (extend)

## Implementation

1. Rank OPEN incidents by `(urgency desc, waiting_ticks desc, people desc)`. Waiting = `tick - created_tick`.
2. For each incident in rank order: compatible resources = kind matches `required_capabilities`, status `AVAILABLE`, not already tentatively claimed this tick.
3. For each (incident, resource): `find_route` incident leg + shelter leg (nearest shelter with `remaining>0`); skip if `NO_ROUTE` (record reason).
4. Score (detail in Step 03) → keep cheapest feasible per incident → emit `ProposedAssignment` list sorted by incident rank.
5. Tentative claim set within one `propose()` call so two incidents can't propose the same boat in the same tick (final arbitration in Step 04).

## What to test

- [ ] Fixture: 2 incidents, 1 boat → higher-urgency incident gets the proposal; loser gets reason `RESOURCE_CLAIMED:HIGHER_RANK`.
- [ ] No compatible resource (all boats FAILED) → `propose()==[]`, no exception.
- [ ] Water incident offered only to boats, road incident only to teams (assert no cross-mode proposal in test).
- [ ] Manual: run baseline 20 ticks, log proposals/tick — count >0 and each has eta + cost.
