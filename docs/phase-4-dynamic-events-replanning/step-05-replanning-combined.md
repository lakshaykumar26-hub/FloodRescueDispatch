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

## Decision notes (as built, Phase 4)

- Tick order: `advance → pop_due (BOAT_FAILURE→trigger_recovery, REPORT→ingest_report, else apply_event) → _detect_and_handle → progress → advance_positions → dispatch → link → snapshot`. `BOAT_FAILURE` must NOT reach `apply_event` (its `fail_boat` branch would double-fire).
- No-alternate route suspends, never strands: hold + per-tick `ROUTE_BLOCKED` + retry (reopen resumes). Rationale: literal cancel-on-no-alternate breaks the reopen flow and the Phase-1 hold contract. Limitation: a permanently unroutable mission holds forever (incident stays `ASSIGNED`); terminal `REPLAN_FAILED` fires only on the cancel path (`NO_ROUTE`/`NO_SHELTER`).
- Detection filters in-flight-expected codes (`RESOURCE_UNAVAILABLE` busy-with-self, `OVER_CAPACITY` boarded-seats double-count, `FUEL_INSUFFICIENT` full-leg pricing) and credits the assignment's own shelter hold; without this every transporting boat false-positives. Re-validation uses live remaining legs with `eta_ticks=0`, keyed by `proposal_id` so the validator's self-conflict skip applies.
- Recovery boarding is a `TRANSFER` decrementing the failed hull (never from `incident.people`); cancelled-then-replaced chains link via `replaces`/`replaced_by` + `REPLAN_CHAIN`. `pending_replans` is same-tick transient (not snapshotted); orphaned incidents still get served via normal dispatch on resume.
- `shelter_overflow.json` legitimately ends with one incident `OPEN` (both shelters full after a conservative swap) — completion is asserted on `combined_disaster.json` (13/13 both strategies), per-tick capacity on the overflow run.
