# Phase 4 — Phase Testing (gate)

- [ ] Bridge closure reroutes or explicitly fails with reason; closed edge never committed.
- [ ] Failed boat with passengers triggers recovery; passengers never deleted or double-counted.
- [ ] Full shelter never over-reserved (`occupancy+reservations<=capacity` every tick in overflow run).
- [ ] Conflicting reports both preserved; disputed edge routed conservatively with explanation.
- [ ] Combined disaster (tick 40) under both strategies: auditable cancel→replan chains, no silent violations.
- [ ] `pytest backend/tests/test_replanning.py backend/tests/test_reports.py backend/tests/test_safety_invariants.py -q` green.
