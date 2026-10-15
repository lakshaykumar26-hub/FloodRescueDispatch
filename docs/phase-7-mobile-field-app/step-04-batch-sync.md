# Phase 7 / Step 04 — Batch Sync + Idempotency + Conflicts

## Goal

Reliable upload with per-event server verdicts.

## Files

- `mobile/services/sync-engine.ts` (full), backend sync endpoint `POST /api/devices/sync` (batch `{events:[...]}` → per-event `{event_id, result: ACCEPTED|DUPLICATE|REJECTED_STALE|REJECTED_INVALID|REQUIRES_RECONCILIATION, reason, server_version}`)

Rules: reuse same `event_id` on retry (server dedups → `DUPLICATE` counts as success, no double transition). `base_assignment_version` mismatch → `REJECTED_STALE` (client shows conflict, pulls fresh mission, never auto-overwrites server). Only `ACCEPTED/DUPLICATE` clears `PENDING`.

## What to test

- [ ] Upload same batch twice → second all `DUPLICATE`, zero double transitions server-side.
- [ ] Stale-version event (assignment cancelled while offline) → `REJECTED_STALE`, UI flags conflict + shows new state.
- [ ] Partial batch (1 good + 1 bad) → per-event results independent; good clears, bad stays with reason.
- [ ] Manual: offline record 3 events → online sync → 3 ACCEPTED, pending 0, last-sync updates.
