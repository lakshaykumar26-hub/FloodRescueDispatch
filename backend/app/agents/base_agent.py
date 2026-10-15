"""Base agent with a private local belief, separated from the global World state.

Agents must NEVER receive a live ``World`` reference. The caller passes a
plain-dict snapshot (already deep-copied) into :meth:`BaseAgent.sense`, and
all later refinements arrive as versioned message dicts via
:meth:`BaseAgent.update_belief`.
"""

import copy


#: Belief edge-record shape. Each entry of ``local_belief["edges"]`` carries
#: at least these keys (mirroring the ``Edge`` fields the agent
#: is allowed to know about).
EDGE_RECORD_KEYS = (
    "edge_id",
    "from_node",
    "to_node",
    "mode",
    "travel_time",
    "status",
    "risk_level",
    "capacity",
)


class BaseAgent:
    """Plain-Python agent base class with an isolated local belief."""

    kind = "base"

    def __init__(self, agent_id: str) -> None:
        self.id = agent_id
        self.kind = type(self).kind
        self.local_belief = {
            "edges": {},
            "shelters": {},
            "assignments": [],
            "belief_version": 0,
        }
        #: World tick of the snapshot/message that last refreshed the
        #: belief (Step 05 partition probe: a partitioned agent's
        #: ``world_tick_at_read`` stays behind the global tick).
        self.world_tick_at_read: int = 0
        self.inbox: list = []
        self.audit: list = []

    def sense(self, snapshot: dict) -> None:
        """Copy a plain-dict world snapshot into the local belief.

        ``snapshot`` is a PLAIN dict (already deep-copied by the caller --
        never a ``World``). Phase 3 sense = full copy while comms are
        perfect; Phase 5 will restrict delivery (partial/stale/filtered
        snapshots) without changing this signature.
        """
        self.local_belief["edges"] = copy.deepcopy(snapshot.get("edges", {}))
        self.local_belief["shelters"] = copy.deepcopy(snapshot.get("shelters", {}))
        self.local_belief["assignments"] = copy.deepcopy(snapshot.get("assignments", []))
        self.local_belief["belief_version"] += 1
        tick_read = snapshot.get("tick", snapshot.get("world_tick", 0))
        self.world_tick_at_read = int(tick_read) if tick_read is not None else 0

    def update_belief(self, message: dict) -> bool:
        """Apply a versioned belief message; ignore stale ones.

        ``message`` shape: ``{message_id, type, version: int,
        edges?: {...}, shelters?: {...}, assignments?: [...]}``. Only the
        fields the message carries are mutated. Returns True when applied,
        False when ignored as stale.
        """
        version = message.get("version", 0)
        if version <= self.local_belief["belief_version"]:
            self.audit.append(
                {
                    "event": "STALE_BELIEF_IGNORED",
                    "tick": message.get("tick"),
                    "message_id": message.get("message_id"),
                }
            )
            return False
        if "edges" in message:
            self.local_belief["edges"] = copy.deepcopy(message["edges"])
        if "shelters" in message:
            self.local_belief["shelters"] = copy.deepcopy(message["shelters"])
        if "assignments" in message:
            self.local_belief["assignments"] = copy.deepcopy(message["assignments"])
        self.local_belief["belief_version"] = version
        world_tick = message.get("world_tick", message.get("tick", self.world_tick_at_read))
        self.world_tick_at_read = (
            int(world_tick) if world_tick is not None else self.world_tick_at_read
        )
        self.audit.append(
            {
                "event": "BELIEF_UPDATED",
                "tick": message.get("tick"),
                "message_id": message.get("message_id"),
                "version": version,
            }
        )
        return True
