"""Idempotent receiver-side dedup (spec section 8, req 4).

First sighting of a ``message_id`` returns NEW (and records it);
any repeat returns DUPLICATE without re-applying the transition.
Callers feed each gateway delivery through here (Step 05 wires it).
"""

NEW = "NEW"
DUPLICATE = "DUPLICATE"


class Deduplicator:
    """Seen-id set with NEW/DUPLICATE verdicts."""

    def __init__(self) -> None:
        self.seen: set[str] = set()

    def check(self, message_id: str) -> str:
        """Return NEW (records id) or DUPLICATE (already seen)."""
        if message_id in self.seen:
            return DUPLICATE
        self.seen.add(message_id)
        return NEW

    def to_dict(self) -> dict:
        """JSON-safe snapshot (sorted list for determinism)."""
        return {"seen": sorted(self.seen)}

    @classmethod
    def from_dict(cls, data: dict) -> "Deduplicator":
        """Restore a snapshot from :meth:`to_dict`."""
        obj = cls()
        obj.seen = set(str(x) for x in data.get("seen", []))
        return obj
