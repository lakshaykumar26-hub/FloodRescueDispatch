"""Deterministic integer simulation clock.

Ordering contract: the engine must apply all events scheduled for tick T
(including closures and arrivals due at T) BEFORE moving resources during
tick T. That is, for each tick T the order is:

    clock.advance() -> pop_due(T) / apply events for T -> advance_positions(T)

so a closure scheduled for tick 40 is already closed when movement for
tick 40 is evaluated. Wall-clock time is never used for ordering; ``tick``
ints are the single source of simulation order (AGENTS.md hard rule 4).
"""

from __future__ import annotations


class Clock:
    """Integer tick counter with no wall-clock dependence."""

    def __init__(self, start: int = 0) -> None:
        if start < 0:
            raise ValueError("start must be >= 0")
        self._start = start
        self.tick: int = start

    def advance(self, n: int = 1) -> int:
        """Advance by ``n`` ticks (default 1) and return the new tick."""
        if n < 0:
            raise ValueError("n must be >= 0")
        self.tick += n
        return self.tick

    def reset(self, seed: int | None = None) -> int:
        """Reset to the start tick and return it.

        ``seed`` is accepted (and ignored) so scenario runners can pass the
        scenario's ``random_seed`` through a uniform reset call without
        affecting the deterministic tick counter.
        """
        _ = seed
        self.tick = self._start
        return self.tick
