# Phase 6 / Step 06 — Comms Monitor + Controls + Metric Charts

## Goal

Operate the sim and compare strategies from the UI.

## Files

- `frontend/components/communications/*`, `metrics/*`, controls bar

Features:
- Comms: connected/disconnected agents, queue length + per-message status, delay/retry/expiry/partition badges, reconciliation status after reconnect.
- Controls: play/pause/step/speed, inject predefined events (closure, failure, overflow, new incident, partition), strategy select, replay button.
- Metrics: Recharts for service time, unmet, idle, violations, fairness gap, recovery/latency (definitions §14; computation Phase 8 — display API values now).

## What to test

- [ ] Partition inject → boat shows disconnected, queue grows, WS keeps streaming; heal → reconciliation badge + stale-route warning clears after re-ack.
- [ ] Each control works: pause halts ticks, step advances exactly 1, speed changes rate, strategy select starts correct engine.
- [ ] Metrics compare view renders centralized vs negotiation side-by-side (values from API).
- [ ] Manual: full demo script — baseline → closure → failure → partition → heal → replay — without console errors.
