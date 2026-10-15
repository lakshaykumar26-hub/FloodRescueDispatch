# Docs — Flood Rescue Dispatch Build Plan

Source: `../flood_rescue_dispatch_mvp_architecture_web_mobile_v2.md` (§16 roadmap + §18.8 mobile sequence).

## Build order

| Phase | Folder | Goal | Done when |
|---|---|---|---|
| 1 | `phase-1-simulation-foundation/` | World, graph, clock, state machines; headless run | Sim runs start→finish with no frontend |
| 2 | `phase-2-centralized-dispatch/` | Greedy scheduler + safety validator + commitments | Valid incidents assigned; invalid rejected with reason |
| 3 | `phase-3-agent-negotiation/` | Local beliefs, bids, conflict resolution, shared interface | Same scenario runs under either strategy |
| 4 | `phase-4-dynamic-events-replanning/` | Closures, failures, overflow, conflicting reports, replanning | Disruptions cause auditable replanning, no silent invariant violation |
| 5 | `phase-5-communication-simulation/` | Gateway, simulated network, partitions, reconciliation | Stale beliefs persist offline; reconnect reconciles without erasing conflicts |
| 6 | `phase-6-api-dashboard-replay/` | FastAPI + persistence + WS + Next.js dashboard + replay | Reviewer can follow a disruption and understand why assignments changed |
| 7 | `phase-7-mobile-field-app/` | Expo offline-first mission/route/sync app | Cached mission works offline, syncs idempotently, stale data flagged |
| 8 | `phase-8-evaluation-hardening/` | Metrics, multi-seed experiments, LAN/radio adapters (optional) | Strategy comparison reproducible; physical comms clearly labeled prototype |

## How to use

1. Work phases in order. Inside a phase, work `step-01`, `step-02`, … in order.
2. Each step file ends with **What to test** — do it before moving on.
3. Each phase ends with `99-phase-testing.md` — all boxes must pass to close the phase.
4. Cross-cutting rules: `CONVENTIONS.md`, `../AGENTS.md`.

## Status

- [x] Phase 1 — done: baseline seed 42 → 13/13 served, run ends tick 40 (exit 0); `pytest backend/tests -q` 33 passed (models, routing, lifecycle, engine smoke, snapshot round-trip + restore-continue).
- [x] Phase 2 — done: greedy central scheduler (propose→resolve→feasible→validate→commit) replaced the stub; baseline seed 42 → 13/13 served, 13 COMMITTED, 1 REJECTED (`RESOURCE_CLAIMED:HIGHER_RANK`); all feasible incidents COMMITTED within N=25 ticks; `pytest backend/tests -q` 94 passed (dispatch, bid scoring, commitments, safety invariants).
- [x] Phase 3 — done: negotiation scheduler behind the same `Scheduler` protocol (`--strategy centralized|negotiation`); both strategies seed 42 → 13/13 served, 13 COMMITTED, 0 closed-edge moves, deterministic winners, `ACKNOWLEDGED` distinct from `COMMITTED`; agents decide from local beliefs only (no global-World access); `pytest backend/tests -q` 127 passed.
- [x] Phase 4 — done: invalidation→replan pipeline (shelter swap / in-place reroute / cancel→repropose→commit with `REPLAN_CHAIN`, terminal `REPLAN_FAILED`); recovery `TRANSFER` workflow; append-only reports with conservative `disputed` policy; `combined_disaster.json` tick-40 stress (closure + failure + overflow + urgency-5 arrival + partition note) → 13/13 served both strategies, 0 closed-edge moves, no orphan cancels; `pytest backend/tests -q` 176 passed.
- [x] Phase 5 — done: gateway store-and-forward (queue/ACK/retry/dedup/expiry/priority) + deterministic SimulatedNetwork (delay/loss/dup/partitions) + reconcile (IN_SYNC/STALE_ROUTE/STALE_OWNERSHIP/CONFLICT) + engine wiring (beliefs only via gateway, BOAT-03 40–60 partition queues + reconciles); baseline 13/13 both strategies; `pytest backend/tests -q` 205 passed.
- [ ] Phase 2
- [ ] Phase 3
- [ ] Phase 4
- [ ] Phase 5
- [ ] Phase 6
- [ ] Phase 7
- [ ] Phase 8
