"""Store-and-forward gateway: validate -> queue -> deliver -> ACK -> retry.

ACKED means receipt confirmed, NEVER acceptance or completion. A message
that is DELIVERED has reached the channel; only an explicit ``ack()``
moves it to ACKED, and even ACKED does not mean the assignment was
accepted or completed (``sent != delivered != acked != accepted !=
completed``, spec section 8). Acceptance/completion are tracked by the
dispatch layer, not here.

Pipeline per message: ``send()`` validates and enqueues; ``pump(tick)``
attempts delivery via the simulated network adapter (expiry, partition
hold, delay, loss, duplicate); ``ack()`` confirms receipt; ``retry_sweep``
counts retry-eligible items (they retry naturally on the next pump).
Every lifecycle event is audited with tick + event + message_id + detail.
"""

import copy

from pydantic import ValidationError

from .deduplicator import Deduplicator
from .delivery_tracker import TERMINAL_STATUSES, DeliveryTracker
from .message_queue import MessageQueue
from .models import Message, validate_message

PRIORITY: dict[str, int] = {
    "ASSIGNMENT_CANCELLED": 0,
    "SHELTER_CAPACITY_CHANGED": 1,
    "HAZARD_REPORTED": 1,
    "ASSIGNMENT_OFFER": 2,
    "MESSAGE_ACK": 2,
}

DEFAULT_PRIORITY = 3


def priority_for(message_type: str) -> int:
    """Priority class for a message type (lower = delivered first)."""
    return PRIORITY.get(message_type, DEFAULT_PRIORITY)


class Gateway:
    """Priority-queued, audited store-and-forward hub over a network adapter."""

    def __init__(
        self,
        network: object,
        simulation_id: str = "SIM-001",
        sender_ids: set[str] | None = None,
    ) -> None:
        self.network = network
        self.simulation_id = simulation_id
        self.sender_ids = set(sender_ids) if sender_ids is not None else None
        # message_id -> {"message": dict, "priority": int}
        self.store: dict[str, dict] = {}
        self.tracker = DeliveryTracker()
        # Send-side dedup: repeat send() of the same id -> DUPLICATE_SEND.
        self.dedup = Deduplicator()
        self.queue = MessageQueue()
        self.audit: list[dict] = []
        self._seq = 0
        # Ids already audited once for DELAYED (prevents audit spam).
        self._delayed_audited: set[str] = set()

    # -- internals -----------------------------------------------------
    def _audit(self, tick: int, event: str, message_id: str, detail: str = "") -> None:
        self.audit.append(
            {
                "tick": int(tick),
                "event": str(event),
                "message_id": str(message_id),
                "detail": str(detail),
            }
        )

    # -- send ----------------------------------------------------------
    def send(self, msg: dict, tick: int) -> tuple[bool, str]:
        """Validate, persist, and priority-enqueue a message envelope."""
        try:
            message = Message(**msg)
        except ValidationError as exc:
            mid = str(msg.get("message_id", "?")) if isinstance(msg, dict) else "?"
            self._audit(tick, "SEND_REJECTED", mid, f"SCHEMA_INVALID: {exc}")
            return (False, "SCHEMA_INVALID")
        ok, code = validate_message(message, tick)
        if not ok:
            self._audit(tick, "SEND_REJECTED", message.message_id, code)
            return (False, code)
        if self.sender_ids is not None and message.sender_id not in self.sender_ids:
            self._audit(tick, "SEND_REJECTED", message.message_id, "UNKNOWN_SENDER")
            return (False, "UNKNOWN_SENDER")
        if self.dedup.check(message.message_id) == "DUPLICATE":
            self._audit(tick, "DUPLICATE_SEND", message.message_id, "already queued")
            return (True, "DUPLICATE_SEND")
        msg_dict = message.model_dump()
        priority = priority_for(message.type)
        self.store[message.message_id] = {"message": msg_dict, "priority": priority}
        self.tracker.register(message.message_id)
        self.queue.push(
            message.message_id, priority, message.created_at_tick, self._seq
        )
        self._seq += 1
        self._audit(
            tick,
            "SEND",
            message.message_id,
            f"{message.type} {message.sender_id}->{message.recipient_id} pri={priority}",
        )
        return (True, "QUEUED")

    # -- pump ----------------------------------------------------------
    def pump(self, tick: int) -> list[dict]:
        """Attempt delivery of queued messages at ``tick``.

        Returns deliveries: [{message: dict, delivery_kind: FIRST|DUPLICATE}].
        The caller feeds each delivery to a consumer-side Deduplicator
        (Step 05 wires it) so duplicate copies never double-apply.
        """
        deliveries: list[dict] = []
        batch: list[str] = []
        while len(self.queue) > 0:
            mid = self.queue.pop()
            if mid is not None:
                batch.append(mid)
        # Deterministic first-touch: seed RNG draws in sorted id order so
        # the same seed + message set always yields identical delay/loss/dup
        # even though actual release follows priority order.
        for mid in sorted(batch):
            try:
                self.network.should_drop(mid)  # type: ignore[union-attr]
            except AttributeError:
                break
        for mid in batch:
            status = self.tracker.status_of(mid)
            if status is None:
                continue
            if status in TERMINAL_STATUSES:
                continue
            entry = self.store.get(mid)
            if entry is None:
                continue
            msg_dict = entry["message"]
            sender = msg_dict["sender_id"]
            recipient = msg_dict["recipient_id"]
            if int(tick) > int(msg_dict["expires_at_tick"]):
                self.tracker.mark_expired(mid, tick)
                self._audit(tick, "EXPIRE", mid, "tick>expires_at_tick")
                continue
            if not self.network.can_deliver(sender, recipient, int(tick)):  # type: ignore[union-attr]
                self.queue.push(mid, entry["priority"], msg_dict["created_at_tick"], self._seq)
                self._seq += 1
                self._audit(tick, "PARTITION_HOLD", mid, f"{sender}->{recipient}")
                continue
            if int(self.network.delivery_tick(msg_dict)) > int(tick):  # type: ignore[union-attr]
                self.queue.push(mid, entry["priority"], msg_dict["created_at_tick"], self._seq)
                self._seq += 1
                if not self.tracker.attempts_of(mid) and mid not in self._delayed_audited:
                    self._audit(tick, "DELAYED", mid, "delivery_tick>tick")
                    self._delayed_audited.add(mid)
                continue
            if bool(self.network.should_drop(mid)):  # type: ignore[union-attr]
                self.tracker.record_attempt(mid, tick, "DROP")
                self.queue.push(mid, entry["priority"], msg_dict["created_at_tick"], self._seq)
                self._seq += 1
                self._audit(tick, "DROP", mid, "seeded loss; retryable until expiry")
                continue
            attempt_no = len(self.tracker.attempts_of(mid))
            self.tracker.mark_delivered(mid, tick, attempt_no)
            self._audit(tick, "DELIVER", mid, "FIRST")
            deliveries.append(
                {"message": copy.deepcopy(msg_dict), "delivery_kind": "FIRST"}
            )
            extra = int(self.network.duplicate_count(mid))  # type: ignore[union-attr]
            for _ in range(extra):
                self._audit(tick, "DELIVER_DUP", mid, "seeded duplication")
                deliveries.append(
                    {"message": copy.deepcopy(msg_dict), "delivery_kind": "DUPLICATE"}
                )
        return deliveries

    # -- ack -----------------------------------------------------------
    def ack(
        self, message_id: str, tick: int, note: str = ""
    ) -> tuple[bool, str]:
        """Confirm receipt of a known message.

        ACKED = receipt confirmed, never acceptance/completion. Acceptance
        is decided by the dispatch layer, not this gateway.
        """
        status = self.tracker.status_of(message_id)
        if status is None:
            self._audit(tick, "ACK_REJECTED", message_id, "UNKNOWN_MESSAGE")
            return (False, "UNKNOWN_MESSAGE")
        if status in TERMINAL_STATUSES:
            self._audit(tick, "ACK_REJECTED", message_id, "ACK_ON_TERMINAL")
            return (False, "ACK_ON_TERMINAL")
        self.tracker.mark_acked(message_id, tick, note)
        self._audit(tick, "ACK", message_id, note)
        return (True, "ACKED")

    # -- status helpers ------------------------------------------------
    def pending_for(self, recipient: str) -> list[str]:
        """Queued (undelivered, non-terminal) ids addressed to ``recipient``."""
        out = [
            mid
            for mid, entry in self.store.items()
            if entry["message"].get("recipient_id") == recipient
            and self.tracker.status_of(mid) == "QUEUED"
        ]
        return sorted(out)

    def status_of(self, message_id: str) -> str | None:
        """Tracker status for ``message_id`` (None if unknown)."""
        return self.tracker.status_of(message_id)

    def retry_sweep(self, tick: int) -> int:
        """Count retry-eligible (QUEUED, non-expired) messages.

        They retry naturally on the next pump(); this sweep only counts
        and audits the sweep itself.
        """
        count = 0
        for mid, entry in self.store.items():
            if self.tracker.status_of(mid) != "QUEUED":
                continue
            if int(tick) > int(entry["message"]["expires_at_tick"]):
                continue
            count += 1
        self._audit(tick, "RETRY_SWEEP", "-", f"eligible={count}")
        return count

    # -- reconcile (Step 04: reconnect + reconciliation) -----------------
    @staticmethod
    def _route_sig(route: object) -> tuple[tuple[str, ...], object] | None:
        """Normalize a route record to ``(edge_ids_tuple, next_index)``.

        Accepts dicts ``{edge_ids, next_index}``, (edges, index) pairs,
        or bare edge lists (index defaults to 0). Returns None when the
        record carries no usable route.
        """
        if route is None:
            return None
        if isinstance(route, dict):
            edges = route.get("edge_ids", route.get("route_edge_ids"))
            if edges is None:
                return None
            idx = route.get("next_index", route.get("route_next_index", 0))
            try:
                return (tuple(str(e) for e in edges), int(idx))  # type: ignore[arg-type]
            except TypeError:
                return None
        if isinstance(route, (list, tuple)):
            if len(route) == 2 and isinstance(route[1], int):
                try:
                    return (tuple(str(e) for e in route[0]), int(route[1]))  # type: ignore[arg-type]
                except TypeError:
                    return None
            try:
                return (tuple(str(e) for e in route), 0)  # type: ignore[arg-type]
            except TypeError:
                return None
        return None

    def reconcile(
        self, agent_report: dict, authority: dict, tick: int
    ) -> tuple[str, list[dict], dict]:
        """Compare a reconnecting agent's belief to authoritative state.

        Pure decision helper (Step 04): performs NO sends — it returns
        message-DICTS the caller sends via :meth:`send`. Deterministic:
        same inputs always yield the same outcome code and dicts.

        ``agent_report``: ``{agent_id, belief_version, assignment_id|None,
        assignment_version|None, local_claims: [{assignment_id, version,
        ...}] (default []), route_signature (optional)}``.
        ``authority``: ``{tick, assignments: {aid: {status, version,
        resource_id, incident_id, ...}}, routes: {resource_id: {edge_ids,
        next_index}}, partition_started_tick|None}``.

        Outcome codes exactly: ``IN_SYNC`` | ``STALE_ROUTE`` |
        ``STALE_OWNERSHIP`` | ``CONFLICT``. The detail dict always
        includes ``reconciliation_time_ticks = tick -
        partition_started_tick`` (or 0 when unknown).

        Precedence (deterministic): primary STALE_OWNERSHIP (agent's own
        aid unknown/terminal at authority) -> primary resource-mismatch
        CONFLICT -> local_claims CONFLICT -> STALE_ROUTE (route-signature
        or version mismatch on an active assignment) -> IN_SYNC (quiet,
        no messages). Stale/conflicting state is surfaced explicitly and
        never silently erased; the caller marks REQUIRES_RECONCILIATION
        (via commitment_manager.flag_reconciliation) and notifies.
        """
        tick = int(tick)
        agent_id = str(agent_report.get("agent_id", "?"))
        resource_id = str(agent_report.get("resource_id", agent_id))
        assignment_id = agent_report.get("assignment_id")
        assignment_version = agent_report.get("assignment_version")
        claims = agent_report.get("local_claims", []) or []
        auth_assignments = authority.get("assignments", {}) or {}
        auth_routes = authority.get("routes", {}) or {}
        part_start = authority.get("partition_started_tick")
        ticks_out = int(tick - part_start) if part_start is not None else 0

        def base_detail(**extra: object) -> dict:
            detail: dict = {
                "reconciliation_time_ticks": ticks_out,
                "ticks_out": ticks_out,
            }
            detail.update(extra)
            return detail

        def is_active(rec: dict) -> bool:
            return str(rec.get("status")) in (
                "PROPOSED",
                "COMMITTED",
                "ACKNOWLEDGED",
                "IN_PROGRESS",
            )

        def is_terminal(rec: dict) -> bool:
            return str(rec.get("status")) in (
                "COMPLETED",
                "CANCELLED",
                "REJECTED",
                "EXPIRED",
            )

        # -- primary assignment: STALE_OWNERSHIP -------------------------
        if assignment_id is not None:
            auth_rec = auth_assignments.get(assignment_id)
            if auth_rec is None:
                detail = base_detail(
                    old_assignment_id=assignment_id,
                    authority_status="UNKNOWN",
                    agent_assignment_version=assignment_version,
                )
                self._audit(
                    tick, "RECONCILE", str(assignment_id), "STALE_OWNERSHIP:UNKNOWN"
                )
                return ("STALE_OWNERSHIP", [], detail)
            if is_terminal(auth_rec) or (
                str(auth_rec.get("status")) == "REQUIRES_RECONCILIATION"
            ):
                detail = base_detail(
                    old_assignment_id=assignment_id,
                    authority_status=str(auth_rec.get("status")),
                    authority_version=auth_rec.get("version"),
                    agent_assignment_version=assignment_version,
                )
                self._audit(
                    tick,
                    "RECONCILE",
                    str(assignment_id),
                    f"STALE_OWNERSHIP:{auth_rec.get('status')}",
                )
                return ("STALE_OWNERSHIP", [], detail)
            # -- primary resource-mismatch: authority owns it elsewhere --
            auth_owner = str(auth_rec.get("resource_id", ""))
            if auth_owner and auth_owner != resource_id:
                detail = base_detail(
                    agent_claim={
                        "assignment_id": assignment_id,
                        "version": assignment_version,
                        "resource_id": resource_id,
                    },
                    authority_record={
                        "assignment_id": assignment_id,
                        "status": auth_rec.get("status"),
                        "version": auth_rec.get("version"),
                        "resource_id": auth_rec.get("resource_id"),
                        "incident_id": auth_rec.get("incident_id"),
                    },
                )
                self._audit(
                    tick, "RECONCILE", str(assignment_id), "CONFLICT:OWNER_MISMATCH"
                )
                return ("CONFLICT", [], detail)

        # -- local_claims: double-commit CONFLICT ------------------------
        for claim in claims:
            if not isinstance(claim, dict):
                continue
            claim_aid = claim.get("assignment_id")
            if claim_aid is None:
                continue
            claim_res = str(
                claim.get("resource_id", resource_id)
            )
            auth_rec = auth_assignments.get(claim_aid)
            # (a) claimed aid owned by a different resource/incident.
            if isinstance(auth_rec, dict) and is_active(auth_rec):
                if str(auth_rec.get("resource_id", "")) != claim_res or (
                    claim.get("incident_id") is not None
                    and claim.get("incident_id") != auth_rec.get("incident_id")
                ):
                    detail = base_detail(
                        agent_claim=dict(claim),
                        authority_record={
                            "assignment_id": claim_aid,
                            "status": auth_rec.get("status"),
                            "version": auth_rec.get("version"),
                            "resource_id": auth_rec.get("resource_id"),
                            "incident_id": auth_rec.get("incident_id"),
                        },
                    )
                    self._audit(
                        tick, "RECONCILE", str(claim_aid), "CONFLICT:CLAIM_MISMATCH"
                    )
                    return ("CONFLICT", [], detail)
            # (b) same resource already actively owned by another ASN.
            for other_aid, other_rec in auth_assignments.items():
                if not isinstance(other_rec, dict):
                    continue
                if str(other_aid) == str(claim_aid):
                    continue
                if not is_active(other_rec):
                    continue
                if str(other_rec.get("resource_id", "")) == claim_res:
                    detail = base_detail(
                        agent_claim=dict(claim),
                        authority_record={
                            "assignment_id": other_aid,
                            "status": other_rec.get("status"),
                            "version": other_rec.get("version"),
                            "resource_id": other_rec.get("resource_id"),
                            "incident_id": other_rec.get("incident_id"),
                        },
                    )
                    self._audit(
                        tick, "RECONCILE", str(claim_aid), "CONFLICT:DOUBLE_COMMIT"
                    )
                    return ("CONFLICT", [], detail)

        # -- primary assignment active: STALE_ROUTE? ---------------------
        if assignment_id is not None:
            auth_rec = auth_assignments.get(assignment_id)
            if isinstance(auth_rec, dict) and is_active(auth_rec):
                auth_version = auth_rec.get("version")
                route_stale = False
                agent_sig = self._route_sig(agent_report.get("route_signature"))
                if agent_sig is None:
                    # Alternate spellings the agent may carry.
                    for key in ("route_edge_ids", "belief_route_edge_ids"):
                        if agent_report.get(key) is not None:
                            agent_sig = self._route_sig(
                                {
                                    "edge_ids": agent_report.get(key),
                                    "next_index": agent_report.get(
                                        "route_next_index",
                                        agent_report.get("next_index", 0),
                                    ),
                                }
                            )
                            break
                auth_route = auth_routes.get(
                    str(auth_rec.get("resource_id", resource_id)), {}
                )
                auth_sig = self._route_sig(auth_route)
                if agent_sig is not None and auth_sig is not None:
                    route_stale = agent_sig != auth_sig
                version_stale = (
                    assignment_version is not None
                    and auth_version is not None
                    and int(assignment_version) != int(auth_version)
                )
                if route_stale or version_stale:
                    route_edges = (
                        list(auth_sig[0])
                        if auth_sig is not None
                        else list(auth_route.get("edge_ids", []))
                        if isinstance(auth_route, dict)
                        else []
                    )
                    reoffer = {
                        "message_id": f"MSG-REOFFER-{assignment_id}-t{tick:04d}",
                        "type": "ASSIGNMENT_OFFER",
                        "sender_id": "DISPATCH-01",
                        "recipient_id": agent_id,
                        "created_at_tick": tick,
                        "expires_at_tick": tick + 10,
                        "version": int(auth_version)
                        if auth_version is not None
                        else 1,
                        "payload": {
                            "assignment_id": assignment_id,
                            "incident_id": auth_rec.get("incident_id"),
                            "destination_id": auth_rec.get("incident_id"),
                            "re_offer": True,
                            "route_edge_ids": route_edges,
                        },
                    }
                    detail = base_detail(
                        assignment_id=assignment_id,
                        agent_assignment_version=assignment_version,
                        authority_version=auth_version,
                        route_stale=bool(route_stale),
                        version_stale=bool(version_stale),
                        route_edge_ids=route_edges,
                    )
                    self._audit(
                        tick, "RECONCILE", str(assignment_id), "STALE_ROUTE:RE_OFFER"
                    )
                    return ("STALE_ROUTE", [reoffer], detail)

        # -- else: versions match -> quiet IN_SYNC -----------------------
        detail = base_detail(
            agent_id=agent_id,
            assignment_id=assignment_id,
            agent_assignment_version=assignment_version,
        )
        self._audit(tick, "RECONCILE", str(assignment_id), "IN_SYNC")
        return ("IN_SYNC", [], detail)

    # -- snapshots -----------------------------------------------------
    def to_dict(self) -> dict:
        """JSON-safe snapshot: store, tracker, dedup, queue, audit, network."""
        return {
            "simulation_id": self.simulation_id,
            "sender_ids": sorted(self.sender_ids)
            if self.sender_ids is not None
            else None,
            "store": copy.deepcopy(self.store),
            "tracker": self.tracker.to_dict(),
            "dedup": self.dedup.to_dict(),
            "queue": self.queue.to_dict(),
            "audit": [dict(a) for a in self.audit],
            "_seq": self._seq,
            "delayed_audited": sorted(self._delayed_audited),
            "network": self.network.to_dict(),  # type: ignore[union-attr]
        }

    @classmethod
    def from_dict(cls, data: dict, network: object) -> "Gateway":
        """Restore a snapshot from :meth:`to_dict`.

        ``network`` must be the live adapter (e.g.
        ``SimulatedNetwork.from_dict(data["network"])``).
        """
        sender_ids = data.get("sender_ids")
        obj = cls(
            network,
            simulation_id=str(data.get("simulation_id", "SIM-001")),
            sender_ids=set(sender_ids) if sender_ids is not None else None,
        )
        obj.store = copy.deepcopy(data.get("store", {}))
        obj.tracker = DeliveryTracker.from_dict(data.get("tracker", {}))
        obj.dedup = Deduplicator.from_dict(data.get("dedup", {}))
        obj.queue = MessageQueue.from_dict(data.get("queue", {}))
        obj.audit = [dict(a) for a in data.get("audit", [])]
        obj._seq = int(data.get("_seq", 0))
        obj._delayed_audited = set(str(x) for x in data.get("delayed_audited", []))
        return obj
