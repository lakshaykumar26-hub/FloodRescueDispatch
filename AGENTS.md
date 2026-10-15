# AGENTS.md — Flood Rescue Dispatch

This file instructs coding agents working in this repo. Read `docs/CONVENTIONS.md` and `docs/README.md` before writing code.

## 1. What this project is

Time-stepped, explainable flood-rescue **simulation + prototype** (not a real emergency system):
- Python/FastAPI backend: simulation engine, agents, dispatch, routing, comms gateway, evaluation, persistence.
- Next.js web dashboard for command staff.
- Expo React Native mobile app for field responders (offline-first).
- Synthetic data only. No live operational feeds.

Source of truth: `flood_rescue_dispatch_mvp_architecture_web_mobile_v2.md`.

## 2. Repo layout (target)

```
backend/app/{api,simulation,agents,dispatch,routing,communications,evaluation,persistence,schemas}
backend/tests/
scenarios/*.json
frontend/ (Next.js + TS + Tailwind + React Leaflet + Recharts)
mobile/ (Expo + RN + TS + expo-sqlite + NetInfo)
docs/phase-N-*/step-*.md
```

Create modules as needed per phase. Do NOT generate empty stub files for everything upfront.

## 3. Hard rules

1. **Simulation engine independent:** `backend/app/simulation/` must not import FastAPI, DB, or frontend code. API handlers call the engine, never reimplement scheduling.
2. **Separate global state vs local belief:** `world.state` ≠ `agent.local_belief`. An offline boat must NOT see global updates magically. Route all inter-agent info through messages.
3. **Safety validator is authoritative:** every proposal passes `safety_validator.py` before commit. Hard constraints (closed edge, failed resource, capacity, fuel reserve, shelter overflow, expired/cancelled) = REJECT, never a score penalty.
4. **Deterministic ticks:** use `tick` ints for simulation order. Wall-clock timestamps only for audit/display. Fixed `random_seed` per scenario. Document tick ordering (e.g. closure at tick 40 applies before movement in tick 40).
5. **Assignment lifecycle explicit:** `PROPOSED -> COMMITTED -> ACKNOWLEDGED -> IN_PROGRESS -> COMPLETED`, plus `REJECTED/EXPIRED/CANCELLED/REQUIRES_RECONCILIATION`. Unique `assignment_id`, `version`, owner, history with reasons.
6. **Comms honesty:** never conflate `sent=delivered=acked=accepted=completed`. Persist outbox, track ACK separately, dedup by `message_id`/`event_id`, enforce expiry (`expires_at_tick`), version checks, reconciliation after reconnect.
7. **Mobile offline-first:** store locally first, show `PENDING_SYNC` vs acknowledged. Same `event_id` on retry (idempotent). Do NOT let disconnected phone commit global assignments. Stale route = show age + warning.
8. **No premature infra:** no Kafka/Redis/K8s/microservices/LLM. One FastAPI app, one DB (Supabase/Postgres), replaceable comm adapters.
9. **Synthetic only:** 25 nodes / 25 road / 20 water / 12 incidents / 5 boats / 5 teams / 4 shelters baseline. Real maps/radios only behind adapters with offline strategy docs.
10. **Audit everything:** proposals, commits, cancellations, reassignments, message retries, report conflicts each get a reason + tick + actor.

## 4. How to work

- Follow the current phase folder in `docs/phase-N-*/` in step order (`step-01`, `step-02`, …). Each step ends with **What to test** — run it before moving on.
- Small diffs. Prefer editing existing files. Don't create files outside the step's scope.
- Validate: `pytest backend/tests -q`, `mypy`/`ruff` if configured, `tsc --noEmit` for frontend/mobile.
- Add/extend a test for every invariant or transition you touch (see `docs/.../99-phase-testing.md`).
- If a finding contradicts this file, stop and surface it; evidence wins.

## 5. Commands (expected)

```bash
# backend
python -m venv .venv && pip install -e backend/
pytest backend/tests -q

# frontend
cd frontend && npm install && npm run dev
# mobile
cd mobile && npm install && npx expo start
```

If these fail, check phase README for the current scaffold state — early phases are headless (no frontend/mobile).

## 6. Security / data

- Validate all API/message payloads with Pydantic. Auth devices, role-scope mobile reads (only own mission + relevant hazards).
- TLS where transport supports it; LAN ≠ trusted. Secrets in `expo-secure-store` / `.env`, never in SQLite plain settings or git.
- Treat device location + reports as untrusted until validated. Cap local cache; clear on decommission.

## 7. Definition of done per phase

See `00-overview.md` in each phase folder. Do not mark a phase done until its `99-phase-testing.md` checklist passes.
