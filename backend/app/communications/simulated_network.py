"""Deterministic simulated network: delay / loss / duplication / partitions.

Spec: architecture section 8 (communication architecture + gateway
requirements) and Phase 5 Step 03. Stdlib only — this module must never
import FastAPI, DB, or frontend code (AGENTS.md hard rules).

What this model guarantees
---------------------------
* ``sent != delivered != acked != accepted != completed`` (spec section 8).
  This class only decides *deliverability timing*; ACK/accept/completion
  tracking lives in the gateway (parallel step).
* Partitions HOLD traffic: ``can_deliver`` returns ``False`` for held pairs
  and the gateway must keep those messages queued (retryable, logged as
  ``PARTITION_HOLD``) — never silently dropped. Loss (``should_drop``) is
  orthogonal to partitions.
* Island semantics: members of a partition island can still reach each
  other; only cross-boundary traffic is held. Scenario configs never place
  the coordinator id ``DISPATCH-01`` inside an island.

Determinism contract
--------------------
* All randomness comes from ``self._rng = random.Random(seed)``.
* Every new ``message_id`` consumes exactly three draws in fixed order:
  jitter, then loss, then dup — regardless of the configured rates. Repeat
  calls for a known id are served from cache and consume nothing.
* The CALLER (gateway) must first touch messages in sorted ``message_id``
  order. Same seed + same config + same message set/order then yields
  identical drops/delays/duplications, run after run and across snapshots.
* ``to_dict``/``from_dict`` capture the seed, config, RNG state, per-message
  draws and the delivery-tick cache, so a snapshot resumes deterministically
  (wired in Step 05).
"""

import random


class SimulatedNetwork:
    """Seeded chaos model consulted by the communications gateway."""

    def __init__(self, seed: int = 42, config: dict | None = None) -> None:
        cfg = dict(config) if config else {}
        self.seed = seed
        self.delay_ticks = int(cfg.get("delay_ticks", 0))
        self.delay_jitter = int(cfg.get("delay_jitter", 0))
        self.loss_rate = float(cfg.get("loss_rate", 0.0))
        self.dup_rate = float(cfg.get("dup_rate", 0.0))
        self.partitions = self._normalize_partitions(cfg.get("partitions", []))
        if self.delay_ticks < 0:
            raise ValueError("delay_ticks must be >= 0")
        if self.delay_jitter < 0:
            raise ValueError("delay_jitter must be >= 0")
        for name, rate in (("loss_rate", self.loss_rate), ("dup_rate", self.dup_rate)):
            if not 0.0 <= rate <= 1.0:
                raise ValueError(f"{name} must be in [0.0, 1.0], got {rate!r}")
        self._rng = random.Random(seed)
        # Per-message draws: message_id -> (jitter, dropped, extra_copies).
        self._draws: dict[str, tuple[int, bool, int]] = {}
        # Delivery-tick cache: message_id -> tick (first computation wins,
        # so repeated calls are stable even if the dict differs).
        self._delivery_cache: dict[str, int] = {}

    @staticmethod
    def _normalize_partitions(raw: object) -> list[dict]:
        parts: list[dict] = []
        for entry in raw or []:  # type: ignore[union-attr]
            agents = list(entry["agents"])  # type: ignore[index]
            from_tick = int(entry["from_tick"])  # type: ignore[index]
            to_tick = int(entry["to_tick"])  # type: ignore[index]
            if from_tick > to_tick:
                raise ValueError(
                    f"partition from_tick ({from_tick}) > to_tick ({to_tick})"
                )
            parts.append(
                {"agents": agents, "from_tick": from_tick, "to_tick": to_tick}
            )
        return parts

    # -- internal ------------------------------------------------------
    def _ensure_draws(self, message_id: str) -> tuple[int, bool, int]:
        """Draw (jitter, dropped, extra) once per id, in that fixed order."""
        draws = self._draws.get(message_id)
        if draws is None:
            jitter = self._rng.randint(0, self.delay_jitter)
            dropped = self._rng.random() < self.loss_rate
            extra = 1 if (self._rng.random() < self.dup_rate) else 0
            draws = (jitter, dropped, extra)
            self._draws[message_id] = draws
        return draws

    # -- delay / loss / duplication ------------------------------------
    def delivery_tick(self, msg: dict) -> int:
        """Earliest tick the message may be released.

        ``result = created_at_tick + delay_ticks + jitter`` where jitter is
        uniform in ``[0, delay_jitter]``. Cached per ``message_id``: stable
        across calls (first computation wins).
        """
        message_id = msg["message_id"]
        cached = self._delivery_cache.get(message_id)
        if cached is not None:
            return cached
        jitter, _, _ = self._ensure_draws(message_id)
        tick = int(msg["created_at_tick"]) + self.delay_ticks + jitter
        self._delivery_cache[message_id] = tick
        return tick

    def should_drop(self, message_id: str) -> bool:
        """True iff the seeded loss draw falls below ``loss_rate``."""
        return self._ensure_draws(message_id)[1]

    def duplicate_count(self, message_id: str) -> int:
        """Extra copies to deliver: 1 if the seeded draw < dup_rate else 0."""
        return self._ensure_draws(message_id)[2]

    # -- partitions ------------------------------------------------------
    def can_deliver(self, sender: str, recipient: str, tick: int) -> bool:
        """False iff a partition active at ``tick`` (inclusive bounds) has
        exactly one of sender/recipient among its agents.

        Island semantics: island members reach each other, outside pairs
        reach each other, cross-boundary traffic is held for retry.
        """
        for part in self.partitions:
            if part["from_tick"] <= tick <= part["to_tick"]:
                members = part["agents"]
                if (sender in members) != (recipient in members):
                    return False
        return True

    def partitions_at(self, tick: int) -> list[dict]:
        """Active partition records at ``tick`` (for logging/reconciliation).

        Returns copies so callers cannot mutate network state.
        """
        return [
            {
                "agents": list(part["agents"]),
                "from_tick": part["from_tick"],
                "to_tick": part["to_tick"],
            }
            for part in self.partitions
            if part["from_tick"] <= tick <= part["to_tick"]
        ]

    # -- snapshots -------------------------------------------------------
    def to_dict(self) -> dict:
        """JSON-safe snapshot: seed + config + RNG state + draws + cache."""
        version, internal, gauss = self._rng.getstate()
        return {
            "seed": self.seed,
            "config": {
                "delay_ticks": self.delay_ticks,
                "delay_jitter": self.delay_jitter,
                "loss_rate": self.loss_rate,
                "dup_rate": self.dup_rate,
                "partitions": [
                    {
                        "agents": list(part["agents"]),
                        "from_tick": part["from_tick"],
                        "to_tick": part["to_tick"],
                    }
                    for part in self.partitions
                ],
            },
            # random.getstate() tuples -> plain lists for JSON round-trips.
            "rng_state": [version, list(internal), gauss],
            "draws": {
                mid: [jitter, dropped, extra]
                for mid, (jitter, dropped, extra) in self._draws.items()
            },
            "delivery_cache": dict(self._delivery_cache),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SimulatedNetwork":
        """Restore a snapshot from :meth:`to_dict` (post-JSON-load is fine)."""
        obj = cls(seed=data["seed"], config=data.get("config"))
        version, internal, gauss = data["rng_state"]
        obj._rng.setstate((version, tuple(internal), gauss))
        obj._draws = {
            mid: (int(vals[0]), bool(vals[1]), int(vals[2]))
            for mid, vals in data.get("draws", {}).items()
        }
        obj._delivery_cache = {
            mid: int(tick) for mid, tick in data.get("delivery_cache", {}).items()
        }
        return obj
