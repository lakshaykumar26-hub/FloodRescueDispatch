# Phase 5 / Step 05 — Wire Agents Through Gateway

## Goal

Remove every direct global-read shortcut; engine delivers only due messages per tick (§9 order step 4–5).

## Files

- `engine.py` (deliver-due → update-beliefs before movement), all `agents/*.py`, `negotiation_scheduler.py` (async-ready send points)

## Implementation

1. Replace direct `world` reads in agents with `inbox` processing: engine per tick pulls `gateway.due(tick)` → `agent.update_belief(msg)` → `tracker.mark_delivered` → agent acts → new `gateway.send`s queued.
2. Add ` specialty test`: instrument agent to record `world_tick_at_read`; assert partitioned agent's belief tick < global tick during partition.
3. Document remaining in-process simplifications (shared memory queues stand in for radios; adapters Phase 8).

## What to test

- [ ] Partitioned agent receives zero application messages during partition (inbox empty), beliefs frozen (snapshot belief before/during/after).
- [ ] Post-wire full baseline still completes (no deadlock from missing messages).
- [ ] `grep -rn "world\.edges\[" backend/app/agents/` → no direct global reads outside `sense()` copy helper.
