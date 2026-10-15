# Phase 3 — Agent Negotiation

Goal: decentralized bidding behind the same `Scheduler` interface. Same scenario runs under `--strategy centralized|negotiation`.

Source spec: §§6, 7.2–7.4.

## Steps

1. `step-01-local-beliefs.md` — `base_agent.py`, belief vs global separation.
2. `step-02-resource-agents.md` — incident/boat/team/shelter/report agents + bid generation.
3. `step-03-negotiation-scheduler.md` — request→bid→resolve→validate→commit→ack flow + `negotiation_scheduler.py`.
4. `step-04-strategy-compare.md` — CLI switch, shared-interface parity, determinism.

## Done when

Same `baseline.json` + seed under either strategy produces valid assignments, no invariant violations, deterministic winners, and per-bid reasons auditable.
