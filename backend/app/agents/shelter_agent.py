"""Shelter agent: owns location, occupancy, and reservations.

``reserve_bid`` is a pure feasibility check against the shelter's own books
(no mutation); ``apply_hold`` / ``release_hold`` mutate holds for later
phases (commit / cancel paths).
"""

from .base_agent import BaseAgent


class ShelterAgent(BaseAgent):
    """Accepts or rejects incoming arrivals from its own books."""

    kind = "shelter"

    def __init__(
        self,
        shelter_id: str,
        node_id: str,
        capacity: int,
        occupancy: int = 0,
    ) -> None:
        super().__init__(shelter_id)
        self.node_id = node_id
        self.capacity = capacity
        self.occupancy = occupancy
        self.reserved: dict = {}

    def _remaining(self) -> int:
        return self.capacity - self.occupancy - sum(self.reserved.values())

    def reserve_bid(self, people: int) -> tuple:
        """Check whether ``people`` seats fit the shelter's own books.

        Returns ``(accept, remaining_after, reason)`` without mutating any
        hold: ``(True, remaining - people, "OK")`` when ``people`` fits,
        else ``(False, remaining, "SHELTER_FULL")``.
        """
        remaining = self._remaining()
        if people <= remaining:
            return (True, remaining - people, "OK")
        self.audit.append(
            {
                "event": "RESERVE_REJECTED",
                "actor": self.id,
                "people": people,
                "remaining": remaining,
                "reason": "SHELTER_FULL",
            }
        )
        return (False, remaining, "SHELTER_FULL")

    def apply_hold(self, ref: str, seats: int) -> bool:
        """Hold ``seats`` under ``ref`` unless it would overbook.

        Returns True on success (audited ``HOLD_APPLIED``); False with no
        mutation when ``seats <= 0`` (``INVALID_SEATS``) or the hold would
        exceed capacity (``SHELTER_FULL``).
        """
        if seats <= 0:
            self.audit.append(
                {
                    "event": "HOLD_REJECTED",
                    "actor": self.id,
                    "ref": ref,
                    "seats": seats,
                    "reason": "INVALID_SEATS",
                }
            )
            return False
        if self.occupancy + sum(self.reserved.values()) + seats > self.capacity:
            self.audit.append(
                {
                    "event": "HOLD_REJECTED",
                    "actor": self.id,
                    "ref": ref,
                    "seats": seats,
                    "reason": "SHELTER_FULL",
                }
            )
            return False
        self.reserved[ref] = self.reserved.get(ref, 0) + seats
        self.audit.append(
            {
                "event": "HOLD_APPLIED",
                "actor": self.id,
                "ref": ref,
                "seats": seats,
                "reason": "OK",
            }
        )
        return True

    def release_hold(self, ref: str) -> int:
        """Drop the hold under ``ref``. Returns seats released (0 if unknown)."""
        seats = self.reserved.pop(ref, 0)
        self.audit.append(
            {
                "event": "HOLD_RELEASED" if seats else "HOLD_RELEASE_FAILED",
                "actor": self.id,
                "ref": ref,
                "seats": seats,
                "reason": "OK" if seats else "UNKNOWN_REF",
            }
        )
        return seats
