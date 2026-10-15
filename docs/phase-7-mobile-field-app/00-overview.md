# Phase 7 — Mobile Field App (Offline-First)

Goal: Expo responder app — cached mission + route + status updates + hazard reports + honest sync (§18).

## Steps

1. `step-01-app-shell-auth.md` — Expo Router, sign-in, device↔resource binding, read-only mission API.
2. `step-02-mission-screens.md` — mission / route-situation (SVG synthetic graph) / status / hazard form / sync screens.
3. `step-03-sqlite-outbox.md` — cached_missions/routes/hazards, local_events, outbox/inbox, sync_state.
4. `step-04-batch-sync.md` — batch upload, idempotent `event_id` reuse, per-event results, conflict UI.
5. `step-05-offline-websocket.md` — NetInfo vs reachability, stale warnings, offline drills, WS while connected.

## Done when

All §18.7 mobile checklist boxes pass; force-close preserves outbox; stale/cancelled assignments flagged, never silently resumed.
