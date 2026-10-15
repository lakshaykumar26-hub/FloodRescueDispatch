# Phase 3 / Step 01 — Base Agent + Local Beliefs

## Goal

Agents as plain Python classes with private beliefs that can go stale. No global peeking.

## Files

- `backend/app/agents/base_agent.py`
- `backend/tests/test_negotiation.py` (new; belief-isolation test)

## Implementation

1. `BaseAgent(id, kind)`: `{id, kind, local_belief: {edges:{id:status}, assignments:[...], belief_version:int}, inbox:[]}`. `update_belief(message)` only mutates what the message carries.
2. Rule enforced by code review + test: agents receive `World` snapshots ONLY via `sense()` that copies explicitly passed fields ( Phase 3 sense = full copy while comms perfect; Phase 5 restricts delivery). Never pass live `World` reference — pass `copy.deepcopy` subset.
3. `belief_version` bumps on every applied message; bids carry it (spec §7.2 example bid).

## What to test

- [ ] Mutate global `World` (close edge) without sending message → agent `local_belief` still shows old status (proves separation).
- [ ] `update_belief` with newer version overwrites; older version ignored (log `STALE_BELIEF_IGNORED`).
- [ ] Manual: print belief vs world after injected closure — differ until message delivered.
