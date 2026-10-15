"""Deterministic scheduler for tick-ordered simulation disruptions.

Holds ``{tick, kind, payload, event_id}`` records. Kinds used today are
``CLOSURE``, ``FLOOD_RISE`` and ``INCIDENT_ARRIVAL``; any other string kind
is stored and returned identically so future failure/overflow kinds work
without scheduler changes. A seeded ``random.Random`` instance is kept for
any future jitter; ordering itself is strictly ``(tick, event_id)`` so the
same seed plus the same pushes always yield the same ``pop_due`` sequence.
"""

from __future__ import annotations

import random


class EventScheduler:
    """In-memory tick-ordered event queue."""

    def __init__(self, seed: int = 42) -> None:
        self.seed = seed
        self._rng = random.Random(seed)
        self._events: list[dict] = []

    def __len__(self) -> int:
        return len(self._events)

    @property
    def rng(self) -> random.Random:
        """Seeded RNG reserved for future jitter (ordering never uses it)."""
        return self._rng

    def push(self, tick: int, kind: str, payload: dict, event_id: str) -> dict:
        """Schedule one event. Returns the stored record."""
        if tick < 0:
            raise ValueError("tick must be >= 0")
        if not kind:
            raise ValueError("kind must be a non-empty string")
        if not event_id:
            raise ValueError("event_id must be a non-empty string")
        record = {
            "tick": tick,
            "kind": kind,
            "payload": dict(payload),
            "event_id": event_id,
        }
        self._events.append(record)
        return dict(record)

    def peek(self) -> dict | None:
        """Return a copy of the earliest ``(tick, event_id)`` event, if any."""
        if not self._events:
            return None
        earliest = min(self._events, key=lambda e: (e["tick"], e["event_id"]))
        return {
            "tick": earliest["tick"],
            "kind": earliest["kind"],
            "payload": dict(earliest["payload"]),
            "event_id": earliest["event_id"],
        }

    def pending(self) -> list[dict]:
        """Return copies of all not-yet-delivered events (for snapshots)."""
        return [
            {
                "tick": e["tick"],
                "kind": e["kind"],
                "payload": dict(e["payload"]),
                "event_id": e["event_id"],
            }
            for e in self._events
        ]

    def pop_due(self, tick: int) -> list[dict]:
        """Remove and return all events with ``event.tick <= tick``.

        Results are ordered by ``(tick, event_id)`` regardless of push
        order, so two events at the same tick fire in ``event_id`` order
        and an event at tick 40 is never returned by ``pop_due(39)``.
        """
        due = [e for e in self._events if e["tick"] <= tick]
        due.sort(key=lambda e: (e["tick"], e["event_id"]))
        due_ids = {id(e) for e in due}
        self._events = [e for e in self._events if id(e) not in due_ids]
        return [
            {
                "tick": e["tick"],
                "kind": e["kind"],
                "payload": dict(e["payload"]),
                "event_id": e["event_id"],
            }
            for e in due
        ]
