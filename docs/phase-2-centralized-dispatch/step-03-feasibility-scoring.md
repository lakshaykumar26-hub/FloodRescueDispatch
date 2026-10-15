# Phase 2 / Step 03 — Feasibility + Bid Scoring

## Goal

Separate hard feasibility (reject) from soft cost (rank). Implements `C(r,i)=w_t*T+w_r*R+w_f*F+w_o*O`.

Spec §§7.3, 10.

## Files

- `backend/app/dispatch/bid_evaluator.py`
- `backend/app/dispatch/route_replanner.py` (thin wrapper over routing for shelter-leg alternatives — full use Phase 4)
- Config: weights in scenario JSON (`weights:{w_t,w_r,w_f,w_o}`), defaults `1.0,2.0,0.5,0.3`.

## Implementation

1. `check_feasible(world, incident, resource, shelter, route) -> (bool, reason)`:
   - mode compatible, resource AVAILABLE, route valid (no closed), `fuel>=eta+reserve`, `passengers<=capacity`, `shelter.remaining>=people`, assignment not expired/cancelled.
   - Any fail → `(False, CODE)` e.g. `FUEL_INSUFFICIENT`, `SHELTER_FULL`, `EDGE_CLOSED:W-12`, `MODE_MISMATCH`, `RESOURCE_UNAVAILABLE`.
2. `score(...) -> float`: `T=eta_ticks`, `R=sum(edge.risk)`, `F=waiting_ticks` fairness nudge (long-waiting cheaper), `O=0` for now (opportunity cost arrives Phase 3 — keep param, document as 0).
3. Never fold a hard fail into cost. Feasibility runs first; only feasible bids are scored.

## What to test

- [ ] Each hard-fail code unit-tested: closed edge, low fuel, over-capacity, full shelter, failed boat, mode mismatch → `feasible is False` + exact code.
- [ ] Scoring: two feasible boats, nearer one wins with default weights; bump `w_r` high → safer-but-longer boat wins (proves weights matter).
- [ ] Manual: print rejected proposals with reasons for baseline — every rejection has a code, none is bare `INFEASIBLE`.
