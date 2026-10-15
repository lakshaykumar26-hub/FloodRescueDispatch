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
