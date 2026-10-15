# Phase 1 — Phase Testing (gate)

All boxes must pass before starting Phase 2.

## Headless run

- [ ] `python -m backend.app.simulation.run --scenario scenarios/baseline.json` runs start→finish, exit 0, prints served/unserved + ticks.
- [ ] Same seed twice → identical `event_log` hash (compare `sha256` of JSON log). Different seed documented.

## Routing + resources (§17)

- [ ] Closed edge never in a new route (`test_routing.py` green).
- [ ] Fuel-insufficient boat rejected; capacity never exceeded; failed resource gets no mission; full shelter rejects reservation; failed boat with passengers sets `needs_recovery` (passengers preserved).

## Determinism + snapshots

- [ ] Snapshot at tick T → restore → continue equals uninterrupted run (state + tick + seed).
- [ ] Scheduler order fixed: closure at tick 40 applies before movement in tick 40 (assert via log order in a 45-tick test run).

## Isolation

- [ ] `grep -rn "from fastapi\|from sqlalchemy\|import supabase" backend/app/simulation/ backend/app/routing/` → no hits.
- [ ] `pytest backend/tests -q` all green (models, routing, lifecycle, engine smoke, snapshot round-trip).

## Exit artifact

Record in `docs/README.md`: baseline seed 42 served count + ticks to complete.
