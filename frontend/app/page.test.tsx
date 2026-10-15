/** Dashboard page: header badges, map+panels wiring, timeline→explanation sync. */
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Assignment, CommsState, SimEvent, SimulationMetrics, WorldState } from "../types";
import DashboardPage from "./page";

const sim = vi.hoisted(() => ({
  simulationId: null as string | null,
  tick: 60,
  status: "running",
  strategy: "centralized" as const,
  world: null as unknown as WorldState,
  events: [] as SimEvent[],
  assignments: [] as Assignment[],
  assignmentHistory: [],
  metrics: null as unknown as SimulationMetrics,
  comms: null as unknown as CommsState,
  snapshots: [10, 20],
  backendReachable: false,
  demoMode: true,
  wsConnected: false,
  loading: false,
  error: null as string | null,
  speed: 1,
  setSpeed: vi.fn(),
  pollIntervalMs: 2000,
  create: vi.fn(),
  start: vi.fn(),
  pause: vi.fn(),
  step: vi.fn(),
  inject: vi.fn(),
  replay: vi.fn(),
  refresh: vi.fn(),
  setStrategy: vi.fn(),
}));

vi.mock("../hooks/useSimulation", () => ({ useSimulation: () => sim }));

import { DEMO_ASSIGNMENTS, DEMO_COMMS, DEMO_EVENTS, DEMO_METRICS, DEMO_WORLD } from "../lib/demo-data";

beforeEach(() => {
  vi.clearAllMocks();
  sim.simulationId = null;
  sim.backendReachable = false;
  sim.wsConnected = false;
  sim.tick = 60;
  sim.status = "running";
  sim.world = DEMO_WORLD;
  sim.events = DEMO_EVENTS;
  sim.assignments = DEMO_ASSIGNMENTS;
  sim.metrics = DEMO_METRICS;
  sim.comms = DEMO_COMMS;
  sim.error = null;
});

describe("DashboardPage", () => {
  it("renders the command header without a status pill", () => {
    const { container } = render(<DashboardPage />);
    expect(screen.getByText("Flood Rescue Dispatch — Command Dashboard")).toBeInTheDocument();
    expect(container.querySelector(".run-summary")).toBeNull();
    expect(screen.queryByText(/status: running/)).toBeNull();
    expect(screen.queryByText(/backend live/)).toBeNull();
  });

  it("shows the offline SVG map and all side panels", () => {
    const { container } = render(<DashboardPage />);
    expect(container.querySelector("svg")).not.toBeNull();
    for (const heading of ["Incidents \\(3\\)", "Decision explanation", "Comms monitor", "Timeline", "Metrics"]) {
      expect(screen.getByText(new RegExp(heading))).toBeInTheDocument();
    }
  });

  it("clicking a timeline event syncs the explanation panel selection", () => {
    render(<DashboardPage />);
    // The COMMITTED tick-41 row references ASN-00002; clicking it selects that chain.
    fireEvent.click(screen.getAllByText("COMMITTED")[0]);
    expect(screen.getByText(/Selected: TEAM-01 → INC-03/)).toBeInTheDocument();
  });

  it("footer documents the deterministic-tick + lifecycle contract", () => {
    render(<DashboardPage />);
    expect(screen.getByText(/Deterministic ticks only/)).toBeInTheDocument();
    expect(screen.getByText(/PROPOSED→COMMITTED/)).toBeInTheDocument();
  });

  it("fills a next-tick progress bar while running, hidden otherwise", () => {
    sim.status = "running";
    const { container } = render(<DashboardPage />);
    const bar = container.querySelector(".tick-progress") as HTMLElement;
    expect(bar).not.toBeNull();
    expect(bar.style.animationDuration).toBe("2000ms");
  });

  it("hides the progress bar when not running", () => {
    sim.status = "idle";
    const { container } = render(<DashboardPage />);
    expect(container.querySelector(".tick-progress")).toBeNull();
  });
});
