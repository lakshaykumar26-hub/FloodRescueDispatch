"""Report agent: submits observations as independently stored claims.

Reports are stored independently and start ``UNVERIFIED``; conflict
detection / resolution arrives in Phase 4 — this stub only mints
well-shaped claims with a per-source sequence.
"""

from .base_agent import BaseAgent


class ReportAgent(BaseAgent):
    """Submits and tracks potentially conflicting reports."""

    kind = "report"

    def __init__(self, agent_id: str) -> None:
        super().__init__(agent_id)
        self._seq = 0

    def submit_claim(
        self,
        subject_id: str,
        claim: str,
        tick: int,
        confidence: float = 1.0,
        verification: str = "UNVERIFIED",
    ) -> dict:
        """Mint a claim dict with this agent's next sequence number.

        ``report_id`` is ``f"RPT-{source}-{seq:04d}"`` with ``seq`` starting
        at 1. ``observed_at_tick == received_at_tick == tick`` (the agent
        reports what it saw now); ``verification_status`` starts
        ``UNVERIFIED`` unless ``verification`` says otherwise.
        """
        self._seq += 1
        report = {
            "report_id": f"RPT-{self.id}-{self._seq:04d}",
            "subject_id": subject_id,
            "claim": claim,
            "source": self.id,
            "observed_at_tick": tick,
            "received_at_tick": tick,
            "confidence": confidence,
            "verification_status": verification,
        }
        self.audit.append(
            {
                "event": "CLAIM_SUBMITTED",
                "tick": tick,
                "actor": self.id,
                "report_id": report["report_id"],
                "reason": "OK",
            }
        )
        return report

    def submit_verified_open(self, subject_id: str, tick: int) -> dict:
        """Mint an authority CONFIRMED OPEN claim (e.g. HQ / field-verified).

        ``claim="OPEN"``, ``confidence=1.0``,
        ``verification_status="CONFIRMED"``. Only a CONFIRMED OPEN newer
        than the newest above-threshold CLOSED claim reopens a disputed
        edge (see ``dispatch/report_store.py``); UNVERIFIED OPEN claims
        never do, no matter how recent.
        """
        return self.submit_claim(
            subject_id, "OPEN", tick, confidence=1.0, verification="CONFIRMED"
        )
