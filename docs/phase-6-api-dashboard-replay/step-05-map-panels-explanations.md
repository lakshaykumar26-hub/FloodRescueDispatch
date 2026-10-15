# Phase 6 / Step 05 — Map + Panels + Explanations + Timeline

## Goal

Explain current situation + why decisions changed (§13).

## Files

- `frontend/components/map/*`, `incidents/*`, `resources/*`, `timeline/*`, decision explanation panel

Features:
- Map: roads vs waterways, open/closed/disputed styles, boats/teams/incidents/shelters icons, planned routes + changed-route highlight, failed/disconnected badges.
- Panels: incident (urgency, wait, demand, status), resource (status, mission, ETA, capacity, fuel), shelter (occupancy/reservations/remaining).
- Explanation per assignment: selected + alternatives with ETA/cost, rejection reasons, safety checks applied, stale/unavailable info note.
- Timeline: scrub ticks, click event → map + explanation sync.

## What to test

- [ ] Inject closure → map edge turns closed, affected route redraws, explanation cites `EDGE_CLOSED` + alternatives.
- [ ] Failed boat badge + recovery assignment linked in panel.
- [ ] Disputed edge styled distinctly with both reports listed.
- [ ] Timeline scrub to tick T shows state at T (cross-check vs `GET state` at replay tick).
- [ ] Manual walkthrough: follow combined-disaster tick 40 entirely in UI.
