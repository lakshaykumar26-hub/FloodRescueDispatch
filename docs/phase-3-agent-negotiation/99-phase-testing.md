# Phase 3 — Phase Testing (gate)

- [ ] Same scenario runs under either strategy with zero invariant violations.
- [ ] Deterministic winners per strategy under fixed seed.
- [ ] Every bid rejection has a reason; alternatives logged per assignment (for dashboard).
- [ ] `ACKNOWLEDGED` distinct from `COMMITTED` in history.
- [ ] No agent reads global `World` directly (grep `world\.edges` inside `agents/` → only via passed copies; belief-isolation test green).
- [ ] `pytest backend/tests/test_negotiation.py backend/tests/test_dispatch.py backend/tests/test_safety_invariants.py -q` green.
