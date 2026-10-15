# Phase 7 / Step 03 — SQLite Cache + Outbox

## Goal

Survive force-close; distinguish stored vs sent vs acked.

## Files

- `mobile/db/{sqlite.ts,migrations/*}`, `mobile/services/sync-engine.ts` (queue half)

Tables: `cached_missions, cached_routes, cached_hazards, local_events, outbox, inbox, sync_state, device_settings`. Outbox row: `{event_id (stable UUID), device_id, assignment_id, type, local_sequence, created_at, base_assignment_version, sync_status: PENDING|SENT|ACKED|REJECTED, attempts}`. `inbox`: processed server message IDs (dup guard).

Writes: status taps + hazard submits → `local_events` + `outbox` in one transaction → UI `PENDING_SYNC`.

## What to test

- [ ] Record event offline → force-close → reopen → event still `PENDING` with same `event_id` + sequence.
- [ ] 10 rapid taps → 10 rows, sequences 1..10, no gaps/dups.
- [ ] `inbox` redelivery of same server msg → applied once.
- [ ] Manual: SQLite inspect shows cache + outbox rows with versions.
