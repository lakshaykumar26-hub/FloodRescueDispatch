# Phase 6 — API + Persistence + Dashboard + Replay

Goal: FastAPI + Supabase persistence + WebSocket live view + Next.js dashboard where a reviewer can follow a disruption and understand why assignments changed.

Source spec: §§11, 12, 13.

## Steps

1. `step-01-rest-api.md` — simulations/state/events/assignments/inject/metrics/replay/communications endpoints.
2. `step-02-persistence.md` — Supabase tables, repos, snapshots, seeds.
3. `step-03-websocket-replay.md` — live stream + replay endpoint.
4. `step-04-dashboard-scaffold.md` — Next.js + Tailwind + Leaflet + Recharts shell.
5. `step-05-map-panels-explanations.md` — map, incident/resource panels, decision explanations, timeline.
6. `step-06-comms-monitor-controls-metrics.md` — comms monitor, play/pause/step/inject/strategy, metric charts + compare.

## Done when

Reviewer injects bridge closure in UI, watches reroute on map, and reads why in the explanation panel; replay reproduces the run.
