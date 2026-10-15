"""Edge-list validation primitive for the safety validator (Phase 2).

Pure function over :class:`World`; no clock, no I/O, no FastAPI/DB imports.
"""

from typing import Sequence

from ..simulation.world import EdgeMode, World


def is_route_valid(
    world: World, edge_ids: Sequence[str], mode: EdgeMode
) -> tuple[bool, str]:
    """Validate that ``edge_ids`` form a traversable route for ``mode``.

    Checks in order per edge: unknown edge -> ``UNKNOWN_EDGE:<id>``; mode
    mismatch -> ``MODE_MISMATCH``; closed edge -> ``EDGE_CLOSED:<id>``;
    non-positive capacity -> ``ZERO_CAPACITY:<id>``. Returns ``(True, "OK")``
    when every edge passes.
    """
    for eid in edge_ids:
        edge = world.edges.get(eid)
        if edge is None:
            return (False, f"UNKNOWN_EDGE:{eid}")
        if edge.mode != mode:
            return (False, "MODE_MISMATCH")
        if edge.status == "closed":
            return (False, f"EDGE_CLOSED:{eid}")
        if edge.capacity <= 0:
            return (False, f"ZERO_CAPACITY:{eid}")
    return (True, "OK")
