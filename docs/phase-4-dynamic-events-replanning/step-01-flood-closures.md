# Phase 4 / Step 01 — Flood Progression + Bridge Closures

## Goal

Edges close/reopen over time; affected routes invalidated before movement each tick.

## Files

- `backend/app/simulation/event_scheduler.py` (extend kinds), `state_manager.py` (`apply_closure/reopen`)
- `backend/app/routing/route_replanner.py` (real logic: `replan(world, assignment) -> new_route|None`)
- `scenarios/bridge_closure.json`, `backend/tests/test_replanning.py`

## Implementation

1. Event kinds: `BRIDGE_CLOSURE {edge_id}`, `EDGE_REOPEN {edge_id}`, `FLOOD_RISE {edge_ids, risk_delta}`. Apply before movement (documented order).
2. After applying: scan active assignments whose route uses a now-closed edge → mark `REQUIRES_RECONCILIATION` (or `CANCELLED:EDGE_CLOSED` if mid-leg and no alt) + emit replan request.
3. `route_replanner.replan`: `find_route` excluding closed; disputed edges allowed only if `allow_disputed=False` default → skip; return `(route, reason)`.

## What to test

- [ ] Close edge on active route → assignment flagged same tick, replan attempted, history has `EDGE_CLOSED:W-12`.
- [ ] No alternate route → incident back to `OPEN` + `REPLAN_FAILED:NO_ROUTE`, resource freed (not stuck).
- [ ] Reopen → new proposals may reuse edge (assert route includes it when optimal).
- [ ] Manual: `run --scenario bridge_closure.json` log shows closure tick, affected ASNs, replacement ASNs.
