# Phase 8 — Evaluation + Hardening + Optional Physical Comms

Goal: reproducible strategy comparison, full scenario matrix, LAN adapter proven, radio only as labeled experiment.

Source spec: §§14, 16 (Phase 7), 17–19.

## Steps

1. `step-01-metrics-runner.md` — metrics + fairness + multi-seed runner.
2. `step-02-scenario-matrix-ci.md` — 10-scenario suite + CI gate.
3. `step-03-lan-adapter.md` — local Wi-Fi/LAN with internet disconnected.
4. `step-04-radio-optional-hardening.md` — radio stub, security/decommission, prototype labeling.

## Done when

Centralized vs negotiation compared on identical seeds × N runs; LAN test passes with internet cut; radio (if any) behind adapter with documented limits; system still labeled prototype.
