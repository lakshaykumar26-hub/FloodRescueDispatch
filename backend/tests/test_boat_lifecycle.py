"""Phase 1 Step 05: resource lifecycles (see docs/phase-1.../step-05)."""

from backend.app.simulation.state_manager import StateManager
from backend.app.simulation.world import Boat, GroundTeam, Shelter, World


def _manager(**overrides) -> StateManager:
    boats = overrides.get(
        "boats",
        {"BOAT-01": Boat(boat_id="BOAT-01", node_id="N-01",
                         capacity=6, fuel=50.0, fuel_reserve=10.0)},
    )
    teams = overrides.get(
        "teams",
        {"TEAM-01": GroundTeam(team_id="TEAM-01", node_id="N-01",
                              capabilities=["medical"])},
    )
    shelters = overrides.get("shelters", {})
    world = World(boats=boats, teams=teams, shelters=shelters)
    return StateManager(world)


def test_happy_path_boat_full_cycle() -> None:
    sm = _manager()
    path = ["ASSIGNED", "EN_ROUTE_TO_INCIDENT", "RESCUING",
            "TRANSPORTING_TO_SHELTER", "RECOVERY", "AVAILABLE"]
    tick = 1
    for to in path:
        ok, code = sm.transition_boat("BOAT-01", to, reason=f"go {to}",
                                      tick=tick, actor="engine")
        assert ok is True
        assert code == "OK"
        tick += 1
    assert sm.world.boats["BOAT-01"].status == "AVAILABLE"
    assert len(sm.world.boats["BOAT-01"].history) == len(path)


def test_illegal_jump_rejected() -> None:
    sm = _manager()
    ok, code = sm.transition_boat("BOAT-01", "TRANSPORTING_TO_SHELTER",
                                 reason="skip ahead", tick=5)
    assert ok is False
    assert code == "REJECTED:ILLEGAL_TRANSITION"
    assert sm.world.boats["BOAT-01"].status == "AVAILABLE"


def test_failed_with_passengers_keeps_them() -> None:
    sm = _manager()
    ok, _ = sm.board_boat("BOAT-01", 4, tick=1, actor="engine")
    assert ok is True
    ok, code = sm.transition_boat("BOAT-01", "ASSIGNED", reason="dispatch",
                                 tick=2)
    assert ok is True
    ok, code = sm.transition_boat("BOAT-01", "FAILED", reason="engine fault",
                                 tick=3)
    assert ok is True
    boat = sm.world.boats["BOAT-01"]
    assert boat.status == "FAILED"
    assert boat.needs_recovery is True
    assert boat.passengers == 4


def test_over_capacity_boarding_rejected() -> None:
    sm = _manager()  # capacity 6
    ok, code = sm.board_boat("BOAT-01", 7, tick=1, actor="engine")
    assert ok is False
    assert code == "REJECTED:OVER_CAPACITY"
    assert sm.world.boats["BOAT-01"].passengers == 0


def test_shelter_concurrent_reserve_exactly_one() -> None:
    # NOTE: step-05 text says "9/10 + two reserve(2) -> exactly one succeeds",
    # but 9+2=11 > 10, so BOTH must fail under the hard invariant
    # occupancy+reservations+seats <= capacity. The intent (one winner for the
    # last seats) is preserved with 8/10 + two reserve(2): first fits
    # (8+2=10), second would overbook (8+2+2=11).
    shelter = Shelter(shelter_id="SH-01", node_id="N-09",
                      capacity=10, occupancy=8)
    first = shelter.reserve("ASN-1", 2, tick=1)
    second = shelter.reserve("ASN-2", 2, tick=1)
    assert (first, second) == (True, False)
    assert shelter.occupancy + sum(shelter.reservations.values()) <= shelter.capacity
    # And the literal 9/10 + reserve(2) case correctly refuses (no overbook).
    full = Shelter(shelter_id="SH-02", node_id="N-09",
                   capacity=10, occupancy=9)
    assert full.reserve("ASN-1", 2, tick=1) is False
    assert full.reserve("ASN-2", 2, tick=1) is False


def test_low_fuel_departure_refused() -> None:
    sm = _manager(boats={
        "BOAT-01": Boat(boat_id="BOAT-01", node_id="N-01", capacity=6,
                        fuel=5.0, fuel_reserve=10.0),
    })
    ok, code = sm.can_depart("BOAT-01", route_eta=10)
    assert ok is False
    assert code == "FUEL_INSUFFICIENT"
    assert sm.world.boats["BOAT-01"].fuel == 5.0
    # Feasible case returns OK and also leaves fuel untouched.
    sm2 = _manager()
    ok, code = sm2.can_depart("BOAT-01", route_eta=10)
    assert (ok, code) == (True, "OK")
    assert sm2.world.boats["BOAT-01"].fuel == 50.0


def test_failed_boat_refuses_assigned() -> None:
    sm = _manager()
    ok, _ = sm.transition_boat("BOAT-01", "FAILED", reason="broke", tick=1)
    assert ok is True
    ok, code = sm.transition_boat("BOAT-01", "ASSIGNED", reason="dispatch",
                                 tick=2)
    assert ok is False
    assert code == "REJECTED:RESOURCE_UNAVAILABLE"
    assert sm.world.boats["BOAT-01"].status == "FAILED"


def test_blocked_states_refuse_assigned() -> None:
    for blocked in ("UNAVAILABLE", "MAINTENANCE", "STRANDED"):
        sm = _manager()
        # Reach the blocked state first (all reachable from AVAILABLE).
        ok, _ = sm.transition_boat("BOAT-01", blocked, reason="setup", tick=1)
        assert ok is True
        ok, code = sm.transition_boat("BOAT-01", "ASSIGNED",
                                     reason="dispatch", tick=2)
        assert ok is False
        assert code == "REJECTED:RESOURCE_UNAVAILABLE"


def test_team_happy_path_and_illegal() -> None:
    sm = _manager()
    for i, to in enumerate(["ASSIGNED", "ON_SCENE", "RETURNING", "AVAILABLE"],
                           start=1):
        ok, code = sm.transition_team("TEAM-01", to, reason=f"go {to}",
                                     tick=i)
        assert (ok, code) == (True, "OK")
    assert sm.world.teams["TEAM-01"].status == "AVAILABLE"

    sm2 = _manager()
    ok, code = sm2.transition_team("TEAM-01", "RETURNING", reason="skip",
                                  tick=1)
    assert ok is False
    assert code == "REJECTED:ILLEGAL_TRANSITION"


def test_history_entries_have_tick_and_reason() -> None:
    sm = _manager()
    sm.transition_boat("BOAT-01", "ASSIGNED", reason="dispatch", tick=1)
    sm.transition_boat("BOAT-01", "EN_ROUTE_TO_INCIDENT", reason="depart",
                       tick=2)
    sm.transition_boat("BOAT-01", "RESCUING", reason="arrived", tick=3)
    history = sm.world.boats["BOAT-01"].history
    assert len(history) == 3
    for entry in history:
        assert "tick" in entry and "reason" in entry
        assert isinstance(entry["tick"], int)
        assert entry["reason"]
    # Refusals are logged too, with no state change.
    n_events = len(sm.event_log)
    ok, _ = sm.transition_boat("BOAT-01", "AVAILABLE", reason="bad jump",
                               tick=4)
    assert ok is False
    assert len(sm.world.boats["BOAT-01"].history) == 4
    assert len(sm.event_log) == n_events + 1


def test_shelter_unknown_assignment_guarded() -> None:
    shelter = Shelter(shelter_id="SH-01", node_id="N", capacity=10)
    assert shelter.checkin("ASN-NOPE", tick=1) == 0
    assert shelter.release("ASN-NOPE", tick=2) == 0
    assert shelter.occupancy == 0
    assert shelter.occupancy + sum(shelter.reservations.values()) >= 0
    # Failure reasons are logged.
    assert shelter.history[-1]["reason"].startswith("REJECTED:")
