# Phase 5 / Step 03 — Simulated Network (Delay/Loss/Dup/Partition)

## Goal

Deterministic chaos: same seed → same drops/delays.

## Files

- `backend/app/communications/simulated_network.py`
- `backend/tests/test_network_partition.py`
- Scenario config: `network:{delay_ticks, loss_rate, dup_rate, partitions:[{agents, from_tick, to_tick}]}`

## Implementation

`SimulatedNetwork(seed)`: `can_deliver(sender, recipient, tick)`, `delivery_tick(msg)` (created+delay+jitter), `maybe_drop/dup/reorder` via seeded RNG. Partitions: pairs in partition map → held in gateway queue (not dropped — retryable). Log `PARTITION_HOLD`. Duplication: deliver same `message_id` twice (dedup proves safety). Reorder: release higher-tick message first when delays overlap.

## What to test

- [ ] Fixed seed → identical drop/delay pattern twice.
- [ ] Loss run: some messages `QUEUED→EXPIRED` or retried; log shows attempts.
- [ ] Dup run: zero double-transitions (dedup test with network dup enabled).
- [ ] Out-of-order: newer state + older state both arrive → older ignored via version check (or flagged — assert no regression to stale).
