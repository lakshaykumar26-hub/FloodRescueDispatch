# Phase 2 — Centralized Dispatch

Goal: greedy-but-safe central scheduler replaces the Step-06 stub. Feasible incidents get committed assignments; infeasible get rejected with reasons.

Source spec: §§7.1, 7.3, 7.4, 10, 17.

## Steps

1. `step-01-scheduler-interface.md` — `scheduler_interface.py` contract both strategies share.
2. `step-02-centralized-scheduler.md` — rank → candidates → routes → score → propose.
3. `step-03-feasibility-scoring.md` — `bid_evaluator.py` + cost function + hard-vs-soft separation.
4. `step-04-commitments-conflicts.md` — `conflict_resolver.py` + `commitment_manager.py` + lifecycle.
5. `step-05-safety-validator-logging.md` — `safety_validator.py` (all §10 invariants) + `assignment_history` logging + engine wiring.

## Done when

- Baseline headless run assigns feasible incidents, rejects the rest with machine-readable reasons.
- `test_dispatch.py` + `test_safety_invariants.py` green; no conflicting active assignments; deterministic winner under fixed seed.
