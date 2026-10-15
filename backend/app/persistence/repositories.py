"""Repository functions over :class:`Database` (stdlib sqlite3).

All writes are keyed by ``(simulation_id, tick)``. ``assignment_history``
is append-only (INSERT only, never UPDATE/DELETE). Snapshots store the
Phase-1 JSON format (``version:1``) so a DB round-trip equals an in-memory
restore. Message statuses stay distinct: QUEUED/DELIVERED/ACKED/EXPIRED.
"""

from __future__ import annotations

import copy
import datetime as _dt
import json
from typing import Any

from .database import Database

# High-volume per-tick movement noise is never persisted (write policy:
# periodic snapshots + meaningful events, not every micro-mutation).
SKIP_EVENT_KINDS = frozenset(
    {
        "MOVE",
        "ROUTE_SET",
        "BOAT_TRANSITION",
        "TEAM_TRANSITION",
        "BOARD",
        "BOARD_SKIPPED",
        "SHELTER_RESERVE",
        "SHELTER_RELEASE",
        "SHELTER_CHECKIN",
        "DISEMBARK",
        "LIFECYCLE_SKIP",
    }
)

# Event-log kinds that become append-only assignment_history rows.
HISTORY_KINDS = frozenset(
    {
        "COMMITTED",
        "ACKNOWLEDGED",
        "IN_PROGRESS",
        "COMPLETED",
        "CANCELLED",
        "EXPIRED",
        "REJECTED",
        "REQUIRES_RECONCILIATION",
        "REPLAN_CHAIN",
        "REPLAN_FAILED",
        "REPLAN",
        "RECONCILED",
    }
)


def _now_iso() -> str:
    return _dt.datetime.now(_dt.UTC).isoformat()


def _dump(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, default=str)


# -- runs ------------------------------------------------------------


def save_run(
    db: Database,
    simulation_id: str,
    scenario_name: str,
    strategy: str,
    seed: int,
    status: str,
    tick: int,
    max_ticks: int,
) -> None:
    now = _now_iso()
    db.execute(
        """INSERT INTO simulation_runs
           (simulation_id, scenario_name, strategy, seed, status, tick,
            max_ticks, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(simulation_id) DO UPDATE SET
             status=excluded.status, tick=excluded.tick,
             max_ticks=excluded.max_ticks, updated_at=excluded.updated_at""",
        (simulation_id, scenario_name, strategy, int(seed), status, int(tick),
         int(max_ticks), now, now),
    )


def get_run(db: Database, simulation_id: str) -> dict | None:
    rows = db.execute(
        "SELECT * FROM simulation_runs WHERE simulation_id = ?", (simulation_id,)
    )
    return rows[0] if rows else None


# -- events ----------------------------------------------------------


def save_events_batch(
    db: Database, simulation_id: str, events: list[dict], seq_start: int = 0
) -> int:
    """Persist meaningful events; skip per-tick movement spam. Returns rows."""
    rows = [
        (
            simulation_id,
            int(e.get("tick", 0)),
            seq_start + i,
            str(e.get("kind", "")),
            str(e.get("actor", "")),
            _dump(e.get("detail", {})),
        )
        for i, e in enumerate(events)
        if str(e.get("kind", "")) not in SKIP_EVENT_KINDS
    ]
    if rows:
        db.executemany(
            """INSERT INTO simulation_events
               (simulation_id, tick, seq, kind, actor, detail)
               VALUES (?, ?, ?, ?, ?, ?)""",
            rows,
        )
    return len(rows)


def count_events(db: Database, simulation_id: str) -> int:
    return db.count(
        "simulation_events", "simulation_id = ?", (simulation_id,)
    )


# -- assignments -----------------------------------------------------


def _assignment_row(
    simulation_id: str, tick: int, aid: str, a: Any
) -> tuple:
    if isinstance(a, dict):
        get = a.get
    else:
        def get(key: str, default: Any = None) -> Any:
            return getattr(a, key, default)

    history = get("history", []) or []
    route = get("route_edge_ids", []) or []
    return (
        simulation_id,
        str(aid),
        int(tick),
        int(get("version", 1) or 1),
        str(get("proposal_id", "") or ""),
        str(get("incident_id", "") or ""),
        str(get("resource_id", "") or ""),
        str(get("resource_kind", "") or ""),
        str(get("shelter_id", "") or ""),
        int(get("seats", 0) or 0),
        _dump(route),
        str(get("status", "") or ""),
        float(get("cost", 0.0) or 0.0),
        int(get("created_tick", 0) or 0),
        _dump(history),
    )


def save_assignment(
    db: Database, simulation_id: str, tick: int, assignment_id: str, a: Any
) -> None:
    db.execute(
        """INSERT INTO assignments
           (simulation_id, assignment_id, tick, version, proposal_id,
            incident_id, resource_id, resource_kind, shelter_id, seats,
            route_edge_ids, status, cost, created_tick, history)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(simulation_id, assignment_id) DO UPDATE SET
             tick=excluded.tick, version=excluded.version,
             status=excluded.status, route_edge_ids=excluded.route_edge_ids,
             history=excluded.history""",
        _assignment_row(simulation_id, tick, assignment_id, a),
    )


def get_assignment(
    db: Database, simulation_id: str, assignment_id: str
) -> dict | None:
    rows = db.execute(
        "SELECT * FROM assignments WHERE simulation_id = ? AND assignment_id = ?",
        (simulation_id, assignment_id),
    )
    return rows[0] if rows else None


def append_history(
    db: Database,
    simulation_id: str,
    tick: int,
    assignment_id: str,
    from_status: str,
    to_status: str,
    reason: str,
    actor: str,
) -> None:
    db.execute(
        """INSERT INTO assignment_history
           (simulation_id, tick, assignment_id, from_status, to_status,
            reason, actor)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            simulation_id,
            int(tick),
            str(assignment_id),
            str(from_status or ""),
            str(to_status or ""),
            str(reason or ""),
            str(actor or ""),
        ),
    )


def history_for(
    db: Database, simulation_id: str, assignment_id: str
) -> list[dict]:
    return db.execute(
        """SELECT * FROM assignment_history
           WHERE simulation_id = ? AND assignment_id = ?
           ORDER BY id ASC""",
        (simulation_id, assignment_id),
    )


def _history_row_from_log(entry: dict) -> tuple[str, str, str, str, str] | None:
    kind = str(entry.get("kind", ""))
    if kind not in HISTORY_KINDS:
        return None
    detail = entry.get("detail", {}) or {}
    aid = (
        detail.get("assignment_id")
        or detail.get("new_assignment_id")
        or detail.get("old_assignment_id")
        or detail.get("proposal_id")
        or "-"
    )
    return (
        str(aid),
        str(detail.get("from", "")),
        kind,
        str(detail.get("reason", "")),
        str(entry.get("actor", "")),
    )


def sync_assignments(
    db: Database,
    simulation_id: str,
    tick: int,
    assignments: dict,
    new_log_entries: list[dict],
) -> None:
    """Upsert current assignment rows + append history for new log entries."""
    for aid, record in assignments.items():
        save_assignment(db, simulation_id, tick, str(aid), record)
    for entry in new_log_entries:
        parsed = _history_row_from_log(entry)
        if parsed is None:
            continue
        aid, frm, to, reason, actor = parsed
        append_history(
            db, simulation_id, int(entry.get("tick", 0)), aid, frm, to, reason, actor
        )


# -- messages --------------------------------------------------------


def save_message(
    db: Database,
    simulation_id: str,
    tick: int,
    message_id: str,
    type: str,
    sender_id: str,
    recipient_id: str,
    status: str,
    payload: dict | None = None,
) -> None:
    db.execute(
        """INSERT INTO communication_messages
           (simulation_id, message_id, tick, type, sender_id, recipient_id,
            status, payload)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(simulation_id, message_id) DO UPDATE SET
             tick=excluded.tick, status=excluded.status,
             payload=excluded.payload""",
        (
            simulation_id,
            message_id,
            int(tick),
            type,
            sender_id,
            recipient_id,
            status,
            _dump(payload or {}),
        ),
    )


def update_message_status(
    db: Database, simulation_id: str, message_id: str, tick: int, status: str
) -> None:
    db.execute(
        """UPDATE communication_messages SET status = ?, tick = ?
           WHERE simulation_id = ? AND message_id = ?""",
        (status, int(tick), simulation_id, message_id),
    )


def get_message(
    db: Database, simulation_id: str, message_id: str
) -> dict | None:
    rows = db.execute(
        """SELECT * FROM communication_messages
           WHERE simulation_id = ? AND message_id = ?""",
        (simulation_id, message_id),
    )
    return rows[0] if rows else None


def sync_messages(db: Database, simulation_id: str, tick: int, gateway: Any) -> None:
    """Upsert every gateway store message with its distinct tracker status."""
    for mid, stored in gateway.store.items():
        msg = stored.get("message", {}) if isinstance(stored, dict) else {}
        status = gateway.tracker.status_of(mid) or "QUEUED"
        save_message(
            db,
            simulation_id,
            int(tick),
            str(mid),
            str(msg.get("type", "")),
            str(msg.get("sender_id", "")),
            str(msg.get("recipient_id", "")),
            str(status),
            dict(msg.get("payload", {}) or {}),
        )


# -- reports ---------------------------------------------------------


def save_report(
    db: Database, simulation_id: str, tick: int, claim: dict
) -> None:
    db.execute(
        """INSERT INTO reports
           (simulation_id, tick, report_id, subject_id, claim, source,
            observed_at_tick, received_at_tick, confidence,
            verification_status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            simulation_id,
            int(tick),
            str(claim.get("report_id", "")),
            str(claim.get("subject_id", "")),
            str(claim.get("claim", "")),
            str(claim.get("source", "")),
            int(claim.get("observed_at_tick", 0) or 0),
            int(claim.get("received_at_tick", 0) or 0),
            float(claim.get("confidence", 0.0) or 0.0),
            str(claim.get("verification_status", "UNVERIFIED")),
        ),
    )


# -- snapshots -------------------------------------------------------


def save_snapshot(
    db: Database, simulation_id: str, tick: int, snapshot: dict
) -> None:
    snap = copy.deepcopy(snapshot)
    db.execute(
        """INSERT INTO state_snapshots
           (simulation_id, tick, version, snapshot_json)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(simulation_id, tick) DO UPDATE SET
             version=excluded.version, snapshot_json=excluded.snapshot_json""",
        (
            simulation_id,
            int(tick),
            int(snap.get("version", 1)),
            _dump(snap),
        ),
    )


def load_snapshot(db: Database, simulation_id: str, tick: int) -> dict | None:
    rows = db.execute(
        "SELECT snapshot_json FROM state_snapshots WHERE simulation_id = ? AND tick = ?",
        (simulation_id, int(tick)),
    )
    if not rows:
        return None
    return json.loads(rows[0]["snapshot_json"])


def list_snapshot_ticks(db: Database, simulation_id: str) -> list[int]:
    rows = db.execute(
        """SELECT tick FROM state_snapshots WHERE simulation_id = ?
           ORDER BY tick ASC""",
        (simulation_id,),
    )
    return [int(r["tick"]) for r in rows]


# -- metrics ---------------------------------------------------------


def save_metrics(
    db: Database, simulation_id: str, tick: int, summary: dict
) -> None:
    db.execute(
        """INSERT INTO simulation_metrics
           (simulation_id, tick, strategy, served, unserved, committed,
            rejected_by_reason, snapshots)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(simulation_id, tick) DO UPDATE SET
             strategy=excluded.strategy, served=excluded.served,
             unserved=excluded.unserved, committed=excluded.committed,
             rejected_by_reason=excluded.rejected_by_reason,
             snapshots=excluded.snapshots""",
        (
            simulation_id,
            int(tick),
            str(summary.get("strategy", "")),
            int(summary.get("served", 0)),
            int(summary.get("unserved", 0)),
            int(summary.get("committed", 0)),
            _dump(summary.get("rejected_by_reason", {})),
            _dump(summary.get("snapshots", [])),
        ),
    )


def get_metrics(db: Database, simulation_id: str, tick: int) -> dict | None:
    rows = db.execute(
        """SELECT * FROM simulation_metrics
           WHERE simulation_id = ? AND tick = ?""",
        (simulation_id, int(tick)),
    )
    return rows[0] if rows else None


__all__ = [
    "HISTORY_KINDS",
    "SKIP_EVENT_KINDS",
    "append_history",
    "count_events",
    "get_assignment",
    "get_message",
    "get_metrics",
    "get_run",
    "history_for",
    "list_snapshot_ticks",
    "load_snapshot",
    "save_assignment",
    "save_events_batch",
    "save_message",
    "save_metrics",
    "save_report",
    "save_run",
    "save_snapshot",
    "sync_assignments",
    "sync_messages",
    "update_message_status",
]
