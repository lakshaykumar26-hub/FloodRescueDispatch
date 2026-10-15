# Phase 7 — Phase Testing (gate, §18.7)

- [ ] Queued event survives force-close/reopen.
- [ ] Repeated upload causes no duplicate transition.
- [ ] UI distinguishes local vs server-acknowledged events.
- [ ] Disconnected app shows cached mission/hazard age.
- [ ] Stale/cancelled assignment rejected or flagged at sync (never silently resumed).
- [ ] Reconnect handles dup + out-of-order.
- [ ] Location denial keeps core flows usable.
- [ ] Synthetic graph works with no tiles.
- [ ] Backend-unreachable detected despite Wi-Fi connected.
- [ ] Background execution treated as best-effort only.
- [ ] `tsc --noEmit` (mobile) clean; `pytest` sync-endpoint tests green.
