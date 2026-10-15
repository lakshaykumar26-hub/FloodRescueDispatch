# Flood Rescue Dispatch

Time-stepped, explainable flood-rescue simulation + prototype (synthetic data only;
not a real emergency system). See `docs/README.md` for the build plan and
`AGENTS.md` for agent working rules.

## Layout (target)

- `backend/app/simulation/` — deterministic simulation engine (no FastAPI/DB imports)
- `backend/app/routing/` — graph + pathfinding (pure functions over `World`)
- `backend/app/{agents,dispatch,communications,evaluation,persistence,schemas,api}/` — later phases
- `backend/tests/` — pytest suite (`pytest backend/tests -q` from repo root)
- `scenarios/` — synthetic scenario JSON files
- `frontend/`, `mobile/` — later phases (6, 7)

## Quick start (Phase 1, headless)

```bash
python -m venv .venv && .venv/Scripts/activate
pip install -e backend/
pytest backend/tests -q
python -m backend.app.simulation.run --scenario scenarios/baseline.json
```

## Environment

| File | Purpose |
|---|---|
| `backend/.env.example` | All backend vars with defaults (copy to `backend/.env`) |
| `backend/.env` | Local backend dev (gitignored). Empty `DATABASE_URL` → sqlite file at `backend/data/flood_rescue.db`, no Postgres needed |
| `frontend/.env.example` | Frontend vars template |
| `frontend/.env.local` | Local dashboard dev (gitignored): `NEXT_PUBLIC_API_URL` must match the backend `PORT` |

Backend vars: `DATABASE_URL`, `SIM_SEED` (last-resort seed), `HOST`/`PORT`
(`py -m backend.app.main` serves with these), `CORS_ORIGINS` (comma-separated),
`SNAPSHOT_EVERY`. Real env vars always override `.env` values; parsing lives in
`backend/app/config.py` (stdlib only, no new dependency).

```bash
# backend API (http://localhost:8000, Swagger at /docs)
py -m backend.app.main

# dashboard (http://localhost:3000) — needs NEXT_PUBLIC_API_URL pointing at the API
cd frontend && npm install && npm run dev
```
