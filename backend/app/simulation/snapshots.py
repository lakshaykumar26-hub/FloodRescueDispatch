"""JSON-serializable world snapshots for restore and replay."""

from __future__ import annotations

import copy
from typing import Any

from .world import World

SNAPSHOT_VERSION = 1


def take_snapshot(world: World, event_log: list[dict], seed: int | None = None) -> dict:
    """Capture ``{version, tick, seed, world, event_log}`` (deep-copied)."""
    return {
        "version": SNAPSHOT_VERSION,
        "tick": world.tick,
        "seed": world.seed if seed is None else seed,
        "world": world.to_dict(),
        "event_log": copy.deepcopy(event_log),
    }


def restore(data: dict[str, Any]) -> tuple[World, list[dict]]:
    """Rebuild ``(World, event_log)`` from :func:`take_snapshot` output."""
    if data.get("version") != SNAPSHOT_VERSION:
        raise ValueError(
            f"unsupported snapshot version: {data.get('version')!r} "
            f"(expected {SNAPSHOT_VERSION})"
        )
    world = World.from_dict(data["world"])
    event_log = copy.deepcopy(data.get("event_log", []))
    return world, event_log
