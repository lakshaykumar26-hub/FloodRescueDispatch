"""Resource API schemas (thin wrappers over simulation world models)."""

from ..simulation.world import Boat, GroundTeam, Shelter


class BoatRead(Boat):
    pass


class GroundTeamRead(GroundTeam):
    pass


class ShelterRead(Shelter):
    pass
