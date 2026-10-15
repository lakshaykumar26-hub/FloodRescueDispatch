"""Per-message delivery states (spec section 8, req 2).

States stay honest: QUEUED (persisted, not yet delivered), DELIVERED
(received by the channel, NOT accepted), ACKED (receipt confirmed, never
acceptance), EXPIRED (tick passed ``expires_at_tick``), REJECTED
(explicit refusal). Terminal states ACKED/EXPIRED/REJECTED ignore
further transitions (return False).
"""

TERMINAL_STATUSES = frozenset({"ACKED", "EXPIRED", "REJECTED"})


class DeliveryTracker:
    """Tracks status + attempt log per message id."""

    def __init__(self) -> None:
        self._status: dict[str, str] = {}
        self._attempts: dict[str, list[dict]] = {}

    def register(self, message_id: str) -> bool:
        """Record a new id as QUEUED. Returns False if already known."""
        if message_id in self._status:
            return False
        self._status[message_id] = "QUEUED"
        self._attempts[message_id] = []
        return True

    def _transition(self, message_id: str, new_status: str) -> bool:
        current = self._status.get(message_id)
        if current is None:
            return False
        if current in TERMINAL_STATUSES:
            return False
        self._status[message_id] = new_status
        return True

    def mark_delivered(self, message_id: str, tick: int, attempt: int = 0) -> bool:
        """QUEUED/DELIVERED -> DELIVERED + attempt log. Terminal -> False."""
        current = self._status.get(message_id)
        if current is None or current in TERMINAL_STATUSES:
            return False
        if current not in ("QUEUED", "DELIVERED"):
            return False
        self._status[message_id] = "DELIVERED"
        self._attempts[message_id].append(
            {"tick": int(tick), "result": "DELIVER", "attempt": int(attempt)}
        )
        return True

    def mark_acked(self, message_id: str, tick: int, note: str = "") -> bool:
        """QUEUED/DELIVERED -> ACKED. Terminal/unknown -> False."""
        current = self._status.get(message_id)
        if current is None or current in TERMINAL_STATUSES:
            return False
        if current not in ("QUEUED", "DELIVERED"):
            return False
        self._status[message_id] = "ACKED"
        self._attempts[message_id].append(
            {"tick": int(tick), "result": "ACK", "note": str(note)}
        )
        return True

    def mark_expired(self, message_id: str, tick: int) -> bool:
        """Move a non-terminal id to EXPIRED. Terminal/unknown -> False."""
        current = self._status.get(message_id)
        if current is None or current in TERMINAL_STATUSES:
            return False
        self._status[message_id] = "EXPIRED"
        self._attempts[message_id].append({"tick": int(tick), "result": "EXPIRE"})
        return True

    def mark_rejected(self, message_id: str, tick: int, code: str = "") -> bool:
        """Move a non-terminal id to REJECTED. Terminal/unknown -> False."""
        current = self._status.get(message_id)
        if current is None or current in TERMINAL_STATUSES:
            return False
        self._status[message_id] = "REJECTED"
        self._attempts[message_id].append(
            {"tick": int(tick), "result": "REJECT", "code": str(code)}
        )
        return True

    def record_attempt(self, message_id: str, tick: int, result: str) -> bool:
        """Append a non-terminal attempt (e.g. DROP) without changing status.

        Returns False for unknown ids or terminal states.
        """
        if message_id not in self._status:
            return False
        if self._status[message_id] in TERMINAL_STATUSES:
            return False
        self._attempts[message_id].append({"tick": int(tick), "result": str(result)})
        return True

    def status_of(self, message_id: str) -> str | None:
        """Current status string, or None if never registered."""
        return self._status.get(message_id)

    def attempts_of(self, message_id: str) -> list[dict]:
        """Copy of the attempt log (empty list if unknown)."""
        return [dict(a) for a in self._attempts.get(message_id, [])]

    def to_dict(self) -> dict:
        """JSON-safe snapshot of statuses + attempt logs."""
        return {
            "status": dict(self._status),
            "attempts": {
                mid: [dict(a) for a in attempts]
                for mid, attempts in self._attempts.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DeliveryTracker":
        """Restore a snapshot from :meth:`to_dict`."""
        obj = cls()
        obj._status = {str(k): str(v) for k, v in data.get("status", {}).items()}
        obj._attempts = {
            str(k): [dict(a) for a in v]
            for k, v in data.get("attempts", {}).items()
        }
        for mid in obj._status:
            obj._attempts.setdefault(mid, [])
        return obj
