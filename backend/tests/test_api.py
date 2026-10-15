"""Phase 6 Step 01: REST API over the engine (TestClient).

Covers: create->start->step×5->tick 5; inject closure lands in events;
assignments non-empty on baseline; bad inject (unknown edge) -> 422 with
reason and tick unchanged; pause->step works; start->step ordering (409).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", str(tmp_path / "api_test.db"))
    from backend.app.api import store
    from backend.app.main import create_app
    from backend.app.persistence import database as _database

    store.clear_entries()
    _database.reset_shared()
    yield TestClient(create_app())
    store.clear_entries()
    _database.reset_shared()


def _make_started(client: TestClient, strategy: str = "centralized") -> str:
    resp = client.post(
        "/api/simulations",
        json={"scenario_name": "baseline", "strategy": strategy},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["seed"] == 42
    assert body["tick"] == 0
    assert body["status"] == "created"
    sim_id = body["simulation_id"]
    start = client.post(f"/api/simulations/{sim_id}/start")
    assert start.status_code == 200, start.text
    assert start.json()["status"] == "running"
    return sim_id


def test_create_start_step_five_state_tick_five(client: TestClient) -> None:
    sim_id = _make_started(client)
    step = client.post(f"/api/simulations/{sim_id}/step", json={"steps": 5})
    assert step.status_code == 200, step.text
    assert step.json()["tick"] == 5
    state = client.get(f"/api/simulations/{sim_id}/state")
    assert state.status_code == 200, state.text
    body = state.json()
    assert body["tick"] == 5
    assert body["status"] == "running"
    assert body["world"]["tick"] == 5
    assert "INC-01" in body["world"]["incidents"]


def test_inject_closure_lands_in_events(client: TestClient) -> None:
    sim_id = _make_started(client)
    client.post(f"/api/simulations/{sim_id}/step", json={"steps": 5})
    inject = client.post(
        f"/api/simulations/{sim_id}/events",
        json={"kind": "CLOSURE", "payload": {"edge_id": "R-11"}},
    )
    assert inject.status_code == 200, inject.text
    client.post(f"/api/simulations/{sim_id}/step", json={"steps": 1})
    events = client.get(f"/api/simulations/{sim_id}/events")
    assert events.status_code == 200, events.text
    assert any(
        e["kind"] == "CLOSURE" and e["detail"].get("edge_id") == "R-11"
        for e in events.json()["events"]
    )


def test_assignments_non_empty_on_baseline(client: TestClient) -> None:
    sim_id = _make_started(client)
    client.post(f"/api/simulations/{sim_id}/step", json={"steps": 5})
    resp = client.get(f"/api/simulations/{sim_id}/assignments")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["assignments"]) > 0
    assert any(e["kind"] == "COMMITTED" for e in body["history"])
    first = body["assignments"][0]
    assert {"assignment_id", "version", "status", "history"} <= set(first)


def test_bad_inject_unknown_edge_422_tick_unchanged(client: TestClient) -> None:
    sim_id = _make_started(client)
    client.post(f"/api/simulations/{sim_id}/step", json={"steps": 5})
    before = client.get(f"/api/simulations/{sim_id}/state").json()["tick"]
    bad = client.post(
        f"/api/simulations/{sim_id}/events",
        json={"kind": "CLOSURE", "payload": {"edge_id": "R-99"}},
    )
    assert bad.status_code == 422, bad.text
    assert bad.json()["reason"] == "UNKNOWN_EDGE"
    after = client.get(f"/api/simulations/{sim_id}/state").json()["tick"]
    assert after == before


def test_pause_then_step_still_works(client: TestClient) -> None:
    sim_id = _make_started(client)
    client.post(f"/api/simulations/{sim_id}/step", json={"steps": 5})
    paused = client.post(f"/api/simulations/{sim_id}/pause")
    assert paused.status_code == 200, paused.text
    assert paused.json()["status"] == "paused"
    step = client.post(f"/api/simulations/{sim_id}/step", json={"steps": 1})
    assert step.status_code == 200, step.text
    assert step.json()["tick"] == 6
    assert step.json()["status"] == "paused"


def test_step_before_start_is_409(client: TestClient) -> None:
    resp = client.post("/api/simulations", json={"scenario_name": "baseline"})
    sim_id = resp.json()["simulation_id"]
    step = client.post(f"/api/simulations/{sim_id}/step", json={"steps": 1})
    assert step.status_code == 409, step.text
    assert step.json()["reason"] == "NOT_STARTED"


def test_metrics_and_comms_endpoints(client: TestClient) -> None:
    sim_id = _make_started(client)
    client.post(f"/api/simulations/{sim_id}/step", json={"steps": 5})
    metrics = client.get(f"/api/simulations/{sim_id}/metrics")
    assert metrics.status_code == 200, metrics.text
    body = metrics.json()
    assert body["tick"] == 5
    assert body["served"] + body["unserved"] == len(
        client.get(f"/api/simulations/{sim_id}/incidents").json()["incidents"]
    )
    assert body["committed"] > 0
    comms = client.get(f"/api/simulations/{sim_id}/communications")
    assert comms.status_code == 200, comms.text
    comms_body = comms.json()
    assert comms_body["total_messages"] > 0
    assert "BOAT-01" in comms_body["belief_ticks"]


def test_replay_endpoint_matches_live_summary(client: TestClient) -> None:
    sim_id = _make_started(client)
    client.post(
        f"/api/simulations/{sim_id}/events",
        json={"kind": "CLOSURE", "payload": {"edge_id": "R-11"}},
    )
    client.post(f"/api/simulations/{sim_id}/step", json={"steps": 12})
    live = client.get(f"/api/simulations/{sim_id}/metrics").json()
    replay = client.post(f"/api/simulations/{sim_id}/replay", json={})
    assert replay.status_code == 200, replay.text
    summary = replay.json()["summary"]
    assert replay.json()["tick"] == 12
    assert summary["served"] == live["served"]
    assert summary["committed"] == live["committed"]


def test_create_accepts_string_scenario_as_name_alias(client: TestClient) -> None:
    """Regression: older dashboards sent the file name in `scenario` (string).

    That must coerce to ``scenario_name`` instead of 422ing the request.
    """
    resp = client.post(
        "/api/simulations",
        json={"scenario": "baseline", "strategy": "centralized"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["scenario_name"] == "baseline"


def test_create_accepts_inline_scenario_dict(client: TestClient) -> None:
    inline = {
        "scenario_name": "tiny",
        "random_seed": 7,
        "ticks": 5,
        "nodes": [{"node_id": "N-01", "neighborhood": "R", "kind": "station", "x": 0.0, "y": 0.0}],
        "edges": [],
        "incidents": [],
        "boats": [],
        "teams": [],
        "shelters": [],
        "events": [],
    }
    resp = client.post(
        "/api/simulations",
        json={"scenario": inline, "strategy": "centralized"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["scenario_name"] == "tiny"
    assert resp.json()["seed"] == 7
