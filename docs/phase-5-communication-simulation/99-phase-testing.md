# Phase 5 — Phase Testing (gate)

- [x] Duplicate messages cause no duplicate transitions.
- [x] Expired offers rejected; delayed/out-of-order handled (version guard).
- [x] Partitioned agents get no global updates (belief-freeze test).
- [x] Reconnect detects stale/conflicting state; reconciliation logged with outcome code.
- [x] Unacked ≠ accepted everywhere in logs.
- [x] `pytest backend/tests/test_comms.py backend/tests/test_network_partition.py backend/tests/test_safety_invariants.py -q` green.
- [x] Combined disaster with BOAT-03 partitioned ticks 40–60: queued (not "received"), reconciled on return.
