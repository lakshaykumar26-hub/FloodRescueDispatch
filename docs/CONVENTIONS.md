# Conventions — Flood Rescue Dispatch

Companion to `../AGENTS.md`. Follow these unless a phase step explicitly overrides them.

## 1. Naming

- IDs: `SIM-001`, `INC-08`, `BOAT-03`, `TEAM-02`, `SHELTER-02`, `ASN-00031`, `MSG-00142`, `RPT-018`, `EVT-DEVICE-0031`. Unique, stable, never reused.
- Files: `snake_case.py` (backend), `kebab-case.tsx` or `camelCase.ts` per existing scaffold (frontend/mobile) — match the folder's current style.
- Tests: `backend/tests/test_<area>.py` (`test_routing.py`, `test_dispatch.py`, `test_safety_invariants.py`, `test_network_partition.py`, `test_replay.py`, `test_boat_lifecycle.py`).
- Scenarios: `scenarios/<name>.json` (`baseline.json`, `bridge_closure.json`, `boat_failure.json`, `shelter_overflow.json`, `combined_disaster.json`).

## 2. Python backend

- Python 3.11+, FastAPI + Pydantic v2, NetworkX, pytest, `asyncio` for messaging.
- Layout: `api/`, `simulation/` (`engine.py`, `world.py`, `clock.py`, `event_scheduler.py`, `state_manager.py`, `snapshots.py`), `agents/`, `dispatch/`, `routing/`, `communications/`, `evaluation/`, `persistence/`, `schemas/`.
- Rules:
  - `simulation/` has zero imports from `api/`, `persistence/`, frontend.
  - All payloads validated by `schemas/` + `communications/models.py`.
  - Tick math in `clock.py` only. Never use `time.now()` for ordering.
  - State transitions via explicit methods that append to history (reason + tick + actor). No silent mutation.
  - Cost function: `C(r,i)=w_t*T + w_r*R + w_f*F + w_o*O` with configurable weights; safety = reject, not penalty.

## 3. TypeScript (frontend + mobile)

- Strict TS (`strict: true`), `tsc --noEmit` clean. Shared shapes mirror Pydantic schemas; keep `frontend/lib/types.ts` and `mobile/types/` in sync with backend `schemas/`.
- Frontend: Next.js App Router, Tailwind, React Leaflet (synthetic toggle allowed), Recharts. Hooks in `hooks/`, API in `lib/`.
- Mobile: Expo Router, `expo-sqlite` migrations in `db/migrations/`, services in `services/` (`api.ts`, `sync-engine.ts`, `connectivity.ts`, `location.ts`). Never store secrets in SQLite.

## 4. Simulation + graph

- `G_t=(V,E_t)`. Edge: `{edge_id, from_node, to_node, mode: road|water, travel_time, status: open|closed|disputed, risk_level 0-1, capacity, last_updated_tick}`.
- Modes: boats → water only; ground teams → road only; multi-stage via transfer points. Fuel must satisfy reserve policy. Shelter: `occupancy + reservations <= capacity` (track separately).
- Incident lifecycle: `OPEN → ASSIGNED → IN_PROGRESS → SERVED | CANCELLED | UNRESOLVED`. Boat lifecycle: `AVAILABLE → ASSIGNED → EN_ROUTE_TO_INCIDENT → RESCUING → TRANSPORTING_TO_SHELTER → RECOVERY → AVAILABLE` (+ `UNAVAILABLE/FAILED/STRANDED/RETURNING/MAINTENANCE`).
- Cancel routing: `cancel()` end state is `AVAILABLE` from every active state, but no direct `RESCUING→AVAILABLE` edge exists by design — mid-rescue boats route via `RETURNING`. Conflict rejections cite the winning `proposal_id` (`RESOURCE_CONFLICT:WINNER=<proposal_id>`); the `proposal_id→assignment_id` link lives in each `COMMITTED` log entry.
- Engine tick order (document any deviation): advance clock → apply flood/infra events → update world → deliver due messages → update local beliefs → move resources on valid routes → update incidents/shelters → detect invalid commitments → cancel/suspend/mark `REQUIRES_RECONCILIATION` → propose/bid → resolve + safety-validate → commit → queue outbound → record events/metrics/snapshots → publish WS.
- Seeds: every scenario JSON has `random_seed`, `flood_progression`, `speeds`, `comm_reliability`, `shelter_capacity`.

## 5. Comms + sync

- Envelope: `{message_id, type, sender_id, recipient_id, simulation_id, created_at_tick, expires_at_tick, version, payload}`. Types: `INCIDENT_CREATED, ASSIGNMENT_OFFER, ASSIGNMENT_ACCEPTED, ASSIGNMENT_CANCELLED, BOAT_POSITION, BOAT_STATUS_CHANGED, HAZARD_REPORTED, SHELTER_CAPACITY_CHANGED, MESSAGE_ACK`.
- Gateway: validate → priority queue → persist → deliver → track ACK → retry → dedup → expiry → reconcile → audit.
- Mobile outbox event: `{event_id, device_id, assignment_id, type, local_sequence, created_at, base_assignment_version, sync_status: PENDING|ACKED|REJECTED}`. Reuse `event_id` on retry. Server replies per-event: `ACCEPTED|DUPLICATE|REJECTED_STALE|REJECTED_INVALID|REQUIRES_RECONCILIATION`.
- Reachability ≠ connectivity: NetInfo `connected` does NOT imply backend reachable — probe gateway separately.
- Reports stored independently: `{report_id, subject_id, claim, source, observed_at_tick, received_at_tick, confidence, verification_status}`. Conflict → keep both, mark disputed, conservative routing, explain.

## 6. API + persistence

- REST: `POST /api/simulations`, `POST .../{id}/start|pause|step`, `GET .../{id}/state|events|assignments|metrics|communications`, `POST .../{id}/events|replay`. WS: `/ws/simulations/{id}`.
- Handlers are thin: validate → call engine/gateway → return. No dispatch logic in routes.
- Postgres/Supabase tables: `simulation_runs, locations, network_edges, incidents, resources, shelters, simulation_events, assignments, assignment_history, communication_messages, reports, state_snapshots, simulation_metrics`. Every row carries `simulation_id + tick`. Never overwrite `assignment_history`; snapshots must suffice to restore/replay.
- Don't write every micro-mutation; periodic snapshots + meaningful event log.

## 7. Testing

- Every step ends with **What to test**. Run `pytest -q` + manual check before next step. Phase gates in `99-phase-testing.md` must pass.
- Determinism: same seed → same event order, same bid winner. Reordering/dup/partition tests must use fixed seeds.
- Frontend/mobile: synthetic graph must render with no network (no tile dependency for MVP). Kill-app-reopen must preserve outbox. Denied location permission must not break mission flow.

## 8. Git + docs

- Branch per step: `phase-N/step-K-short-name`. Commit with `phaseN-stepK: verb detail`.
- Update `docs/README.md` checklist when a phase completes. Keep decision reasons in code + `assignment_history`, and surface them in dashboard/mobile UI (selected vs alternatives, safety checks, stale info).
