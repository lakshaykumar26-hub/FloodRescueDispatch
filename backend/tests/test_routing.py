"""Phase 1 Step 03: graph + routing (see docs/phase-1.../step-03-graph-routing.md)."""

import json
from pathlib import Path

from backend.app.routing.graph import build_graph
from backend.app.routing.pathfinder import find_route
from backend.app.routing.route_validator import is_route_valid
from backend.app.simulation.world import Edge, Node, World


def _node(node_id: str, x: float = 0.0, y: float = 0.0) -> Node:
    return Node(
        node_id=node_id, neighborhood="Test", kind="intersection", x=x, y=y
    )


def _edge(
    edge_id: str,
    frm: str,
    to: str,
    mode: str,
    travel_time: int,
    status: str = "open",
    risk: float = 0.1,
    capacity: int = 2,
) -> Edge:
    return Edge(
        edge_id=edge_id,
        from_node=frm,
        to_node=to,
        mode=mode,  # type: ignore[arg-type]
        travel_time=travel_time,
        status=status,  # type: ignore[arg-type]
        risk_level=risk,
        capacity=capacity,
    )


def _road_triangle() -> World:
    """A/B/C road graph: A->B->C costs 5+5=10, direct A->C costs 12."""
    return World(
        nodes={"A": _node("A", 0, 0), "B": _node("B", 1, 0), "C": _node("C", 2, 0)},
        edges={
            "R-AB": _edge("R-AB", "A", "B", "road", 5, risk=0.1),
            "R-BC": _edge("R-BC", "B", "C", "road", 5, risk=0.2),
            "R-AC": _edge("R-AC", "A", "C", "road", 12, risk=0.1),
        },
    )


def _mixed_road_water() -> World:
    """Parallel road and water corridors between A/B/C."""
    return World(
        nodes={"A": _node("A", 0, 0), "B": _node("B", 1, 0), "C": _node("C", 2, 0)},
        edges={
            "R-AB": _edge("R-AB", "A", "B", "road", 5),
            "R-BC": _edge("R-BC", "B", "C", "road", 5),
            "W-AB": _edge("W-AB", "A", "B", "water", 4, capacity=1),
            "W-BC": _edge("W-BC", "B", "C", "water", 4, capacity=1),
        },
    )


def test_open_graph_prefers_via_b_over_direct() -> None:
    world = _road_triangle()
    route = find_route(world, "A", "C", "road")
    assert route is not None
    assert route["nodes"] == ["A", "B", "C"]
    assert route["edges"] == ["R-AB", "R-BC"]
    assert route["eta_ticks"] == 10


def test_closing_bc_reroutes_via_direct() -> None:
    world = _road_triangle()
    before = find_route(world, "A", "C", "road")
    assert before is not None and before["edges"] == ["R-AB", "R-BC"]

    world.edges["R-BC"].status = "closed"
    # Old edge list is now invalid with an explicit reason.
    valid, reason = is_route_valid(world, ["R-AB", "R-BC"], "road")
    assert (valid, reason) == (False, "EDGE_CLOSED:R-BC")

    after = find_route(world, "A", "C", "road")
    assert after is not None
    assert after["edges"] == ["R-AC"]
    assert after["nodes"] == ["A", "C"]
    assert after["edges"] != before["edges"]  # path changed
    assert after["eta_ticks"] == 12


def test_boat_requesting_road_only_path_is_mode_mismatch() -> None:
    world = _road_triangle()
    valid, reason = is_route_valid(world, ["R-AB", "R-BC"], "water")
    assert valid is False
    assert reason == "MODE_MISMATCH"


def test_water_closure_blocks_boat_but_not_ground_team() -> None:
    world = _mixed_road_water()
    world.edges["W-BC"].status = "closed"

    boat_route = find_route(world, "A", "C", "water")
    assert boat_route is None  # NO_ROUTE for the boat

    team_route = find_route(world, "A", "C", "road")
    assert team_route is not None
    assert team_route["nodes"] == ["A", "B", "C"]
    assert team_route["edges"] == ["R-AB", "R-BC"]


def test_eta_ticks_equals_travel_time_sum() -> None:
    world = _mixed_road_water()
    for mode in ("road", "water"):
        route = find_route(world, "A", "C", mode)
        assert route is not None
        expected = sum(world.edges[eid].travel_time for eid in route["edges"])
        assert route["eta_ticks"] == expected


def test_build_graph_excludes_closed_and_is_bidirectional() -> None:
    world = _road_triangle()
    world.edges["R-BC"].status = "closed"
    graph = build_graph(world, "road")
    assert graph.has_edge("A", "B") and graph.has_edge("B", "A")
    assert graph.has_edge("A", "C") and graph.has_edge("C", "A")
    assert not graph.has_edge("B", "C") and not graph.has_edge("C", "B")
    assert graph["A"]["B"]["weight"] == 5
    assert graph["A"]["B"]["edge_id"] == "R-AB"


def test_disputed_edge_reports_warning_and_max_risk() -> None:
    world = _mixed_road_water()
    world.edges["W-BC"].status = "disputed"
    world.edges["W-AB"].risk_level = 0.125
    world.edges["W-BC"].risk_level = 0.625
    route = find_route(world, "A", "C", "water")
    assert route is not None
    assert route["warnings"] == ["DISPUTED:W-BC"]
    assert route["risk"] == 0.625


def test_unknown_node_returns_none_and_validator_names_unknown_edge() -> None:
    world = _road_triangle()
    assert find_route(world, "A", "ZZZ", "road") is None
    assert find_route(world, "ZZZ", "A", "road") is None
    valid, reason = is_route_valid(world, ["R-AB", "NOPE-1"], "road")
    assert (valid, reason) == (False, "UNKNOWN_EDGE:NOPE-1")


def test_mini_graph_fixture_loads_and_routes() -> None:
    path = Path(__file__).resolve().parent.parent.parent / "scenarios" / "mini_graph.json"
    world = World.model_validate(json.loads(path.read_text()))
    road = find_route(world, "A", "C", "road")
    assert road is not None
    assert road["edges"] == ["R-AB", "R-BC"]
    assert road["eta_ticks"] == 10
    water = find_route(world, "A", "C", "water")
    assert water is not None
    assert water["eta_ticks"] == sum(
        world.edges[eid].travel_time for eid in water["edges"]
    )
