# Phase 5 / Step 01 — Message Envelope + Validation

## Goal

Spec §8 envelope as validated Pydantic models.

## Files

- `backend/app/communications/models.py`, `backend/app/schemas/messages.py`
- `backend/tests/test_comms.py` (envelope tests)

## Implementation

Envelope `{message_id, type, sender_id, recipient_id, simulation_id, created_at_tick, expires_at_tick, version, payload}`. Types: `INCIDENT_CREATED, ASSIGNMENT_OFFER, ASSIGNMENT_ACCEPTED, ASSIGNMENT_CANCELLED, BOAT_POSITION, BOAT_STATUS_CHANGED, HAZARD_REPORTED, SHELTER_CAPACITY_CHANGED, MESSAGE_ACK`. `payload` per-type schema (e.g. OFFER carries `assignment_id, incident_id, destination_id`). `validate(): sender known, type known, schema ok, transition permitted, not expired at current tick`.

## What to test

- [ ] Bad sender/type/schema/expired each rejected with distinct code.
- [ ] Valid OFFER passes; `MESSAGE_ACK` references existing `message_id`.
- [ ] Manual: print a valid + an expired envelope validation result.
