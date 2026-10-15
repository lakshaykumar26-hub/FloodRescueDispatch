# Phase 5 / Step 04 — Reconnect + Reconciliation

## Goal

Stale missions detected and resolved explicitly on return.

## Files

- `backend/app/communications/gateway.py` (`reconcile`), `commitment_manager.py` (version guard)
- `backend/tests/test_network_partition.py` (reconnect cases)

## Implementation

1. On `partition_end`: agent sends `{belief_version, assignment_id, assignment_version}`; coordinator compares to authoritative state.
2. Outcomes: `IN_SYNC` (resume), `STALE_ROUTE` (push new route, require re-ack before movement), `STALE_OWNERSHIP` (assignment reassigned while away → mark old `REQUIRES_RECONCILIATION`, do NOT auto-resume), `CONFLICT` (both sides committed — surface both, human/strategy resolves; never silently erase).
3. Commits validate `base_version == current_version` else `REJECTED_STALE` (mirrors mobile `base_assignment_version` in Phase 7).
4. Reconciliation timed: record `reconciliation_time` ticks (metric in Phase 8).

## What to test

- [ ] Partitioned boat misses closure → on return gets `STALE_ROUTE`, holds position until re-ack (assert no movement on stale route).
- [ ] Assignment reassigned during partition → returning boat's old ASN marked `REQUIRES_RECONCILIATION`, not resumed.
- [ ] Double-commit conflict represented explicitly (both versions visible in log).
- [ ] Manual: partition fixture print before/after belief versions.
