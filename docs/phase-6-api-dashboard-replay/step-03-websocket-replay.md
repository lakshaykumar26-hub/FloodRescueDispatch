# Phase 6 / Step 03 — WebSocket Live + Replay

## Goal

Stream ticks/events and reproduce completed runs exactly.

## Files

- `backend/app/api/simulations.py` (`WS /ws/simulations/{id}`), replay logic in `engine.py`/`snapshots.py`
- `backend/tests/test_replay.py` (full: fixed-seed reproduce + snapshot resume + order)

Protocol: server→client `{tick, state_digest, events:[...], assignments_delta, comms_digest}` each tick; client→server `{action: pause|step|inject}`. Replay: `POST .../replay {from_snapshot_tick?}` re-executes deterministically from snapshot or tick 0 with same seed + recorded injections.

## What to test

- [ ] WS test client receives tick 1..5 in order with matching event counts.
- [ ] Fixed seed replay → identical event order + winners (diff logs).
- [ ] Replay from mid snapshot equals uninterrupted run from that tick on.
- [ ] Metrics computed from recorded data only (recompute after replay matches).
- [ ] Manual: `wscat` connect, see ticks stream; kill + replay → same final summary.
