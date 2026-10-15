# Phase 1 / Step 01 — Repo Scaffold + Tooling

## Goal

Empty-but-runnable monorepo so every later step has a place to land. No business logic yet.

## Files to create

```
backend/pyproject.toml
backend/.env.example
backend/app/__init__.py
backend/app/simulation/__init__.py
backend/tests/__init__.py
scenarios/.gitkeep
README.md (update)
```

`pyproject.toml` deps: `fastapi`, `pydantic>=2`, `networkx`, `pytest`, `ruff` (or black+isort). Python `>=3.11`.

`.env.example`: `DATABASE_URL=postgresql://...`, `SIM_SEED=42`.

## Implementation

1. Create dirs per `00-overview.md` target layout, but only `simulation/__init__.py` + `tests/__init__.py` for now. Do NOT pre-create agents/dispatch/comms files.
2. `pyproject.toml` with `[project]`, `[tool.pytest.ini_options] testpaths=["tests"]`, `[tool.ruff]`.
3. Verify `python -c "import sys; print(sys.version)"` and `pytest --collect-only` runs (0 tests, exit 0).

## What to test

- [ ] `pip install -e backend/` (or `pip install -r`) succeeds on fresh venv.
- [ ] `pytest backend/tests -q` → `no tests ran`, exit code 0 (not import error).
- [ ] `grep -r "fastapi" backend/app/simulation/` returns nothing.
- [ ] Manual: `ls backend/app frontend mobile scenarios` matches target layout placeholders.
