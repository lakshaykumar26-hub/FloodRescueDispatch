# Phase 1 / Step 04 — Clock, Event Scheduler, State + Snapshots

## Goal

Deterministic time + scheduled disruptions + restorable state. Required for replay (Phase 6) and multi-seed eval (Phase 8).

Spec: §§9, 11.

## Files

- `backend/app/simulation/{clock.py,event_scheduler.py,state_manager.py,snapshots.py}`
- `backend/tests/test_replay.py` (first half: snapshot round-trip; full replay asserted in Phase 6)
- `scenarios/baseline.json` (skeleton — full content in Step 06)

## Implementation

1. `clock.py`: `{tick:int, tick_length_note}`. Methods `advance(n=1)`, `reset(seed)`. Document ordering contract in docstring: events scheduled for tick T apply **before** movement in tick T.
2. `event_scheduler.py`: min-heap of `{tick, kind, payload, event_id}`. Kinds for now: `CLOSURE, FLOOD_RISE, INCIDENT_ARRIVAL` (failure/overflow arrive Phase 4 — scheduler must already support arbitrary kinds). `pop_due(tick)` returns due events in `(tick, event_id)` order. Seeded `random.Random(seed)` for any jitter.
3. `state_manager.py`: owns `World`, applies events (`apply_closure`, `apply_incident`), moves resources one edge per tick helper (`advance_positions()` — full movement rules in Step 05/06). Every mutation appends `{tick, kind, actor, detail}` to in-memory `event_log`.
4. `snapshots.py`: `take_snapshot(world, tick) -> dict` (deep copy + tick + seed + event_log length) and `restore(data) -> World`. JSON-serializable. Later persisted to `state_snapshots` table (Phase 6) — keep format stable from now on (`version: 1` field).
5. Baseline skeleton: `{scenario_name, random_seed:42, ticks:120, nodes:25, road_edges:25, water_edges:20, incidents:12, boats:5, teams:5, shelters:4, neighborhoods:4}` + empty event list (filled Step 06).

## What to test

- [ ] `pytest backend/tests/test_replay.py -q` (partial): take snapshot at tick 10, mutate world, restore → deep-equal to snapshot; `tick` and `seed` preserved; snapshot JSON round-trips via `json.dumps/loads`.
- [ ] Scheduler: two events same tick fire in `event_id` order; event at tick 40 does NOT fire at tick 39 (`pop_due(39)==[]`).
- [ ] Same seed → same `pop_due` sequence across two runs (run twice, diff logs).
- [ ] Manual: `python -c` advance clock 5 ticks, print tick — no wall-clock drift (no `time.sleep`, no datetime ordering).
