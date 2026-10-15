"""API package: thin validated handlers over the engine + gateway.

Each module owns one router and delegates to :mod:`api.store`
(validate -> call engine/gateway -> return; no dispatch logic here).
"""

from . import (
    assignments,
    communications,
    events,
    incidents,
    metrics,
    simulations,
    state,
)

__all__ = [
    "assignments",
    "communications",
    "events",
    "incidents",
    "metrics",
    "simulations",
    "state",
]
