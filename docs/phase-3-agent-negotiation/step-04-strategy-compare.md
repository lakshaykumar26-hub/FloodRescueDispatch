# Phase 3 / Step 04 — Strategy Switch + Parity

## Goal

Fair comparison harness: same scenario + seed, either strategy, deterministic.

## Files

- `backend/app/simulation/run.py` (`--strategy centralized|negotiation`), `engine.py` (inject scheduler)
- `backend/app/evaluation/experiment_runner.py` (stub: run N ticks under each strategy, dump assignment counts — full metrics Phase 8)
- `scenarios/baseline.json` (add `strategy` override support, not hardcoded)

## Implementation

1. Engine takes `scheduler: Scheduler`. CLI `--strategy` + `--seed` override scenario file.
2. `experiment_runner.run_pair(scenario, ticks)`: run both strategies same seed, return `{strategy, committed, rejected_by_reason, ticks}`. No fairness math yet (Phase 8).
3. Document any intentional behavioral differences (e.g. negotiation includes `O` term) in file header.

## What to test

- [ ] Same seed, centralized twice → identical winners. Negotiation twice → identical winners.
- [ ] `--strategy bogus` exits with usage error, no partial run.
- [ ] Manual: `run --strategy centralized` vs `run --strategy negotiation` on baseline — both complete, both log zero safety violations, print side-by-side summary.
