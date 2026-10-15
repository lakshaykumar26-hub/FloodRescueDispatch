# Phase 5 / Step 02 — Gateway (Queue/ACK/Retry/Dedup/Expiry)

## Goal

Store-and-forward hub with honest delivery states.

## Files

- `backend/app/communications/{gateway.py,message_queue.py,delivery_tracker.py,deduplicator.py}`
- `backend/tests/test_comms.py` (gateway cases)

## Implementation

1. `gateway.send(msg)`: validate → persist (in-memory now, DB table Phase 6) → priority enqueue (safety-critical first: CANCEL, SHELTER_CAPACITY, HAZARD over telemetry) → attempt delivery via network adapter.
2. `delivery_tracker`: per-message `{QUEUED, DELIVERED, ACKED, EXPIRED, REJECTED}` + attempts log. ACK tracked separately from acceptance. Unacked ≠ accepted.
3. `deduplicator`: seen `message_id` set → redelivery returns `DUPLICATE` without re-applying transition.
4. Retry: eligible (non-expired, ack-missing) requeued on tick or reconnect. Expired (`tick>expires_at_tick`) → `EXPIRED`, never delivered.
5. Audit: every send/deliver/ack/retry/expire/dedup appended to log.

## What to test

- [ ] Duplicate delivery → single state transition, second marked `DUPLICATE`.
- [ ] Expired offer → `REJECTED:EXPIRED`, no assignment.
- [ ] Priority: CANCEL jumps ahead of queued telemetry (assert order in test queue).
- [ ] Unacked message never counted as accepted (assert states distinct).
