# Phase 5 — Communication Simulation

Goal: all agent coordination flows through a gateway with delay/loss/dup/partition; offline agents hold stale beliefs and reconcile on return.

Source spec: §§8, 10, 17 (comms checklist).

## Steps

1. `step-01-message-models.md` — envelope, types, validation.
2. `step-02-gateway-queues.md` — queue, ACK, retry, dedup, expiry, priority, audit.
3. `step-03-simulated-network.md` — delay/loss/dup/reorder + partitions.
4. `step-04-reconnect-reconciliation.md` — version checks, stale detection, `REQUIRES_RECONCILIATION` flow.
5. `step-05-wire-agents-gateway.md` — route all inter-agent traffic via gateway; kill magic updates.

## Done when

Partitioned agents get no updates, duplicates cause no double-transitions, expired offers rejected, reconnect reconciles without erasing conflicts.
