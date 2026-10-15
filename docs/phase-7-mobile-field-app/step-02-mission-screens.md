# Phase 7 / Step 02 — Mission / Route / Status / Hazard Screens

## Goal

All §18.2 screens working read-mostly against cached data.

## Files

- `mobile/features/missions/*`, `reports/*`, `communications/*`, `components/*`

Screens:
1. My mission: ASN id/version, incident, destination, status (`COMMITTED/ACKNOWLEDGED/IN_PROGRESS/PENDING_SYNC/CANCELLED/COMPLETED`), last-sync time, stale banner past freshness limit.
2. Route+situation: last-known route + hazards with age+source; `react-native-svg` synthetic graph (no tiles); optional device dot only with permission, manual fallback otherwise; never present stale route as current.
3. Mission status: departure/arrival/rescue/passengers/destination/recovery buttons with confirm for critical ones.
4. Hazard form: node/edge picker, type, confidence, observation time; photo explicitly deferred.
5. Connection/sync: reachability, pending count, last success, retry, per-event error reasons.

## What to test

- [ ] Location permission denied → mission + manual updates still work (no crash, no blank map).
- [ ] Stale mission (>freshness limit or offline) shows age warning banner.
- [ ] Synthetic SVG renders with zero network (device airplane mode).
- [ ] Manual: walk each screen offline — all render cached data with age labels.
