# Phase 2 — Phase Testing (gate)

- [ ] `pytest backend/tests/test_dispatch.py backend/tests/test_safety_invariants.py -q` green.
- [ ] One resource never holds two active assignments (scan all ticks of baseline run).
- [ ] Competing bids resolve deterministically under fixed seed (two runs, diff winners → fail).
- [ ] Every rejected proposal has a machine-readable reason (no bare rejects in log).
- [ ] Cancellation invalidates prior commitment (resource freed, shelter seats released, history appended).
- [ ] Replanning preserves history (cancel + new commit both present, linked by incident_id).
- [ ] Baseline: feasible incidents assigned within N ticks (record N); infeasible (isolated/no-route) remain OPEN with `NO_ROUTE` reason, not silently dropped.
