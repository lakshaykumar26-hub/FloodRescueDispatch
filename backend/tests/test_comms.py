"""Phase 5 Step 01: message envelope + validation.

See docs/phase-5-communication-simulation/step-01-message-models.md.
Step 02 appends its gateway section below the STEP 01 header.
"""

# --- STEP 01: envelope validation ---

import pytest
from pydantic import ValidationError

from backend.app.communications.models import Message, validate_known, validate_message


def _offer(**overrides):  # type: ignore[no-untyped-def]
    base = {
        "message_id": "MSG-00142",
        "type": "ASSIGNMENT_OFFER",
        "sender_id": "DISPATCH-01",
        "recipient_id": "BOAT-03",
        "simulation_id": "SIM-001",
        "created_at_tick": 42,
        "expires_at_tick": 52,
        "version": 3,
        "payload": {
            "assignment_id": "ASN-00031",
            "incident_id": "INC-08",
            "destination_id": "SHELTER-02",
        },
    }
    base.update(overrides)
    return base


def test_bad_type_rejected() -> None:
    with pytest.raises(ValidationError):
        Message(**_offer(type="NOT_A_TYPE"))  # type: ignore[typeddict-unknown-key]


def test_offer_missing_incident_id_rejected() -> None:
    bad = _offer(payload={"assignment_id": "ASN-00031"})
    with pytest.raises(ValidationError):
        Message(**bad)


def test_expired_envelope_vs_created_tick() -> None:
    msg = Message(**_offer())
    assert validate_message(msg, tick=42) == (True, "OK")
    assert validate_message(msg, tick=53) == (False, "EXPIRED")


def test_valid_offer_passes() -> None:
    msg = Message(**_offer())
    assert validate_message(msg, tick=42) == (True, "OK")


def test_ack_reference_known_vs_unknown() -> None:
    ack_base = {
        "message_id": "MSG-00143",
        "type": "MESSAGE_ACK",
        "sender_id": "BOAT-03",
        "recipient_id": "DISPATCH-01",
        "simulation_id": "SIM-001",
        "created_at_tick": 43,
        "expires_at_tick": 53,
        "version": 0,
        "payload": {"ack_of": "MSG-00142", "status": "DELIVERED"},
    }
    ack = Message(**ack_base)
    assert validate_known(ack, {"MSG-00142"}) == (True, "OK")
    assert validate_known(ack, set()) == (False, "ACK_UNKNOWN_REFERENCE")
    assert validate_known(ack, {"MSG-99999"}) == (False, "ACK_UNKNOWN_REFERENCE")


# --- STEP 02: gateway queue / ACK / retry / dedup / expiry ---

import copy

from backend.app.communications.deduplicator import Deduplicator
from backend.app.communications.delivery_tracker import DeliveryTracker
from backend.app.communications.gateway import Gateway
from backend.app.communications.message_queue import MessageQueue
from backend.app.communications.simulated_network import SimulatedNetwork


def _base_msg(message_id="MSG-00200", type="ASSIGNMENT_OFFER", tick=10, ttl=10, **kw):  # type: ignore[no-untyped-def]
    base = {
        "message_id": message_id,
        "type": type,
        "sender_id": "DISPATCH-01",
        "recipient_id": "BOAT-03",
        "simulation_id": "SIM-001",
        "created_at_tick": tick,
        "expires_at_tick": tick + ttl,
        "version": 1,
        "payload": {"assignment_id": "ASN-00031", "incident_id": "INC-08"},
    }
    base.update(kw)
    return base


def _telemetry(mid, tick=10):
    return {
        "message_id": mid,
        "type": "BOAT_POSITION",
        "sender_id": "BOAT-03",
        "recipient_id": "DISPATCH-01",
        "simulation_id": "SIM-001",
        "created_at_tick": tick,
        "expires_at_tick": tick + 50,
        "version": 1,
        "payload": {},
    }


def _cancel(mid, tick=10):
    return {
        "message_id": mid,
        "type": "ASSIGNMENT_CANCELLED",
        "sender_id": "DISPATCH-01",
        "recipient_id": "BOAT-03",
        "simulation_id": "SIM-001",
        "created_at_tick": tick,
        "expires_at_tick": tick + 50,
        "version": 2,
        "payload": {"assignment_id": "ASN-00031", "reason": "SAFETY"},
    }


def test_duplicate_delivery_single_transition() -> None:
    net = SimulatedNetwork(seed=7, config={"dup_rate": 1.0})
    gw = Gateway(net)
    ok, code = gw.send(_base_msg("MSG-00201", tick=10), tick=10)
    assert (ok, code) == (True, "QUEUED")
    deliveries = gw.pump(tick=10)
    assert len(deliveries) == 2
    assert deliveries[0]["delivery_kind"] == "FIRST"
    assert deliveries[1]["delivery_kind"] == "DUPLICATE"
    # Consumer-side dedup: FIRST applies, second is a no-op duplicate.
    consumer = Deduplicator()
    assert consumer.check(deliveries[0]["message"]["message_id"]) == "NEW"
    assert consumer.check(deliveries[1]["message"]["message_id"]) == "DUPLICATE"
    # Gateway audit records the duplicate copy.
    assert any(a["event"] == "DELIVER_DUP" for a in gw.audit)


def test_expired_offer_never_delivered() -> None:
    net = SimulatedNetwork(seed=1)
    gw = Gateway(net)
    ok, code = gw.send(_base_msg("MSG-00202", tick=10, ttl=2), tick=10)
    assert (ok, code) == (True, "QUEUED")
    deliveries = gw.pump(tick=13)  # tick > expires_at_tick (12)
    assert deliveries == []
    assert gw.status_of("MSG-00202") == "EXPIRED"
    # A commit-style guard must treat an expired offer as rejected.
    assert gw.status_of("MSG-00202") != "DELIVERED"
    assert any(a["event"] == "EXPIRE" for a in gw.audit)


def test_priority_cancel_before_telemetry() -> None:
    net = SimulatedNetwork(seed=1)
    gw = Gateway(net)
    assert gw.send(_telemetry("MSG-00210", tick=10), tick=10) == (True, "QUEUED")
    assert gw.send(_telemetry("MSG-00211", tick=10), tick=10) == (True, "QUEUED")
    assert gw.send(_cancel("MSG-00212", tick=10), tick=10) == (True, "QUEUED")
    deliveries = gw.pump(tick=10)
    assert [d["message"]["message_id"] for d in deliveries] == [
        "MSG-00212",
        "MSG-00210",
        "MSG-00211",
    ]


def test_unacked_vs_accepted_states() -> None:
    net = SimulatedNetwork(seed=1)
    gw = Gateway(net)
    mid = "MSG-00220"
    assert gw.send(_base_msg(mid, tick=10), tick=10) == (True, "QUEUED")
    assert gw.status_of(mid) == "QUEUED"
    deliveries = gw.pump(tick=10)
    assert len(deliveries) == 1
    # DELIVERED is receipt by the channel, not acceptance.
    assert gw.status_of(mid) == "DELIVERED"
    ok, code = gw.ack(mid, tick=11)
    assert (ok, code) == (True, "ACKED")
    assert gw.status_of(mid) == "ACKED"
    # ACKED is receipt confirmed, never acceptance — statuses stay distinct.
    assert gw.status_of(mid) not in ("QUEUED", "DELIVERED")


def test_ack_unknown_message() -> None:
    net = SimulatedNetwork(seed=1)
    gw = Gateway(net)
    assert gw.ack("MSG-NOPE", tick=10) == (False, "UNKNOWN_MESSAGE")


def test_duplicate_send_not_requeued() -> None:
    net = SimulatedNetwork(seed=1)
    gw = Gateway(net)
    assert gw.send(_base_msg("MSG-00230", tick=10), tick=10) == (True, "QUEUED")
    assert gw.send(_base_msg("MSG-00230", tick=10), tick=10) == (True, "DUPLICATE_SEND")
    assert len(gw.queue) == 1
    deliveries = gw.pump(tick=10)
    assert len(deliveries) == 1


def test_queue_ordering_and_tracker_terminals() -> None:
    q = MessageQueue()
    q.push("B", 2, 10, 1)
    q.push("A", 0, 10, 2)
    assert q.peek() == "A"
    assert q.pop() == "A"
    assert len(q) == 1
    tr = DeliveryTracker()
    assert tr.register("M1") is True
    assert tr.status_of("M1") == "QUEUED"
    assert tr.mark_acked("M1", tick=5, note="ok") is True
    assert tr.status_of("M1") == "ACKED"
    # Terminal ignores further transitions.
    assert tr.mark_delivered("M1", tick=6, attempt=1) is False
    assert tr.mark_expired("M1", tick=7) is False
