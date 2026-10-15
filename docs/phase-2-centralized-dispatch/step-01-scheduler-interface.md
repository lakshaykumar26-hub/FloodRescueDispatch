# Phase 2 / Step 01 — Scheduler Interface

## Goal

One contract both centralized (now) and negotiation (Phase 3) implement, so strategy comparison is fair.

## Files

- `backend/app/dispatch/scheduler_interface.py`
- `backend/tests/test_dispatch.py` (skeleton: interface conformance test)

## Implementation

```python
class ProposedAssignment(TypedDict):  # or Pydantic
    incident_id: str; resource_id: str; resource_kind: str
    shelter_id: str | None; route_edge_ids: list[str]
    eta_ticks: int; cost: float; reasons: list[str]

class Scheduler(Protocol):
    strategy: str  # "centralized" | "negotiation"
    def propose(self, world: World, tick: int) -> list[ProposedAssignment]: ...
    def commit(self, world: World, proposal: ProposedAssignment, tick: int) -> Assignment: ...
```

- `Assignment`: `{assignment_id, version:1, incident_id, resource_id, shelter_id, route, status: PROPOSED|COMMITTED|..., history:[{tick,from,to,reason,actor}]}`.
- Document: schedulers are pure decision-makers; they never mutate movement or shelters directly — `commitment_manager` + `state_manager` do that after safety validation.

## What to test

- [ ] Import both (centralized now, negotiation stub later) as `Scheduler` without code change in engine.
- [ ] `propose()` returns list (possibly empty), never raises on empty world (0 incidents → `[]`).
- [ ] Manual: type-check `centralized_scheduler.py` satisfies `Protocol` (`mypy` or `isinstance` via runtime_checkable).
