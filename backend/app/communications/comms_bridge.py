"""Step 05 comms bridge: wire agents to the store-and-forward gateway.

Helpers that translate between world snapshots, gateway ``Message``
envelopes, agent beliefs, and gateway reconciliation inputs, so the
engine never lets agents read global state directly. Per-tick flow::

    snapshot  = world_to_belief_snapshot(world)   # engine
    msg       = make_belief_message(...)           # publish (one per agent)
    gateway.send(msg, tick)                        # queue
    deliveries = gateway.pump(tick)                # due only
    deliver_to_agent(agent, msg, dedup, tick)      # belief update
    report    = build_agent_report(...)            # reconnect only
    authority = build_authority(...)               # reconnect only
    gateway.reconcile(report, authority, tick)     # reconnect only

In-process simplification (Step 05): the shared-memory
:class:`~backend.app.communications.gateway.Gateway` stands in for
real radios — ``send``/``pump`` are plain method calls, not RF
transmissions, and there is no serialization, spectrum contention, or
range model. Replaceable comm adapters (real transports) land in
Phase 8 without changing these payload shapes.

Stdlib only (plus typing): no FastAPI, DB, or frontend imports, so
``simulation/`` and ``agents/`` can use this module freely.
"""

from __future__ import annotations

import copy
from typing import Any

#: Coordinator sender id (never placed inside a partition island).
COORDINATOR_ID = "DISPATCH-01"


def belief_payload_from_snapshot(snapshot: dict, world_tick: int) -> dict:
    """Deep-copied belief body ``{edges, shelters, assignments, world_tick}``.

    ``snapshot`` is a plain dict such as
    :func:`world_to_belief_snapshot` output (which carries no
    ``assignments`` key — those default to ``[]``). Mutating the
    result never affects the snapshot and vice versa.
    """
    edges = snapshot.get("edges", {})
    shelters = snapshot.get("shelters", {})
    assignments = snapshot.get("assignments", [])
    return {
        "edges": copy.deepcopy(edges if edges is not None else {}),
        "shelters": copy.deepcopy(shelters if shelters is not None else {}),
        "assignments": copy.deepcopy(
            assignments if assignments is not None else []
        ),
        "world_tick": int(world_tick),
    }


def make_belief_message(
    sender: str,
    recipient: str,
    snapshot: dict,
    tick: int,
    version: int,
    seq: int,
    simulation_id: str = "SIM-001",
    ttl: int = 10,
) -> dict:
    """Build a valid gateway ``Message`` envelope carrying a belief sync.

    Uses type ``"BOAT_STATUS_CHANGED"`` (no required payload keys, so
    the belief body rides free) with payload ``{assignment_id: "-",
    reason: "BELIEF_SYNC", edges, shelters, assignments, world_tick}``.
    ``world_tick`` prefers the snapshot's own ``tick``/``world_tick``
    and falls back to ``tick``. ``version`` should grow monotonically
    per recipient (e.g. the tick for one broadcast per agent per tick)
    because :meth:`BaseAgent.update_belief` ignores stale versions.
    The returned dict passes ``Message(**d)`` validation.
    """
    tick_i = int(tick)
    snap_tick = snapshot.get("tick", snapshot.get("world_tick", tick_i))
    try:
        world_tick = int(snap_tick)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        world_tick = tick_i
    payload = belief_payload_from_snapshot(snapshot, world_tick)
    payload = {"assignment_id": "-", "reason": "BELIEF_SYNC", **payload}
    return {
        "message_id": f"MSG-BELIEF-{tick_i:04d}-{int(seq):04d}",
        "type": "BOAT_STATUS_CHANGED",
        "sender_id": str(sender),
        "recipient_id": str(recipient),
        "simulation_id": str(simulation_id),
        "created_at_tick": tick_i,
        "expires_at_tick": tick_i + int(ttl),
        "version": int(version),
        "payload": payload,
    }


def to_belief_update(msg_dict: dict) -> dict:
    """Translate a gateway ``Message`` dict into an ``update_belief`` dict.

    Returns ``{message_id, type, version, edges, shelters, assignments,
    tick (created_at_tick), world_tick (payload, default
    created_at_tick)}``. All containers are deep copies, so applying
    the update never aliases gateway store memory.
    """
    payload = msg_dict.get("payload", {}) or {}
    try:
        created = int(msg_dict.get("created_at_tick", 0))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        created = 0
    world_tick = payload.get("world_tick", created)
    try:
        world_tick = int(world_tick)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        world_tick = created
    try:
        version = int(msg_dict.get("version", 0))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        version = 0
    return {
        "message_id": msg_dict.get("message_id"),
        "type": msg_dict.get("type"),
        "version": version,
        "edges": copy.deepcopy(payload.get("edges") or {}),
        "shelters": copy.deepcopy(payload.get("shelters") or {}),
        "assignments": copy.deepcopy(payload.get("assignments") or []),
        "tick": created,
        "world_tick": world_tick,
    }


def _as_route_sig(edges: Any, index: Any) -> dict | None:
    """Normalize ``(edges, index)`` to ``{edge_ids, next_index}`` or None."""
    if edges is None:
        return None
    try:
        edge_list = [str(e) for e in edges]
    except TypeError:
        return None
    if not edge_list:
        return None
    try:
        next_index = int(index)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        next_index = 0
    return {"edge_ids": edge_list, "next_index": next_index}


def _route_signature(service_entry: dict | None, assignment: Any) -> dict | None:
    """Pick a ``{edge_ids, next_index}`` signature from service/assignment.

    Prefers an explicit route on ``service_entry`` (``route`` nested
    record, or ``edge_ids``/``route_edge_ids`` + ``next_index``), then
    falls back to the assignment's ``route_edge_ids`` (index 0 — the
    authority holds the live ``next_index``). Returns None when neither
    carries a usable route, in which case reconciliation skips the
    route comparison.
    """
    if isinstance(service_entry, dict):
        nested = service_entry.get("route")
        if isinstance(nested, dict):
            sig = _as_route_sig(
                nested.get("edge_ids", nested.get("route_edge_ids")),
                nested.get("next_index", nested.get("route_next_index", 0)),
            )
            if sig is not None:
                return sig
        for edges_key in ("edge_ids", "route_edge_ids"):
            if service_entry.get(edges_key) is not None:
                sig = _as_route_sig(
                    service_entry.get(edges_key),
                    service_entry.get(
                        "next_index",
                        service_entry.get("route_next_index", 0),
                    ),
                )
                if sig is not None:
                    return sig
    if assignment is not None:
        if hasattr(assignment, "route_edge_ids"):
            edges = assignment.route_edge_ids
            index = (
                assignment.get("next_index", 0)
                if isinstance(assignment, dict)
                else 0
            )
        elif isinstance(assignment, dict):
            edges = assignment.get(
                "edge_ids", assignment.get("route_edge_ids")
            )
            index = assignment.get(
                "next_index", assignment.get("route_next_index", 0)
            )
        else:
            edges, index = None, 0
        sig = _as_route_sig(edges, index)
        if sig is not None:
            return sig
    return None


def build_agent_report(
    agent: Any,
    service_entry: dict | None,
    assignment_registry: dict,
) -> dict:
    """Build a gateway ``reconcile`` agent-report for ``agent``.

    ``service_entry`` is the engine ``_service[resource_id]`` record (or
    None when the resource holds no mission); ``assignment_registry``
    maps assignment ids to ``Assignment`` models (or plain dicts) for
    the version lookup. ``local_claims`` is always ``[]``: in-process
    agents hold no independent claims outside the registry.
    """
    agent_id = str(getattr(agent, "id", "?"))
    belief = getattr(agent, "local_belief", {}) or {}
    if not isinstance(belief, dict):
        belief = {}
    try:
        belief_version = int(belief.get("belief_version", 0))
    except (TypeError, ValueError):
        belief_version = 0
    try:
        belief_world_tick = int(getattr(agent, "world_tick_at_read", 0) or 0)
    except (TypeError, ValueError):
        belief_world_tick = 0
    assignment_id: str | None = None
    if isinstance(service_entry, dict):
        aid = service_entry.get("assignment_id")
        if isinstance(aid, str):
            assignment_id = aid
    assignment_version: int | None = None
    assignment: Any = None
    if assignment_id is not None and isinstance(assignment_registry, dict):
        assignment = assignment_registry.get(assignment_id)
        if assignment is not None:
            if isinstance(assignment, dict):
                raw_version = assignment.get("version")
            else:
                raw_version = getattr(assignment, "version", None)
            if raw_version is not None:
                try:
                    assignment_version = int(raw_version)  # type: ignore[arg-type]
                except (TypeError, ValueError):
                    assignment_version = None
    return {
        "agent_id": agent_id,
        "resource_id": agent_id,
        "belief_version": belief_version,
        "belief_world_tick": belief_world_tick,
        "assignment_id": assignment_id,
        "assignment_version": assignment_version,
        "route_signature": _route_signature(service_entry, assignment),
        "local_claims": [],
    }


def build_authority(
    assignments: dict,
    routes: dict,
    tick: int,
    partition_started_tick: int | None,
) -> dict:
    """Build a gateway ``reconcile`` authority snapshot.

    ``assignments`` maps ids to ``Assignment`` models (or plain dicts);
    each normalizes to ``{status, version, resource_id, incident_id}``.
    ``routes`` maps resource ids to ``{edge_ids, next_index, ...}``
    records. Pure function: inputs are never mutated.
    """
    auth_assignments: dict[str, dict] = {}
    for aid, rec in (assignments or {}).items():
        if isinstance(rec, dict):
            raw_version = rec.get("version", 0)
            try:
                version = int(raw_version)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                version = 0
            auth_assignments[str(aid)] = {
                "status": str(rec.get("status")),
                "version": version,
                "resource_id": str(rec.get("resource_id", "")),
                "incident_id": str(rec.get("incident_id", "")),
            }
        else:
            auth_assignments[str(aid)] = {
                "status": str(getattr(rec, "status", "")),
                "version": int(getattr(rec, "version", 0) or 0),
                "resource_id": str(getattr(rec, "resource_id", "")),
                "incident_id": str(getattr(rec, "incident_id", "")),
            }
    auth_routes: dict[str, dict] = {}
    for rid, route in (routes or {}).items():
        if isinstance(route, dict):
            edges = route.get("edge_ids", route.get("route_edge_ids", []))
            try:
                edge_list = [str(e) for e in (edges or [])]
            except TypeError:
                edge_list = []
            try:
                index = int(
                    route.get("next_index", route.get("route_next_index", 0))
                )
            except (TypeError, ValueError):
                index = 0
            auth_routes[str(rid)] = {"edge_ids": edge_list, "next_index": index}
    return {
        "tick": int(tick),
        "assignments": auth_assignments,
        "routes": auth_routes,
        "partition_started_tick": partition_started_tick,
    }


def deliver_to_agent(agent: Any, msg_dict: dict, dedup: Any, tick: int) -> str:
    """Deliver one gateway message dict to ``agent`` (consumer side).

    Checks the agent-owned ``dedup`` (``Deduplicator``) first: repeats
    return ``"DUPLICATE"`` without touching the belief. Otherwise the
    message is translated via :func:`to_belief_update` and applied with
    ``agent.update_belief`` — True yields ``"APPLIED"``, False (stale
    version) yields ``"STALE_IGNORED"``. Touches no gateway state
    (delivery/ACK bookkeeping stays with the caller); ``tick`` is
    accepted for call-site symmetry and future audit use.
    """
    _ = tick
    message_id = str(msg_dict.get("message_id", "?"))
    if dedup.check(message_id) == "DUPLICATE":
        return "DUPLICATE"
    applied = agent.update_belief(to_belief_update(msg_dict))
    return "APPLIED" if applied else "STALE_IGNORED"


__all__ = [
    "COORDINATOR_ID",
    "belief_payload_from_snapshot",
    "make_belief_message",
    "to_belief_update",
    "build_agent_report",
    "build_authority",
    "deliver_to_agent",
]
