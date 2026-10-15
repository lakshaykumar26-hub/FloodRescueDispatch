# Phase 4 / Step 04 — Contradictory Reports + Conservative Routing

## Goal

Uncertainty as first-class data: keep both claims, route conservatively, explain why.

Spec §9 (reports).

## Files

- `backend/app/agents/report_agent.py` (full), `backend/app/persistence` stub or in-memory `report_store.py` (DB table in Phase 6)
- `backend/tests/test_reports.py`

## Implementation

1. Store: `{report_id, subject_id(edge), claim: OPEN|CLOSED, source, observed_at_tick, received_at_tick, confidence, verification_status: UNVERIFIED|CONFIRMED|SUPERSEDED}`. Never overwrite — append.
2. Belief update: latest observation ≠ auto-truth. Rule: if any `CLOSED` claim with `confidence>=threshold (0.5 default)` and no newer `CONFIRMED OPEN` → edge `disputed` → routing treats as closed for new commits (`allow_disputed=False`), existing routes flagged for review. Log `EDGE_DISPUTED` with both report IDs.
3. Explanation string per decision: `restricted W-12: RPT-018 CLOSED conf 0.9 (BOAT-03@t38) vs RPT-021 OPEN conf 0.4 (TEAM-01@t39) → conservative CLOSED`.
4. Confidence is evidence, not truth — document in code comment + dashboard tooltip (Phase 6).

## What to test

- [ ] Two conflicting reports same edge → both stored, edge `disputed`, new routes avoid it.
- [ ] Later `CONFIRMED OPEN` (authority source) → edge reopens, reason logged.
- [ ] Low-confidence CLOSED alone (0.2 < threshold) → edge stays open but warning logged.
- [ ] Manual: inject conflicting reports, print edge status + explanation string.
