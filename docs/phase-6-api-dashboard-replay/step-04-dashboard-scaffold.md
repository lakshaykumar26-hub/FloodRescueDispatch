# Phase 6 / Step 04 — Dashboard Scaffold

## Goal

Next.js + TS + Tailwind + Leaflet + Recharts shell wired to the API, with synthetic-graph fallback (no tile dependency blocks MVP).

## Files

- `frontend/app/page.tsx`, `frontend/components/...` (map/incidents/resources/communications/timeline/metrics stubs), `frontend/lib/api.ts`, `frontend/types/index.ts`, `frontend/.env.example` (`NEXT_PUBLIC_API_URL`)

Setup: `create-next-app`, Tailwind, `react-leaflet`, `recharts`. `lib/api.ts` typed client mirroring backend schemas. Synthetic toggle: render nodes/edges as SVG overlay when tiles unreachable (required for offline demo).

## What to test

- [ ] `npm run dev` loads, `tsc --noEmit` clean, no hardcoded localhost in committed code (env var).
- [ ] With backend running: dashboard fetches `/state` and shows tick + counts.
- [ ] With network tiles blocked (devtools offline for tile host): synthetic graph still renders.
- [ ] Manual: create sim from UI, tick counter advances via WS.
