# Phase 8 / Step 01 — Metrics + Fairness + Experiment Runner

## Goal

§14 metrics from recorded data with precise milestone definitions.

## Files

- `backend/app/evaluation/{metrics.py,fairness.py,experiment_runner.py}`
- `backend/tests/test_metrics.py`

Metrics: time-to-service (define milestone: `SERVED` = people at shelter, log separately `ARRIVED_AT_INCIDENT` vs `DELIVERED_TO_SHELTER`), unmet, idle, route violations, fairness gap `max_n(avgT_n)-min_n(avgT_n)` + unmet-by-neighborhood guard, recovery time, assignment/message latency, queue length, reconciliation time. `experiment_runner`: N seeds × both strategies, identical scenarios, output comparison table + charts data for dashboard.

Rule: scheduler must not game averages by leaving hard incidents unserved — always report unmet alongside means.

## What to test

- [ ] Hand-computed 3-incident fixture matches `metrics.py` output exactly.
- [ ] Fairness gap test: skewed service → gap >0; unmet-heavy run flagged even if mean looks good.
- [ ] Same seed rerun → identical metrics JSON.
- [ ] Manual: `run-compare --scenario baseline --seeds 5` prints table; negotiation vs centralized deltas sane.
