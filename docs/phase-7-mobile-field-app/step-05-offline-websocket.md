# Phase 7 / Step 05 — Connectivity vs Reachability + WS + Drills

## Goal

Honest connection UI; live updates while reachable; proven offline behavior.

## Files

- `mobile/services/connectivity.ts` (NetInfo + gateway probe), WS subscribe, `mobile/state/*`

Triggers: launch/foreground, NetInfo change, user retry, ack-more-to-send. Background sync best-effort only (document; never rely for critical updates). WS while reachable for state pushes; outbox remains source of truth for uploads.

Drills: (a) offline record→online sync, (b) stale mission flag, (c) cancelled-mission conflict, (d) dup/out-of-order reconnect, (e) permission-denied flow, (f) tile-less map.

## What to test

- [ ] Wi-Fi on + backend stopped → status UNREACHABLE (not connected).
- [ ] Offline 10 min → mission screen shows data age + stale warning.
- [ ] Reconnect storm (dup + reorder) → no dup transitions, order resolved by version.
- [ ] Background behavior documented + tested as best-effort (no critical path depends on it).
- [ ] Manual drills a–f pass on a real device (Expo dev build) — record results in PR.
