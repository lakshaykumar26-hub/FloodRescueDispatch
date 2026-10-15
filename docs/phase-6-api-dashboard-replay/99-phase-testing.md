# Phase 6 — Phase Testing (gate)

- [ ] Reviewer can trigger a disruption in UI and explain the reassignment (map + reasons + alternatives).
- [ ] Replay preserves event order; snapshots restore relevant state; fixed seed reproduces behavior.
- [ ] Comms monitor shows queue/delay/retry/expiry/partitions + reconciliation truthfully.
- [ ] API + WS + persistence integration green: `test_api.py`, `test_replay.py` (full), `test_persistence.py`.
- [ ] Dashboard works with tiles blocked (synthetic fallback) and `tsc --noEmit` clean.
