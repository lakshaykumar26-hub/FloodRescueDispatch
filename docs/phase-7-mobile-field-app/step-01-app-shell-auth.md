# Phase 7 / Step 01 — App Shell + Auth + Read-Only Missions

## Goal

Signed-in device bound to one resource sees its mission. No writes yet.

## Files

- `mobile/app/*` (Expo Router: sign-in, mission, route, status, report, sync), `mobile/services/api.ts`, `mobile/types/*`, `mobile/app.json`
- Backend: `GET /api/devices/me/mission` (role-scoped: own assignment only), device auth (token in `expo-secure-store`)

Flow: sign-in → store token securely → `device_id↔BOAT-xx` binding → fetch mission + route + hazards → show connection state (backend probe, not just Wi-Fi icon).

## What to test

- [ ] Sign-in stores token in SecureStore (grep: no token in SQLite/settings files).
- [ ] Device A cannot fetch device B's mission (403 or scoped empty).
- [ ] Backend down + Wi-Fi on → UI shows unreachable (probe fails), not "connected".
- [ ] Manual: airplane on → sign-in cached state explains login needs connectivity.
