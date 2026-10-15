# Phase 8 / Step 02 — Full Scenario Matrix + CI

## Goal

All §14 scenarios green on every push.

## Files

- `scenarios/*.json` (all 10: baseline, simultaneous, bridge_closure, boat_failure, shelter_overflow, partition, contradictory_reports, duplicate_messages, reconnection, combined_disaster)
- `.github/workflows/ci.yml` (pytest + ruff + mypy + tsc + replay determinism check)

Each scenario asserts its focus (contention/partition/idempotency/reconcile/combined). CI fails on: test failure, lint, `tsc`, nondeterministic replay, closed-edge commit, over-reserve.

## What to test

- [ ] `pytest backend/tests -q` full suite green (routing, lifecycle, dispatch, safety, partition, replay, reports, metrics, api, persistence).
- [ ] Matrix script runs all 10 × both strategies, zero invariant violations, summary table saved.
- [ ] CI passes on a clean checkout (document env: Python, Node, Supabase test URL or sqlite fallback).
- [ ] Manual: break an invariant locally → CI red with the right test name.
