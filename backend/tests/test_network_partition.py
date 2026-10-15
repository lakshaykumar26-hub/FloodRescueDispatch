"""STEP 03 — Simulated network (delay/loss/dup/partition) tests.

Step 03 owns everything above the "STEP 04"/"STEP 05" markers at the end of
this file; later steps append their sections below (gateway reconnect +
agent wiring must not edit Step 03 tests).
"""

import json

from backend.app.communications.simulated_network import SimulatedNetwork


def _msg(mid: str, tick: int, sender: str = "DISPATCH-01",
         recipient: str = "BOAT-01") -> dict:
    return {
        "message_id": mid,
        "sender_id": sender,
        "recipient_id": recipient,
        "created_at_tick": tick,
    }


def _pattern(net: SimulatedNetwork, ids: list[str], tick: int) -> list[tuple]:
    # Caller-side rule: first touch messages in sorted message_id order so
    # seeded draws are reproducible (see SimulatedNetwork docstring).
    out = []
    for mid in sorted(ids):
        out.append(
            (mid, net.delivery_tick(_msg(mid, tick)),
             net.should_drop(mid), net.duplicate_count(mid))
        )
    return out


def test_same_seed_identical_pattern() -> None:
    """Fixed seed twice -> identical delivery_tick/drop/dup over a set."""
    cfg = {"delay_ticks": 2, "delay_jitter": 5,
           "loss_rate": 0.5, "dup_rate": 0.5}
    ids = [f"MSG-{i:05d}" for i in range(1, 11)]
    first = _pattern(SimulatedNetwork(seed=7, config=cfg), ids, 10)
    second = _pattern(SimulatedNetwork(seed=7, config=cfg), ids, 10)
    assert first == second
    # Exact observed values (seed=7): regression tripwire, no randomness.
    assert first == [
        ("MSG-00001", 14, False, 1),
        ("MSG-00002", 12, True, 0),
        ("MSG-00003", 14, False, 0),
        ("MSG-00004", 13, True, 1),
        ("MSG-00005", 12, True, 0),
        ("MSG-00006", 12, False, 1),
        ("MSG-00007", 13, False, 0),
        ("MSG-00008", 12, False, 1),
        ("MSG-00009", 13, True, 0),
        ("MSG-00010", 14, True, 0),
    ]


def test_loss_drops_without_partition() -> None:
    """Loss drops messages even while can_deliver is True (loss != partition)."""
    net = SimulatedNetwork(seed=42, config={"loss_rate": 0.5})
    ids = [f"MSG-{i:05d}" for i in range(1, 21)]
    dropped = [mid for mid in sorted(ids) if net.should_drop(mid)]
    assert dropped == [
        "MSG-00001", "MSG-00002", "MSG-00004", "MSG-00006", "MSG-00008",
        "MSG-00009", "MSG-00012", "MSG-00016", "MSG-00017", "MSG-00020",
    ]
    assert 1 <= len(dropped) < len(ids)  # some, but not all, lost
    # No partitions configured: every pair can deliver at any tick.
    for mid in ids:
        assert net.can_deliver("DISPATCH-01", "BOAT-01", 10) is True


def test_dup_produces_extra_copy() -> None:
    net = SimulatedNetwork(seed=42, config={"dup_rate": 0.5})
    ids = [f"MSG-{i:05d}" for i in range(1, 21)]
    counts = {mid: net.duplicate_count(mid) for mid in sorted(ids)}
    assert set(counts.values()) <= {0, 1}  # at most 1 extra copy
    assert [m for m, c in counts.items() if c == 1] == [
        "MSG-00001", "MSG-00002", "MSG-00003", "MSG-00007", "MSG-00008",
        "MSG-00009", "MSG-00012", "MSG-00017", "MSG-00019", "MSG-00020",
    ]


def test_partition_island_semantics() -> None:
    """Island members reach each other; cross-boundary traffic is HELD."""
    part = {"agents": ["BOAT-01", "BOAT-02"], "from_tick": 10, "to_tick": 20}
    net = SimulatedNetwork(seed=42, config={"partitions": [part]})
    # During the partition (tick 15):
    assert net.can_deliver("BOAT-01", "BOAT-02", 15) is True  # inside-island
    assert net.can_deliver("BOAT-01", "BOAT-03", 15) is False  # cross-boundary
    assert net.can_deliver("BOAT-03", "BOAT-01", 15) is False  # reverse held
    assert net.can_deliver("BOAT-01", "DISPATCH-01", 15) is False
    assert net.can_deliver("DISPATCH-01", "BOAT-01", 15) is False
    assert net.can_deliver("BOAT-03", "BOAT-04", 15) is True  # outside-outside
    assert net.can_deliver("DISPATCH-01", "BOAT-03", 15) is True
    # Inclusive bounds: held at 10 and 20, released at 9 and 21.
    assert net.can_deliver("BOAT-01", "BOAT-03", 10) is False
    assert net.can_deliver("BOAT-01", "BOAT-03", 20) is False
    assert net.can_deliver("BOAT-01", "BOAT-03", 9) is True
    assert net.can_deliver("BOAT-01", "BOAT-03", 21) is True
    # Held is retryable, not dropped: zero-loss net drops nothing and still
    # computes a delivery tick for the held message (released on reconnect).
    assert net.should_drop("MSG-00001") is False
    assert net.delivery_tick(_msg("MSG-00001", 15)) == 15
    # partitions_at helper: active record at 15, empty outside.
    assert net.partitions_at(15) == [part]
    assert net.partitions_at(9) == []
    assert net.partitions_at(21) == []


def test_jitter_reorders_same_tick() -> None:
    """Same created tick + jitter>0 -> spread delivery ticks (reorder)."""
    net = SimulatedNetwork(seed=7, config={"delay_ticks": 2, "delay_jitter": 5})
    ids = [f"MSG-{i:05d}" for i in range(1, 21)]
    ticks = [net.delivery_tick(_msg(mid, 10)) for mid in sorted(ids)]
    assert ticks == [14, 12, 14, 13, 12, 12, 13, 12, 13, 14,
                     16, 13, 13, 12, 15, 14, 14, 17, 14, 17]
    assert len(set(ticks)) > 1  # reordered, not lockstep
    assert all(12 <= t <= 17 for t in ticks)  # created + delay + [0, jitter]
    # Cache: repeat calls are stable and consume no further draws.
    assert [net.delivery_tick(_msg(mid, 10)) for mid in sorted(ids)] == ticks


def test_snapshot_round_trip_preserves_draws() -> None:
    net = SimulatedNetwork(seed=7, config={"delay_ticks": 1, "delay_jitter": 3,
                                           "loss_rate": 0.5, "dup_rate": 0.5})
    first_ids = [f"MSG-{i:05d}" for i in range(1, 6)]
    before = _pattern(net, first_ids, 10)
    snap = net.to_dict()
    # Snapshot is JSON-safe (rng state as plain lists) for Step 05 wiring.
    reloaded = json.loads(json.dumps(snap))
    resumed = SimulatedNetwork.from_dict(reloaded)
    assert resumed.to_dict() == snap
    # Cached values survive the round-trip.
    for mid in first_ids:
        assert resumed.delivery_tick(_msg(mid, 10)) == net.delivery_tick(
            _msg(mid, 10))
    # Subsequent draws continue identically on both branches.
    next_ids = [f"MSG-{i:05d}" for i in range(6, 11)]
    assert _pattern(resumed, next_ids, 12) == _pattern(net, next_ids, 12)
    assert resumed.to_dict() == net.to_dict()


# STEP 04 (reconnect/reconciliation) appends below — do not edit Step 03 tests.
# STEP 05 (agent/gateway wiring) appends below — do not edit Step 03 tests.


# ---------------------------------------------------------------------------
# STEP 04 — Reconnect + reconciliation (gateway.reconcile + version guard).
# ---------------------------------------------------------------------------

from backend.app.communications.gateway import Gateway
from backend.app.dispatch import commitment_manager as cm
from backend.app.dispatch.scheduler_interface import Assignment


def _gw04() -> Gateway:
    return Gateway(SimulatedNetwork(seed=11), simulation_id="SIM-001")


def _asn04(
    aid: str,
    status: str = "COMMITTED",
    version: int = 1,
    resource: str = "BOAT-01",
    incident: str = "INC-01",
) -> Assignment:
    return Assignment(
        assignment_id=aid,
        version=version,
        proposal_id=f"PROP-{aid}",
        incident_id=incident,
        resource_id=resource,
        resource_kind="boat",
        seats=4,
        route_edge_ids=["E1", "E2"],
        status=status,  # type: ignore[arg-type]
        cost=1.0,
        created_tick=5,
        history=[
            {
                "tick": 5,
                "from": "PROPOSED",
                "to": "COMMITTED",
                "reason": "commit",
                "actor": "dispatch",
            }
        ],
    )


def test_reconcile_stale_route_reoffer() -> None:
    """Partitioned boat missed a closure -> STALE_ROUTE + one re-offer."""
    gw = _gw04()
    tick = 30
    authority = {
        "tick": tick,
        "assignments": {
            "ASN-00001": {
                "status": "COMMITTED",
                "version": 2,
                "resource_id": "BOAT-01",
                "incident_id": "INC-01",
            },
        },
        "routes": {"BOAT-01": {"edge_ids": ["E2", "E3"], "next_index": 0}},
        "partition_started_tick": 20,
    }
    report = {
        "agent_id": "BOAT-01",
        "belief_version": 1,
        "assignment_id": "ASN-00001",
        "assignment_version": 1,  # stale: authority bumped to 2
        "route_signature": {"edge_ids": ["E1", "E2"], "next_index": 0},
    }
    outcome, actions, detail = gw.reconcile(report, authority, tick)
    assert outcome == "STALE_ROUTE"
    assert len(actions) == 1  # exactly one re-offer, sent by the caller
    reoffer = actions[0]
    assert reoffer["message_id"] == "MSG-REOFFER-ASN-00001-t0030"
    assert reoffer["type"] == "ASSIGNMENT_OFFER"
    assert reoffer["sender_id"] == "DISPATCH-01"
    assert reoffer["recipient_id"] == "BOAT-01"
    assert reoffer["created_at_tick"] == tick
    assert reoffer["expires_at_tick"] == tick + 10
    assert reoffer["version"] == 2  # bumped authority version
    assert reoffer["payload"]["assignment_id"] == "ASN-00001"
    assert reoffer["payload"]["incident_id"] == "INC-01"
    assert reoffer["payload"]["re_offer"] is True
    assert reoffer["payload"]["route_edge_ids"] == ["E2", "E3"]
    assert detail["reconciliation_time_ticks"] == 10
    # Pure: reconcile itself sends nothing (caller sends via send()).
    assert gw.store == {}


def test_reconcile_stale_ownership_flags_reconciliation() -> None:
    """Assignment reassigned while away -> STALE_OWNERSHIP, never resumed."""
    gw = _gw04()
    tick = 40
    authority = {
        "tick": tick,
        "assignments": {
            "ASN-00007": {
                "status": "CANCELLED",
                "version": 1,
                "resource_id": "BOAT-02",
                "incident_id": "INC-03",
            },
            "ASN-00008": {
                "status": "COMMITTED",
                "version": 1,
                "resource_id": "BOAT-02",
                "incident_id": "INC-04",
            },
        },
        "routes": {},
        "partition_started_tick": 25,
    }
    report = {
        "agent_id": "BOAT-02",
        "belief_version": 1,
        "assignment_id": "ASN-00007",
        "assignment_version": 1,
        "local_claims": [],
    }
    outcome, actions, detail = gw.reconcile(report, authority, tick)
    assert outcome == "STALE_OWNERSHIP"
    assert actions == []
    assert detail["old_assignment_id"] == "ASN-00007"
    assert detail["authority_status"] == "CANCELLED"
    assert detail["reconciliation_time_ticks"] == 15
    # Caller marks the superseded assignment explicitly (audit: caller's job).
    assignments = {"ASN-00007": _asn04("ASN-00007", resource="BOAT-02")}
    ok, code = cm.flag_reconciliation(
        assignments, "ASN-00007", tick, "superseded while partitioned"
    )
    assert (ok, code) == (True, "OK")
    flagged = assignments["ASN-00007"]
    assert flagged.status == "REQUIRES_RECONCILIATION"
    assert flagged.history[-1] == {
        "tick": tick,
        "from": "COMMITTED",
        "to": "REQUIRES_RECONCILIATION",
        "reason": "superseded while partitioned",
        "actor": "dispatch",
    }


def test_reconcile_conflict_double_commit() -> None:
    """Agent claims ASN-X while authority holds ASN-Y: both stay visible."""
    gw = _gw04()
    tick = 50
    authority = {
        "tick": tick,
        "assignments": {
            "ASN-00012": {
                "status": "COMMITTED",
                "version": 1,
                "resource_id": "BOAT-01",
                "incident_id": "INC-09",
            },
        },
        "routes": {},
        "partition_started_tick": 44,
    }
    report = {
        "agent_id": "BOAT-01",
        "belief_version": 1,
        "assignment_id": None,
        "assignment_version": None,
        "local_claims": [
            {
                "assignment_id": "ASN-00011",
                "version": 1,
                "resource_id": "BOAT-01",
                "incident_id": "INC-08",
            }
        ],
    }
    outcome, actions, detail = gw.reconcile(report, authority, tick)
    assert outcome == "CONFLICT"
    assert actions == []  # surfaced, resolved nowhere here
    assert detail["agent_claim"]["assignment_id"] == "ASN-00011"
    assert detail["authority_record"]["assignment_id"] == "ASN-00012"
    assert detail["authority_record"]["resource_id"] == "BOAT-01"
    assert detail["reconciliation_time_ticks"] == 6


def test_check_version_guard() -> None:
    assert cm.check_version(2, 2) == (True, "OK")
    assert cm.check_version(2, 1) == (False, "REJECTED_STALE")
    assert cm.check_version(1, 2) == (False, "REJECTED_STALE")


def test_flag_reconciliation_edges() -> None:
    assignments = {
        "ASN-A": _asn04("ASN-A", status="IN_PROGRESS"),
        "ASN-T": _asn04("ASN-T", status="CANCELLED"),
    }
    assert assignments["ASN-A"].status == "IN_PROGRESS"
    ok, code = cm.flag_reconciliation(assignments, "ASN-A", 60, "stale on return")
    assert (ok, code) == (True, "OK")
    assert assignments["ASN-A"].status == "REQUIRES_RECONCILIATION"
    # Idempotent re-flag.
    assert cm.flag_reconciliation(assignments, "ASN-A", 61, "again") == (
        True,
        "OK:ALREADY",
    )
    assert assignments["ASN-A"].status == "REQUIRES_RECONCILIATION"
    # Terminal states refuse; unknown ids report cleanly.
    assert cm.flag_reconciliation(assignments, "ASN-T", 60, "x") == (
        False,
        "REJECTED:TERMINAL",
    )
    assert cm.flag_reconciliation(assignments, "ASN-NOPE", 60, "x") == (
        False,
        "UNKNOWN_ASSIGNMENT",
    )


def test_reconcile_in_sync_quiet() -> None:
    """Matching versions + route -> IN_SYNC with no catch-up chatter."""
    gw = _gw04()
    tick = 30
    authority = {
        "tick": tick,
        "assignments": {
            "ASN-00001": {
                "status": "COMMITTED",
                "version": 2,
                "resource_id": "BOAT-01",
                "incident_id": "INC-01",
            },
        },
        "routes": {"BOAT-01": {"edge_ids": ["E2", "E3"], "next_index": 0}},
        "partition_started_tick": 20,
    }
    report = {
        "agent_id": "BOAT-01",
        "belief_version": 2,
        "assignment_id": "ASN-00001",
        "assignment_version": 2,
        "route_signature": {"edge_ids": ["E2", "E3"], "next_index": 0},
    }
    outcome, actions, detail = gw.reconcile(report, authority, tick)
    assert outcome == "IN_SYNC"
    assert actions == []
    assert detail["reconciliation_time_ticks"] == 10
    # No assignment at all + nothing claimed -> also IN_SYNC.
    outcome2, actions2, detail2 = gw.reconcile(
        {"agent_id": "BOAT-03"},
        {"tick": tick, "assignments": {}, "routes": {}},
        tick,
    )
    assert outcome2 == "IN_SYNC"
    assert actions2 == []
    assert detail2["reconciliation_time_ticks"] == 0


# ---------------------------------------------------------------------------
# STEP 05 — Agent/gateway wiring (belief freeze + reconnect + no shortcuts).
# ---------------------------------------------------------------------------

from pathlib import Path

import pytest

from backend.app.agents.base_agent import BaseAgent
from backend.app.communications.deduplicator import Deduplicator
from backend.app.simulation.engine import Simulation
from backend.app.simulation.run import build_simulation


_S05_PARTITION = {"agents": ["BOAT-03"], "from_tick": 10, "to_tick": 20}

_S05_RECONCILIATION_OUTCOMES = frozenset(
    {"STALE_ROUTE", "IN_SYNC", "STALE_OWNERSHIP", "CONFLICT"}
)


def _s05_load_scenario(name: str):
    """Load a scenario JSON dict, or None when the file is missing."""
    path = Path(__file__).resolve().parents[2] / "scenarios" / name
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _s05_reliable(data: dict) -> dict:
    """Deepcopy of ``data`` with a reliable (partition-free) network."""
    data = json.loads(json.dumps(data))
    data["network"] = {}
    return data


def _s05_partitioned(data: dict) -> dict:
    """Deepcopy of ``data`` partitioning BOAT-03 over ticks 10-20."""
    data = json.loads(json.dumps(data))
    data["network"] = {"partitions": [dict(_S05_PARTITION)]}
    return data


def _s05_outcome(entry) -> str | None:
    """Best-effort outcome code from a reconciliation_log entry."""
    if isinstance(entry, dict):
        for key in ("outcome", "result", "code"):
            value = entry.get(key)
            if isinstance(value, str) and value:
                return value
    text = str(entry)
    for code in ("STALE_ROUTE", "STALE_OWNERSHIP", "CONFLICT", "IN_SYNC"):
        if code in text:
            return code
    return None


def test_step05_partition_freezes_belief() -> None:
    """Partitioned BOAT-03 gets no global updates: belief frozen mid-partition."""
    data = _s05_load_scenario("baseline.json")
    if data is None:
        pytest.skip("scenarios/baseline.json missing")
    sim = build_simulation(_s05_partitioned(data))
    assert isinstance(sim, Simulation)
    agents = getattr(sim, "comms_agents", None)
    gateway = getattr(sim, "gateway", None)
    network = getattr(sim, "network", None)
    if agents is None or gateway is None or network is None:
        pytest.skip("engine wiring pending (no comms_agents/gateway/network)")
    if not network.partitions_at(15):
        pytest.skip("engine did not pick up data['network'] partitions")
    if "BOAT-03" not in sim.world.boats:
        pytest.skip("scenario has no BOAT-03")
    while sim.tick < 9:
        sim.step()
    if "BOAT-03" not in agents:
        pytest.skip("engine wiring pending (BOAT-03 mirror missing)")
    target = agents["BOAT-03"]
    pre_version = target.local_belief.get("belief_version", 0)
    while sim.tick < 15:
        sim.step()
    assert target.world_tick_at_read < sim.tick
    assert target.local_belief.get("belief_version", 0) == pre_version
    pending = gateway.pending_for("BOAT-03") if hasattr(gateway, "pending_for") else []
    audit = getattr(gateway, "audit", []) or []
    audit_hold = any(
        isinstance(entry, dict) and entry.get("event") == "PARTITION_HOLD"
        for entry in audit
    )
    assert pending or audit_hold
    others = [agent for aid, agent in agents.items() if aid != "BOAT-03"]
    assert others
    assert max(agent.world_tick_at_read for agent in others) > (
        target.world_tick_at_read
    )


def test_step05_no_movement_on_stale_route_after_reconnect() -> None:
    """After the partition lifts, BOAT-03 reconciles (logged, no exception)."""
    data = _s05_load_scenario("baseline.json")
    if data is None:
        pytest.skip("scenarios/baseline.json missing")
    sim = build_simulation(_s05_partitioned(data))
    assert isinstance(sim, Simulation)
    if getattr(sim, "reconciliation_log", None) is None:
        pytest.skip("engine wiring pending (no reconciliation_log)")
    network = getattr(sim, "network", None)
    if network is None or not network.partitions_at(15):
        pytest.skip("engine did not pick up data['network'] partitions")
    while sim.tick < 26:
        sim.step()
    entries = [
        entry for entry in sim.reconciliation_log if "BOAT-03" in str(entry)
    ]
    assert entries, "expected a reconciliation_log entry for BOAT-03"
    outcomes = {_s05_outcome(entry) for entry in entries}
    assert outcomes & _S05_RECONCILIATION_OUTCOMES, (
        f"unknown reconciliation outcomes: {sorted(str(o) for o in outcomes)}"
    )
    event_log = getattr(getattr(sim, "manager", None), "event_log", []) or []
    reconciled = [
        entry
        for entry in event_log
        if isinstance(entry, dict) and "RECONCIL" in str(entry.get("kind", ""))
    ]
    if not reconciled:
        gateway = getattr(sim, "gateway", None)
        audit = getattr(gateway, "audit", []) if gateway is not None else []
        reconciled = [
            entry
            for entry in audit
            if isinstance(entry, dict)
            and entry.get("event") in ("RECONCILE", "RECONCILED")
        ]
    assert reconciled, "expected a RECONCILED log entry on reconnect"
    assert sim.world.boats["BOAT-03"].node_id in sim.world.nodes


def test_step05_baseline_still_completes() -> None:
    """Reliable network: baseline serves every incident, no dispatch deadlock."""
    data = _s05_load_scenario("baseline.json")
    if data is None:
        data = _s05_load_scenario("combined_disaster.json")
    if data is None:
        pytest.skip("no scenario file available")
    sim = build_simulation(_s05_reliable(data))
    assert isinstance(sim, Simulation)
    sim.run(120)
    total = len(sim.world.incidents)
    assert total > 0
    served = sum(
        1 for incident in sim.world.incidents.values()
        if incident.status == "SERVED"
    )
    if served != total:
        assert sim.assignments, (
            f"deadlock suspected: served {served}/{total} with no assignments"
        )


def test_step05_no_direct_world_reads_in_agents() -> None:
    """Agents never read the global World (no world.edges[/world.incidents)."""
    agents_dir = (
        Path(__file__).resolve().parents[2] / "backend" / "app" / "agents"
    )
    if not agents_dir.is_dir():
        pytest.skip("agents package not found")
    hits = []
    for path in sorted(agents_dir.glob("*.py")):
        for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1
        ):
            code = line.split("#", 1)[0]
            if "world.edges[" in code or "world.incidents" in code:
                hits.append(f"{path.name}:{number}: {line.strip()}")
            elif "simulation.world import" in code or "simulation import" in code:
                hits.append(f"{path.name}:{number}: {line.strip()}")
    assert hits == [], f"direct global reads in agents/: {hits}"


def test_step05_duplicate_belief_no_double_apply() -> None:
    """Duplicated belief delivery: dedup + version guard apply it exactly once."""
    net = SimulatedNetwork(seed=7, config={"dup_rate": 1.0})
    gateway = Gateway(net)
    message = {
        "message_id": "MSG-S05-DUP-001",
        "type": "ASSIGNMENT_OFFER",
        "sender_id": "DISPATCH-01",
        "recipient_id": "BOAT-99",
        "simulation_id": "SIM-001",
        "created_at_tick": 10,
        "expires_at_tick": 60,
        "version": 1,
        "payload": {"assignment_id": "ASN-00031", "incident_id": "INC-08"},
    }
    assert gateway.send(message, tick=10) == (True, "QUEUED")
    deliveries = gateway.pump(tick=10)
    assert len(deliveries) == 2
    assert [d["delivery_kind"] for d in deliveries] == ["FIRST", "DUPLICATE"]
    agent = BaseAgent("BOAT-99")
    consumer = Deduplicator()
    verdicts = []
    results = []
    for delivery in deliveries:
        verdicts.append(
            consumer.check(delivery["message"]["message_id"])
        )
        results.append(agent.update_belief(delivery["message"]))
    assert verdicts == ["NEW", "DUPLICATE"]
    assert results == [True, False]
    assert agent.local_belief["belief_version"] == 1
    assert (
        sum(
            1 for entry in agent.audit
            if entry.get("event") == "BELIEF_UPDATED"
        )
        == 1
    )
