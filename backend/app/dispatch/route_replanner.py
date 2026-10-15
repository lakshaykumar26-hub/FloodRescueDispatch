"""Shelter-leg alternatives for dispatch bids (Phase 2 Step 03).

Thin wrapper over routing: list shelters that can take ``seats_needed``
reachable from ``origin_node`` via ``mode``, sorted by ETA. Full use
arrives in Phase 4 (dynamic replanning after closures/overflow); here it
only feeds the bidder with deterministic shelter options.

Pure function over :class:`World`; no FastAPI/DB imports.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from ..routing.pathfinder import find_route

if TYPE_CHECKING:
    from ..simulation.world import EdgeMode, World


def shelter_options(
    world: World, origin_node: str, mode: str, seats_needed: int
) -> list[tuple[str, dict]]:
    """Return ``[(shelter_id, route)]`` sorted by ``(eta_ticks, shelter_id)``.

    Only shelters with ``world.shelter_remaining(sid) >= seats_needed`` and
    a non-``None`` ``find_route(world, origin_node, shelter.node_id, mode)``
    are included. Shelter iteration is in ``shelter_id`` order so the result
    is deterministic.
    """
    options: list[tuple[str, dict]] = []
    for sid in sorted(world.shelters):
        shelter = world.shelters[sid]
        if world.shelter_remaining(sid) < seats_needed:
            continue
        route = find_route(world, origin_node, shelter.node_id, cast("EdgeMode", mode))
        if route is None:
            continue
        options.append((sid, route))
    options.sort(key=lambda item: (item[1]["eta_ticks"], item[0]))
    return options


__all__ = ["shelter_options"]
