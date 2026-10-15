# Phase 4 / Step 05 — Replanning Pipeline + Combined Disaster

## Goal

Single invalidation→replan path for all disruption kinds + the spec's tick-40 stress test.

## Files

- `backend/app/dispatch/commitment_manager.py` (`invalidate_and_replan`), `scenarios/combined_disaster.json`

## Implementation

1. `detect_invalid(world, tick)`: iterate active assignments → `safety_validator.validate` → invalid list with reasons.
2. For each: cancel/suspend with reason → release/re-reserve per Steps 02–03 → re-`propose` for orphaned incidents + recovery requests → resolve/validate/commit → link histories.
3. `combined_disaster.json`: at tick 40 — bridge closes, BOAT-02 fails (with passengers), SHELTER-01 fills, new urgency-5 incident, BOAT-03 partitioned (partition enforced Phase 5; for now log `COMMS_NOTE: partition simulated in P5`). Expected log sequence per §9: edge+resource states updated → routes revalidated → recovery started → destinations recalculated → reassignment → queue-for-BOAT-03 note → all with reasons → reconcile note.
4. Both strategies must handle it (run `--strategy` ×2).

## What to test

- [ ] `run --scenario combined_disaster.json --strategy centralized` and `--strategy negotiation`: complete, zero invariant violations, recovery assignment exists, BOAT-03 note present.
- [ ] Every `CANCELLED` has a linked `COMMITTED` replacement or explicit `REPLAN_FAILED` reason (no orphans).
- [ ] History chain for one incident readable end-to-end (print and eyeball).
