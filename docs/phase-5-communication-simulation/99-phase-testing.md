# Phase 5 — Phase Testing (gate)

- [ ] Duplicate messages cause no duplicate transitions.
- [ ] Expired offers rejected; delayed/out-of-order handled (version guard).
- [ ] Partitioned agents get no global updates (belief-freeze test).
- [ ] Reconnect detects stale/conflicting state; reconciliation logged with outcome code.
- [ ] Unacked ≠ accepted everywhere in logs.
- [ ] `pytest backend/tests/test_comms.py backend/tests/test_network_partition.py backend/tests/test_safety_invariants.py -q` green.
- [ ] Combined disaster with BOAT-03 partitioned ticks 40–60: queued (not "received"), reconciled on return.
