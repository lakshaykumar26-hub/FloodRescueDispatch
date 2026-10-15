# Phase 6 / Step 02 — Persistence (Supabase/Postgres)

## Goal

Durable runs, history, messages, snapshots, metrics per §11.

## Files

- `backend/app/persistence/{database.py,repositories.py}`, SQL migration file(s), `.env.example` (`DATABASE_URL`)
- `backend/tests/test_persistence.py` (sqlite in-memory or test schema)

Tables: `simulation_runs, locations, network_edges, incidents, resources, shelters, simulation_events, assignments, assignment_history, communication_messages, reports, state_snapshots, simulation_metrics`. Every row: `simulation_id + tick`. Snapshots reuse Phase-1 JSON format (`version:1`). Deterministic seeds stored on run.

Write policy: snapshots every N ticks + meaningful events; not every micro-mutation. `assignment_history` append-only.

## What to test

- [ ] Create run → rows in `simulation_runs` with seed + strategy + status.
- [ ] Commit + cancel → two rows in `assignment_history`, current row in `assignments` reflects cancel.
- [ ] Message lifecycle states persisted distinctly (QUEUED/DELIVERED/ACKED/EXPIRED).
- [ ] Snapshot restore from DB equals in-memory restore (round-trip test).
- [ ] Manual: run 30 ticks, count rows — snapshots ~3, events >0, no per-edge-per-tick spam.
