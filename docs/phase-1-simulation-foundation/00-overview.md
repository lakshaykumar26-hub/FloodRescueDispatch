# Phase 1 — Simulation Foundation

Goal: headless time-stepped world (graph + clock + state machines) that runs start→finish with no frontend, no dispatch intelligence yet.

Source spec: §§5, 6, 9, 15, 16 (Phase 1), 17.

## Steps

1. `step-01-repo-scaffold.md` — monorepo, Python tooling, scenario dir, headless runner entry.
2. `step-02-world-models.md` — Pydantic schemas: nodes, edges, incidents, boats, teams, shelters.
3. `step-03-graph-routing.md` — NetworkX road/water graphs, mode-filtered pathfinder.
4. `step-04-clock-scheduler-state.md` — clock, event scheduler, state manager, snapshots.
5. `step-05-resource-lifecycles.md` — boat/team state machines, shelter occupancy vs reservations.
6. `step-06-engine-loop-baseline.md` — deterministic tick loop + `baseline.json` + headless run.

## Done when

- `python -m backend.app.simulation.run --scenario scenarios/baseline.json` (or equivalent) advances ticks, moves stub resources on valid routes, updates shelters, and exits with a summary.
- `pytest backend/tests -q` passes: routing, boat lifecycle, snapshot restore.
- No imports from FastAPI/DB inside `simulation/` (enforced by test or grep).
