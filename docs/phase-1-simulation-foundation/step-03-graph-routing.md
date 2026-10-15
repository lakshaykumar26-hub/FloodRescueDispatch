# Phase 1 / Step 03 — Graph + Routing

## Goal

Mode-correct shortest paths that never route through closed edges. Foundation for dispatch scoring (Phase 2) and replanning (Phase 4).

Spec: §§5, 17 (routing checklist).

## Files

- `backend/app/routing/{graph.py,pathfinder.py,route_validator.py}`
- `backend/tests/test_routing.py`
- `scenarios/mini_graph.json` (4–6 node fixture for tests)

## Implementation

1. `graph.py`: build two NetworkX `DiGraph`s (or one with mode attr) from `World.edges`. Weight = `travel_time`. Provide `build_graph(world, mode, tick)` that **excludes** `status==closed`. `disputed` edges included but flagged (conservative policy applied in Phase 4; for now return `warnings` list).
2. `pathfinder.py`: `find_route(world, origin, dest, mode) -> {nodes:[...], edges:[...], eta_ticks, risk, warnings}`. Use `nx.shortest_path(weight=travel_time)`. No path → return `None`, never raise in engine loop (caller logs `NO_ROUTE`).
3. `route_validator.py`: `is_route_valid(world, edge_ids, mode) -> (bool, reason)`. Checks: all edges exist, mode matches, none closed, capacity>0. This is the primitive Phase 2's safety validator will call.
4. Keep pure: functions take `World`, return data. No clock, no I/O.

## What to test

- [ ] `pytest backend/tests/test_routing.py -q`:
  - Open graph A→B→C (cost 5+5) vs direct A→C (cost 12) picks via B.
  - Close B→C → reroutes via direct or returns None with reason `EDGE_CLOSED:W-12`.
  - Boat requesting road-only path → `MODE_MISMATCH`.
  - Water edge closed → boat gets `NO_ROUTE`, ground team unaffected (separate graphs).
  - `travel_time` sum equals reported `eta_ticks`.
- [ ] Manual: script prints route for `mini_graph.json` before/after closing one edge — second route differs or cleanly reports none.
- [ ] Performance sanity: 25-node baseline routes in <50ms each (log timing, no assert needed yet).
