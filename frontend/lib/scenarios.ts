/**
 * Scenario catalog for the dashboard picker.
 * Names must match `scenarios/<name>.json` in the repo root — the backend
 * resolves them by name (see `backend/app/api/store.py::_resolve_scenario`).
 * `mini_graph.json` is excluded: it is a routing-test fixture, not a
 * runnable simulation (no incidents/boats/shelters).
 */
export interface ScenarioMeta {
  name: string;
  label: string;
  blurb: string;
}

export const SCENARIOS: ScenarioMeta[] = [
  {
    name: "single_boat_test",
    label: "Single boat test",
    blurb: "One boat, several rescue requests, and shelter drop-offs.",
  },
  {
    name: "baseline",
    label: "Baseline flood",
    blurb: "Normal dispatch across 25 nodes and 12 incidents.",
  },
  {
    name: "simultaneous_incidents",
    label: "Simultaneous incidents",
    blurb: "Five incidents at once; resource contention.",
  },
  {
    name: "bridge_closure",
    label: "Bridge closure",
    blurb: "A key waterway closes mid-run, then reopens.",
  },
  {
    name: "boat_failure",
    label: "Boat failure",
    blurb: "A loaded boat fails; the recovery workflow takes over.",
  },
  {
    name: "shelter_overflow",
    label: "Shelter overflow",
    blurb: "The primary shelter fills; arrivals reroute.",
  },
  {
    name: "network_partition",
    label: "Network partition",
    blurb: "A boat loses contact; delayed messages, stale beliefs.",
  },
  {
    name: "contradictory_reports",
    label: "Contradictory reports",
    blurb: "Conflicting hazard claims; conservative routing.",
  },
  {
    name: "duplicate_messages",
    label: "Duplicate messages",
    blurb: "Every message arrives twice; idempotent handling.",
  },
  {
    name: "reconnection",
    label: "Reconnection",
    blurb: "Outage plus closure; reconcile on reconnect.",
  },
  {
    name: "combined_disaster",
    label: "Combined disaster",
    blurb: "Closure, failure, full shelter, and outage at once.",
  },
];

export const DEFAULT_SCENARIO = "single_boat_test";
