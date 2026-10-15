# Phase 4 — Dynamic Events + Replanning

Goal: closures, failures, overflow, conflicting reports trigger explicit auditable replanning. Combined-disaster scenario at tick 40 works.

Source spec: §§9, 10, 17.

## Steps

1. `step-01-flood-closures.md` — flood progression + bridge closure + route invalidation.
2. `step-02-boat-failure-recovery.md` — failure + passenger recovery workflow.
3. `step-03-shelter-overflow.md` — overflow + destination reassignment.
4. `step-04-conflicting-reports.md` — report store, conservative disputed-edge policy, explanations.
5. `step-05-replanning-combined.md` — invalidation pipeline + `combined_disaster.json` (tick-40 test).

## Done when

Disruptions cause `CANCELLED → REPROPOSED → COMMITTED` chains with reasons, no silent violations, recovery assignments for stranded passengers.
