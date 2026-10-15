"""Headless CLI runner: load a scenario JSON, run the engine, print a summary.

Usage:
    python -m backend.app.simulation.run --scenario scenarios/baseline.json
        [--ticks N] [--seed S]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.app.dispatch.centralized_scheduler import CentralizedScheduler
from backend.app.dispatch.negotiation_scheduler import NegotiationScheduler
from backend.app.dispatch.scheduler_interface import Weights
from backend.app.simulation.engine import Simulation
from backend.app.simulation.world import (
    Boat,
    Edge,
    GroundTeam,
    Incident,
    Node,
    Shelter,
    World,
)


def load_scenario(path: str | Path) -> dict:
    """Read and return the raw scenario JSON document."""
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _as_list(value: object) -> list:
    """Normalize a scenario collection to a list.

    Runnable scenarios store ``nodes``/``edges``/... as lists, but the
    routing fixture ``mini_graph.json`` stores ``nodes``/``edges`` as
    dicts keyed by id (it is validated directly via
    ``World.model_validate`` in ``test_routing``). Accept both so the
    headless runner and the API return a clear empty world instead of
    ``TypeError: string indices must be integers``.
    """
    if value is None:
        return []
    if isinstance(value, dict):
        return list(value.values())
    if isinstance(value, list):
        return value
    raise ValueError(f"expected list or dict for scenario collection, got {type(value).__name__}")


def _coerce_int(value: object, field: str) -> int:
    """Coerce a scenario tick/seed field to int, raising ValueError on garbage.

    ``create_entry`` maps only ``ValueError`` to 422 ``BAD_SCENARIO``;
    a bare ``int(None)`` (``TypeError``) or missing dict key
    (``KeyError``) would escape as a 500, so every coercion here goes
    through this helper.
    """
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"bad scenario field {field!r}: {value!r}") from exc


def _scenario_seed(data: dict, seed: int | None) -> int:
    """Resolve the run seed: explicit override, else ``random_seed`` (legacy ``seed`` fallback)."""
    if seed is not None:
        return _coerce_int(seed, "seed")
    if "random_seed" in data:
        return _coerce_int(data.get("random_seed"), "random_seed")
    return _coerce_int(data.get("seed", 42), "seed")


def _validated_items(value: object, collection: str, id_key: str) -> list[dict]:
    """Normalize a scenario collection to a list of dicts with an id key.

    Raises ``ValueError`` (not ``KeyError``/``TypeError``) when an entry
    is not a dict or lacks its id key, so callers surface 422 instead
    of 500.
    """
    items = _as_list(value)
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(
                f"bad scenario {collection}[{index}]: expected dict, "
                f"got {type(item).__name__}"
            )
        if id_key not in item:
            raise ValueError(
                f"bad scenario {collection}[{index}]: missing {id_key!r}"
            )
    return items


def build_world(data: dict, seed: int | None = None) -> World:
    """Build a :class:`World` from a scenario document.

    Nodes/edges/incidents/boats/teams/shelters are validated with the
    pydantic world models; ``seed`` defaults to the scenario's
    ``random_seed``. Collections accept either the runnable list form
    or the ``mini_graph.json`` dict form.
    """
    world_seed = _scenario_seed(data, seed)
    nodes = {item["node_id"]: Node.model_validate(item) for item in _validated_items(data.get("nodes", []), "nodes", "node_id")}
    edges = {item["edge_id"]: Edge.model_validate(item) for item in _validated_items(data.get("edges", []), "edges", "edge_id")}
    incidents = {
        item["incident_id"]: Incident.model_validate(item)
        for item in _validated_items(data.get("incidents", []), "incidents", "incident_id")
    }
    boats = {
        item["boat_id"]: Boat.model_validate(item) for item in _validated_items(data.get("boats", []), "boats", "boat_id")
    }
    teams = {
        item["team_id"]: GroundTeam.model_validate(item)
        for item in _validated_items(data.get("teams", []), "teams", "team_id")
    }
    shelters = {
        item["shelter_id"]: Shelter.model_validate(item)
        for item in _validated_items(data.get("shelters", []), "shelters", "shelter_id")
    }
    return World(
        nodes=nodes,
        edges=edges,
        incidents=incidents,
        boats=boats,
        teams=teams,
        shelters=shelters,
        tick=_coerce_int(data.get("tick", 0), "tick"),
        seed=world_seed,
    )


def build_simulation(
    data: dict, seed: int | None = None, snapshot_every: int = 10,
    strategy: str | None = None,
) -> Simulation:
    """Build a :class:`Simulation` and preload the scenario's scheduler events."""
    world = build_world(data, seed=seed)
    simulation_seed = _scenario_seed(data, seed)
    raw_weights = data.get("weights", {})
    if raw_weights is None:
        raw_weights = {}
    if not isinstance(raw_weights, dict):
        raise ValueError(f"bad scenario field 'weights': {raw_weights!r}")
    weights = Weights(**raw_weights)
    resolved = strategy if strategy is not None else str(data.get("strategy", "centralized"))
    if resolved == "centralized":
        scheduler = CentralizedScheduler(weights)
    elif resolved == "negotiation":
        scheduler = NegotiationScheduler(weights)
    else:
        raise ValueError(
            f"unknown strategy: {resolved!r} (expected 'centralized' or 'negotiation')"
        )
    raw_network = data.get("network", {})
    if raw_network is None:
        raw_network = {}
    if not isinstance(raw_network, dict):
        raise ValueError(f"bad scenario field 'network': {raw_network!r}")
    simulation = Simulation(
        world, seed=simulation_seed, snapshot_every=snapshot_every,
        scheduler=scheduler,
        network_config=dict(raw_network),
    )
    for index, event in enumerate(_as_list(data.get("events", []))):
        if not isinstance(event, dict):
            raise ValueError(
                f"bad scenario events[{index}]: expected dict, "
                f"got {type(event).__name__}"
            )
        for key in ("tick", "kind", "event_id"):
            if key not in event:
                raise ValueError(f"bad scenario events[{index}]: missing {key!r}")
        payload = event.get("payload", {})
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            raise ValueError(
                f"bad scenario events[{index}]: 'payload' must be a dict"
            )
        simulation.manager.scheduler.push(
            _coerce_int(event["tick"], f"events[{index}].tick"),
            str(event["kind"]),
            dict(payload),
            str(event["event_id"]),
        )
    return simulation


def summarize(simulation: Simulation) -> dict:
    """Count served/unserved incidents plus dispatch commit/reject stats."""
    served = sum(
        1 for incident in simulation.world.incidents.values()
        if incident.status == "SERVED"
    )
    unserved = len(simulation.world.incidents) - served
    committed = sum(
        1 for entry in simulation.manager.event_log if entry["kind"] == "COMMITTED"
    )
    rejected_by_reason: dict[str, int] = {}
    for entry in simulation.manager.event_log:
        if entry["kind"] != "REJECTED":
            continue
        detail = entry.get("detail")
        reason = detail.get("reason", "") if isinstance(detail, dict) else ""
        rejected_by_reason[reason] = rejected_by_reason.get(reason, 0) + 1
    return {
        "ticks": simulation.tick,
        "strategy": getattr(simulation.scheduler, "strategy", "centralized"),
        "served": served,
        "unserved": unserved,
        "snapshots": sorted(simulation.snapshots),
        "committed": committed,
        "rejected_by_reason": rejected_by_reason,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a flood-rescue scenario headless.")
    parser.add_argument("--scenario", required=True, help="Path to a scenario JSON file.")
    parser.add_argument("--ticks", type=int, default=None, help="Max ticks to simulate.")
    parser.add_argument("--seed", type=int, default=None, help="Override the scenario seed.")
    parser.add_argument(
        "--strategy",
        choices=["centralized", "negotiation"],
        default=None,
        help="Dispatch strategy (default: centralized; overrides scenario file).",
    )
    args = parser.parse_args(argv)

    data = load_scenario(args.scenario)
    max_ticks = args.ticks if args.ticks is not None else _coerce_int(data.get("ticks", 120), "ticks")
    strategy = args.strategy if args.strategy is not None else str(data.get("strategy", "centralized"))
    simulation = build_simulation(data, seed=args.seed, strategy=strategy)
    simulation.run(max_ticks)
    summary = summarize(simulation)
    print(f"scenario: {data.get('scenario_name', args.scenario)}")
    print(f"strategy: {summary['strategy']}")
    print(f"ticks: {summary['ticks']}")
    print(f"served: {summary['served']}")
    print(f"unserved: {summary['unserved']}")
    print(f"committed: {summary['committed']}")
    print(f"rejected_by_reason: {summary['rejected_by_reason']}")
    print(f"snapshots: {summary['snapshots']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
