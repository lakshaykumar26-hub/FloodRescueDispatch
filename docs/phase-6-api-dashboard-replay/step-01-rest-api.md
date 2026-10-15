# Phase 6 / Step 01 — REST API

## Goal

Thin validated handlers over engine + gateway. No scheduling logic in routes.

## Files

- `backend/app/main.py`, `backend/app/api/{simulations.py,state.py,incidents.py,assignments.py,events.py,communications.py,metrics.py}`
- Manual via `curl`/Swagger; automated: `backend/tests/test_api.py` (TestClient)

Endpoints (§12): `POST /api/simulations` (from scenario), `POST .../{id}/start|pause|step`, `GET .../{id}/state|events|assignments|metrics|communications`, `POST .../{id}/events` (inject), `POST .../{id}/replay`.

Rules: Pydantic in/out, strategy + seed in create body, inject validates kind/payload, errors carry reason codes.

## What to test

- [ ] `TestClient`: create→start→step×5→state shows tick 5; inject closure → events contains it; assignments non-empty (baseline).
- [ ] Bad inject (unknown edge) → 422 with reason, sim tick unchanged.
- [ ] Pause→step still works (single-step while paused); start→step ordering enforced.
- [ ] Manual: Swagger UI `POST /api/simulations` then `GET state` — JSON matches world schema.
