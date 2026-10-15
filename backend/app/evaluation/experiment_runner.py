"""Fair strategy comparison harness (Phase 3 Step 04).

Intentional behavioral differences vs centralized (documented here so
parity checks do not mistake them for bugs):

- Negotiation prices each winner as ``cost = base + w_o * O`` where the
  opportunity term ``O = second_best_base - best_base`` (``0.0`` when only
  one feasible bid exists). Centralized scores ``base`` only.
- Losing negotiation bids are rejected at bid level with a
  ``HIGHER_COST: winner <id> cost <final> vs <loser_base>`` reason that
  cites the winner's final (opportunity-adjusted) cost. Centralized
  losers surface as feasibility/claim rejections instead.
- Negotiation syncs one agent per world entity and hands each a
  per-agent belief snapshot (``world_to_belief_snapshot`` deep copy) on
  every ``propose``. Phase-3 delivery is still perfect/full-copy (the
  snapshot mirrors global state), so parity holds; the snapshot seam
  exists so Phase 5 can degrade delivery without changing signatures.

Determinism: same scenario + seed + ticks under one strategy always
yields the same winners (rank order, sorted agent IDs, proposal IDs
derived from ``(tick, rank index)``).
"""

from __future__ import annotations

import copy
from pathlib import Path

from ..simulation.run import build_simulation, load_scenario, summarize


def run_pair(scenario_path: str | Path, ticks: int, seed: int | None = None) -> dict:
    """Run ``ticks`` ticks under each strategy from the same scenario + seed.

    The scenario file is loaded twice so each strategy starts from a
    fresh deep copy. Returns ``{"centralized": {...}, "negotiation":
    {...}}`` where each entry holds ``strategy, committed,
    rejected_by_reason, ticks, served`` (``rejected_by_reason`` tallied
    from ``REJECTED`` log reasons; ``served`` = ``SERVED`` incident
    count). No fairness math yet (Phase 8).
    """
    path = Path(scenario_path)
    results: dict[str, dict] = {}
    for strategy in ("centralized", "negotiation"):
        data = load_scenario(path)
        simulation = build_simulation(
            copy.deepcopy(data), seed=seed, strategy=strategy
        )
        simulation.run(ticks)
        summary = summarize(simulation)
        results[strategy] = {
            "strategy": summary["strategy"],
            "committed": summary["committed"],
            "rejected_by_reason": dict(summary["rejected_by_reason"]),
            "ticks": summary["ticks"],
            "served": summary["served"],
        }
    return results


__all__ = ["run_pair"]
