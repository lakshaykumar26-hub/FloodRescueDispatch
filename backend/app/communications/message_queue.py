"""Priority heap over queued message ids (spec section 8, req 9).

Ordering is (priority, created_at_tick, seq): lower priority value wins
(safety-critical first), then older ticks, then FIFO via the caller seq.
An internal monotonic counter breaks any residual tie so ordering is
stable even if callers reuse a seq value. This queue never mutates
message payloads — it stores ids only.
"""

import heapq


class MessageQueue:
    """Min-heap of queued message ids ordered by priority then age."""

    def __init__(self) -> None:
        self._heap: list[tuple[int, int, int, int, str]] = []
        self._counter = 0

    def push(
        self, message_id: str, priority: int, created_at_tick: int, seq: int
    ) -> None:
        """Enqueue ``message_id`` with the given ordering keys."""
        heapq.heappush(
            self._heap,
            (int(priority), int(created_at_tick), int(seq), self._counter, message_id),
        )
        self._counter += 1

    def pop(self) -> str | None:
        """Remove and return the highest-priority id, or None if empty."""
        if not self._heap:
            return None
        _, _, _, _, message_id = heapq.heappop(self._heap)
        return message_id

    def peek(self) -> str | None:
        """Return the highest-priority id without removing it."""
        if not self._heap:
            return None
        return self._heap[0][4]

    def __len__(self) -> int:
        return len(self._heap)

    def to_dict(self) -> dict:
        """JSON-safe snapshot preserving heap order and the counter."""
        return {
            "entries": [
                {
                    "message_id": mid,
                    "priority": prio,
                    "created_at_tick": created,
                    "seq": seq,
                    "order": order,
                }
                for (prio, created, seq, order, mid) in self._heap
            ],
            "counter": self._counter,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MessageQueue":
        """Restore a snapshot from :meth:`to_dict`."""
        obj = cls()
        entries = []
        for e in data.get("entries", []):
            entries.append(
                (
                    int(e["priority"]),
                    int(e["created_at_tick"]),
                    int(e["seq"]),
                    int(e["order"]),
                    str(e["message_id"]),
                )
            )
        heapq.heapify(entries)
        obj._heap = entries
        obj._counter = int(data.get("counter", len(entries)))
        return obj
