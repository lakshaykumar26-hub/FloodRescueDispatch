"""Append-only store for contradictory edge reports (Phase 4 Step 04; spec section 9).

Confidence is evidence, not truth: a high-confidence CLOSED claim does NOT
close the edge outright and the latest observation is NOT auto-truth. Claims
are never overwritten -- every report is appended and the edge belief is
derived deterministically from the full claim history:

- any CLOSED claim with ``confidence >= threshold`` (default 0.5) and no
  newer CONFIRMED OPEN  -> edge ``disputed`` (conservative: new commits
  must avoid it, existing in-flight movement still traverses with warning).
- a CONFIRMED OPEN newer (``received_at_tick``) than the newest
  above-threshold CLOSED -> edge ``open`` again.
- only sub-threshold CLOSED claims -> edge stays ``open`` but a
  ``REPORT_WARNING`` is logged (weak evidence, not ignored silently).
- no claims at all -> ``open``.

Ordering uses integer ``received_at_tick`` only (deterministic); wall-clock
timestamps are never consulted. No FastAPI/DB imports (AGENTS.md hard rule).
"""

from __future__ import annotations

from typing import Any

_CLAIM_KEYS: tuple[str, ...] = (
    "report_id",
    "subject_id",
    "claim",
    "source",
    "observed_at_tick",
    "received_at_tick",
    "confidence",
    "verification_status",
)

_CLAIM_VALUES: frozenset[str] = frozenset({"OPEN", "CLOSED"})
_VERIFICATION_VALUES: frozenset[str] = frozenset(
    {"UNVERIFIED", "CONFIRMED", "SUPERSEDED"}
)


def _pick_latest(claims: list[dict]) -> dict:
    """Deterministic representative: newest, then most confident, then id."""
    return sorted(
        claims,
        key=lambda c: (c["received_at_tick"], c["confidence"], c["report_id"]),
    )[-1]


def _fmt(claim: dict) -> str:
    return (
        f"{claim['report_id']} {claim['claim']} conf {claim['confidence']} "
        f"({claim['source']}@t{claim['observed_at_tick']})"
    )


class ReportStore:
    """In-memory append-only claim log with derived edge beliefs."""

    def __init__(self, threshold: float = 0.5) -> None:
        self.threshold = threshold
        self.claims: list[dict] = []

    def add_claim(self, claim: dict) -> dict:
        """Validate ``claim``, append a copy, and return the stored copy.

        Raises ``ValueError`` on missing keys, a ``claim`` outside
        ``OPEN|CLOSED``, or an unknown ``verification_status``. Never
        mutates or drops an existing entry.
        """
        missing = [k for k in _CLAIM_KEYS if k not in claim]
        if missing:
            raise ValueError(f"claim missing keys: {missing}")
        if claim["claim"] not in _CLAIM_VALUES:
            raise ValueError(f"invalid claim: {claim['claim']!r}")
        if claim["verification_status"] not in _VERIFICATION_VALUES:
            raise ValueError(
                f"invalid verification_status: {claim['verification_status']!r}"
            )
        stored = {k: claim[k] for k in _CLAIM_KEYS}
        self.claims.append(stored)
        return dict(stored)

    def claims_for(self, edge_id: str) -> list[dict]:
        """Copies of every claim filed against ``edge_id``, in filing order."""
        return [dict(c) for c in self.claims if c["subject_id"] == edge_id]

    def edge_belief(self, edge_id: str) -> tuple[str, str]:
        """Derive ``(status, explanation)`` for ``edge_id`` from all claims.

        ``status`` is ``"disputed"`` or ``"open"`` (never ``"closed"``:
        hard closures belong to scheduler events, not reports).
        """
        relevant = [c for c in self.claims if c["subject_id"] == edge_id]
        closed = [c for c in relevant if c["claim"] == "CLOSED"]
        opens = [c for c in relevant if c["claim"] == "OPEN"]
        above = [c for c in closed if c["confidence"] >= self.threshold]
        confirmed = [
            c for c in opens if c.get("verification_status") == "CONFIRMED"
        ]
        newest_closed_tick = (
            max(c["received_at_tick"] for c in above) if above else None
        )
        newer_confirmed = [
            c
            for c in confirmed
            if newest_closed_tick is None
            or c["received_at_tick"] > newest_closed_tick
        ]
        if above and not newer_confirmed:
            closed_rep = _pick_latest(above)
            if opens:
                open_rep = _pick_latest(opens)
                explanation = (
                    f"restricted {edge_id}: {_fmt(closed_rep)} "
                    f"vs {_fmt(open_rep)} → conservative CLOSED"
                )
            else:
                explanation = (
                    f"restricted {edge_id}: {_fmt(closed_rep)} "
                    f"→ conservative CLOSED"
                )
            return ("disputed", explanation)
        if above and newer_confirmed:
            open_rep = _pick_latest(newer_confirmed)
            closed_rep = _pick_latest(above)
            explanation = (
                f"reopened {edge_id}: {_fmt(open_rep)} CONFIRMED "
                f"supersedes {closed_rep['report_id']} CLOSED → OPEN"
            )
            return ("open", explanation)
        if closed:
            weak_rep = _pick_latest(closed)
            explanation = (
                f"open {edge_id}: only weak CLOSED evidence "
                f"({weak_rep['report_id']} conf {weak_rep['confidence']} "
                f"below threshold {self.threshold}) → stays OPEN"
            )
            return ("open", explanation)
        return ("open", "no claims")

    def ingest_report(
        self, manager: Any, claim: dict, tick: int, actor: str = "reporter"
    ) -> tuple[str, str]:
        """File ``claim`` and apply the derived belief to the manager's world.

        ``manager`` is any object exposing ``world`` (edge dict) and
        ``_log(tick, kind, actor, detail)`` (e.g. ``StateManager``; not
        imported or modified here). Transitions only run between ``open``
        and ``disputed`` -- a hard-``closed`` edge is never touched by
        reports. Unknown edges log ``IGNORED`` and never raise. Returns the
        ``edge_belief`` ``(status, explanation)`` tuple.
        """
        stored = self.add_claim(claim)
        edge_id = stored["subject_id"]
        world = getattr(manager, "world", None)
        edge = None
        if world is not None:
            edges = getattr(world, "edges", {})
            edge = edges.get(edge_id) if isinstance(edges, dict) else None
        if edge is None:
            manager._log(
                tick,
                "IGNORED",
                actor,
                {
                    "reason": "unknown_edge",
                    "edge_id": edge_id,
                    "report_id": stored["report_id"],
                },
            )
            return self.edge_belief(edge_id)
        status, explanation = self.edge_belief(edge_id)
        report_ids = [
            c["report_id"] for c in self.claims if c["subject_id"] == edge_id
        ]
        if status == "disputed":
            if edge.status == "closed":
                manager._log(
                    tick,
                    "REPORT_WARNING",
                    actor,
                    {
                        "edge_id": edge_id,
                        "report_ids": report_ids,
                        "explanation": explanation,
                        "reason": "closure_stands",
                    },
                )
            else:
                edge.status = "disputed"
                edge.last_updated_tick = tick
                manager._log(
                    tick,
                    "EDGE_DISPUTED",
                    actor,
                    {
                        "edge_id": edge_id,
                        "report_ids": report_ids,
                        "explanation": explanation,
                    },
                )
        else:
            relevant = [c for c in self.claims if c["subject_id"] == edge_id]
            above = [
                c
                for c in relevant
                if c["claim"] == "CLOSED"
                and c["confidence"] >= self.threshold
            ]
            if edge.status == "disputed" and above:
                edge.status = "open"
                edge.last_updated_tick = tick
                manager._log(
                    tick,
                    "EDGE_REOPENED",
                    actor,
                    {
                        "edge_id": edge_id,
                        "report_ids": report_ids,
                        "reason": "CONFIRMED_OPEN",
                        "explanation": explanation,
                    },
                )
            elif not above and any(
                c["claim"] == "CLOSED" for c in relevant
            ):
                manager._log(
                    tick,
                    "REPORT_WARNING",
                    actor,
                    {
                        "edge_id": edge_id,
                        "report_ids": report_ids,
                        "explanation": explanation,
                        "reason": "weak_evidence",
                    },
                )
        return (status, explanation)

    def to_dict(self) -> dict:
        """Snapshot the store (threshold + full append-only history)."""
        return {
            "threshold": self.threshold,
            "claims": [dict(c) for c in self.claims],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ReportStore":
        """Restore a store from :meth:`to_dict` output, preserving order."""
        store = cls(threshold=data.get("threshold", 0.5))
        for claim in data.get("claims", []):
            store.add_claim(claim)
        return store


__all__ = ["ReportStore"]
