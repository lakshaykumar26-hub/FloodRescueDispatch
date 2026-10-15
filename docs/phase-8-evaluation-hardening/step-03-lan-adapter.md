# Phase 8 / Step 03 — Local Wi-Fi / LAN Adapter

## Goal

Backend on LAN laptop + phone on same Wi-Fi, internet cut, app still syncs (§16 Phase 7 steps 1–2, §18.8 step 8).

## Files

- `backend/app/communications/wifi_adapter.py`, mobile gateway-URL setting, `docs/lan-test-log.md`

Implementation: adapter implements same `send/due` interface as simulated network (swap via config, not code fork). TLS or documented exception on LAN; LAN ≠ trusted (auth still required). Mobile: manual gateway URL + reachability probe + retry.

Procedure: start backend on LAN IP → connect phone to same AP → disable WAN → create mission → offline-record → sync → partition drill → record results.

## What to test

- [ ] With WAN disconnected: mission fetch + event sync + WS ticks all work over LAN.
- [ ] Kill backend mid-sync → outbox retains PENDING, no phantom ACK.
- [ ] Duplicate/retry over real LAN → no double transitions.
- [ ] Manual: attach `lan-test-log.md` (devices, IPs, WAN-cut proof, drill results).
