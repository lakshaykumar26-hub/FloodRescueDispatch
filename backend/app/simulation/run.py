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


def build_world(data: dict, seed: int | None = None) -> World:
    """Build a :class:`World` from a scenario document.

    Nodes/edges/incidents/boats/teams/shelters are validated with the
    pydantic world models; ``seed`` defaults to the scenario's
    ``random_seed``.
    """
    world_seed = seed if seed is not None else int(data.get("random_seed", 42))
    nodes = {item["node_id"]: Node.model_validate(item) for item in data.get("nodes", [])}
    edges = {item["edge_id"]: Edge.model_validate(item) for item in data.get("edges", [])}
    incidents = {
        item["incident_id"]: Incident.model_validate(item)
        for item in data.get("incidents", [])
    }
    boats = {
        item["boat_id"]: Boat.model_validate(item) for item in data.get("boats", [])
    }
    teams = {
        item["team_id"]: GroundTeam.model_validate(item)
        for item in data.get("teams", [])
    }
    shelters = {
        item["shelter_id"]: Shelter.model_validate(item)
        for item in data.get("shelters", [])
    }
    return World(
        nodes=nodes,
        edges=edges,
        incidents=incidents,
        boats=boats,
        teams=teams,
        shelters=shelters,
        tick=int(data.get("tick", 0)),
        seed=world_seed,
    )


def build_simulation(
    data: dict, seed: int | None = None, snapshot_every: int = 10,
    strategy: str | None = None,
) -> Simulation:
    """Build a :class:`Simulation` and preload the scenario's scheduler events."""
    world = build_world(data, seed=seed)
    simulation_seed = seed if seed is not None else int(data.get("random_seed", 42))
    weights = Weights(**data.get("weights", {}))
    resolved = strategy if strategy is not None else str(data.get("strategy", "centralized"))
    if resolved == "centralized":
        scheduler = CentralizedScheduler(weights)
    elif resolved == "negotiation":
        scheduler = NegotiationScheduler(weights)
    else:
        raise ValueError(
            f"unknown strategy: {resolved!r} (expected 'centralized' or 'negotiation')"
        )
    simulation = Simulation(
        world, seed=simulation_seed, snapshot_every=snapshot_every,
        scheduler=scheduler,
    )
    for event in data.get("events", []):
        simulation.manager.scheduler.push(
            int(event["tick"]),
            str(event["kind"]),
            dict(event.get("payload", {})),
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
        reason = entry["detail"].get("reason", "")
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
    max_ticks = args.ticks if args.ticks is not None else int(data.get("ticks", 120))
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
