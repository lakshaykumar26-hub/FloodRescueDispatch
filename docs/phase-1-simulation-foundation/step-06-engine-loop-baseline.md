# Phase 1 / Step 06 — Engine Loop + Baseline Scenario (Headless)

## Goal

Prove the foundation runs end-to-end with dumb movement (no smart dispatch yet). Phase 2 replaces the stub assigner.

Spec: §§9 (loop order), 15 (synthetic sizes).

## Files

- `backend/app/simulation/engine.py`
- `backend/app/simulation/run.py` (CLI: `python -m backend.app.simulation.run --scenario scenarios/baseline.json`)
- `scenarios/baseline.json` (full: 25 nodes, 25 road, 20 water, 12 incidents, 5 boats, 5 teams, 4 shelters, 4 neighborhoods, seed 42)
- `backend/tests/test_engine_smoke.py`

## Implementation

1. `engine.py` `Simulation(tick, world, scheduler, log)` with `step()` in fixed order (log the order in docstring):
   1. `clock.advance()` 2. `pop_due` + apply events 3. update world 4. (comms stub: no-op until Phase 5) 5. move each `EN_ROUTE`/transporting resource one edge along its precomputed route if edge still open, else hold + log `ROUTE_BLOCKED` 6. update incidents/shelters 7. record snapshot every N ticks (N=10).
2. Stub assigner (DELETE in Phase 2): greedily pair first OPEN incident with first AVAILABLE compatible resource, precompute route. This exists only to exercise movement; mark with `TODO(P2): replace with centralized_scheduler`.
3. `baseline.json`: ensure mix — some road-only, some water-only, some transfer-required incidents; ≥2 isolated nodes with alternate routes so closures matter. All coords synthetic.
4. `run.py`: load JSON → build World → loop to `ticks` or all `SERVED` → print summary (`served/unserved, ticks, snapshots`).

## What to test

- [ ] `pytest backend/tests/test_engine_smoke.py -q`: run baseline seed 42 for 30 ticks headless — completes without exception, `event_log` non-empty, at least one resource moved, snapshots taken at 10/20/30.
- [ ] Determinism: run twice same seed → identical final tick + served count. Change seed → (likely) different outcome; log both.
- [ ] Blocked-route hold: close a bridge mid-run (inject `CLOSURE` at tick 5 in a copy of baseline) → affected boat logs `ROUTE_BLOCKED`, does NOT teleport or traverse closed edge.
- [ ] Manual: `python -m backend.app.simulation.run --scenario scenarios/baseline.json --ticks 20` prints tick-by-tick movement + final summary.
