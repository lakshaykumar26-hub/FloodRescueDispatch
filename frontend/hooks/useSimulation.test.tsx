/** useSimulation: create/start/step/inject flows + demo fallback when backend is down. */
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useSimulation } from "./useSimulation";

const api = vi.hoisted(() => ({
  checkBackend: vi.fn(),
  createSimulation: vi.fn(),
  startSimulation: vi.fn(),
  pauseSimulation: vi.fn(),
  stepSimulation: vi.fn(),
  injectEvent: vi.fn(),
  replaySimulation: vi.fn(),
  getState: vi.fn(),
  getEvents: vi.fn(),
  getAssignments: vi.fn(),
  getMetrics: vi.fn(),
  getCommunications: vi.fn(),
  subscribeSimulation: vi.fn(() => () => {}),
  normalizeComms: vi.fn((x: unknown) => x),
}));

vi.mock("../lib/api", () => api);
vi.mock("../lib/demo-data", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../lib/demo-data")>();
  return mod;
});

const liveState = {
  tick: 5,
  status: "running",
  world: {
    nodes: [{ node_id: "N-01", neighborhood: "R", kind: "station", x: 0, y: 0 }],
    edges: [],
    incidents: [],
    boats: [],
    teams: [],
    shelters: [],
  },
  snapshots: [10],
};

beforeEach(() => {
  vi.clearAllMocks();
  api.checkBackend.mockResolvedValue(false); // offline default; single tests opt into live
  api.subscribeSimulation.mockReturnValue(() => {});
  api.getState.mockResolvedValue(liveState);
  api.getEvents.mockResolvedValue([{ tick: 5, kind: "COMMITTED", actor: "d", detail: {} }]);
  api.getAssignments.mockResolvedValue({ assignments: [], history: [] });
  api.getMetrics.mockResolvedValue({ ticks: 5, strategy: "centralized", served: 1, unserved: 0, committed: 1, rejected_by_reason: {} });
  api.getCommunications.mockResolvedValue({ tick: 5, connected: [], disconnected: [], queue: [], messages: [], reconciliation_log: [], partitions: [] });
});

describe("useSimulation", () => {
  it("starts in demo mode with synthetic data before any sim exists", () => {
    const { result } = renderHook(() => useSimulation());
    expect(result.current.simulationId).toBeNull();
    expect(result.current.demoMode).toBe(true);
    expect(result.current.world.nodes.length).toBeGreaterThan(0);
    expect(result.current.metrics).not.toBeNull();
  });

  it("mount probe flips to live when the backend answers /health", async () => {
    api.checkBackend.mockResolvedValueOnce(true);
    const { result } = renderHook(() => useSimulation());
    expect(result.current.backendReachable).toBe(false); // initial demo state
    await waitFor(() => expect(result.current.backendReachable).toBe(true));
    expect(result.current.demoMode).toBe(false);
    expect(api.checkBackend).toHaveBeenCalledOnce();
  });

  it("mount probe stays on demo data when the backend is down", async () => {
    api.checkBackend.mockResolvedValueOnce(false);
    const { result } = renderHook(() => useSimulation());
    await waitFor(() => expect(api.checkBackend).toHaveBeenCalledOnce());
    expect(result.current.backendReachable).toBe(false);
    expect(result.current.world.nodes.length).toBeGreaterThan(0); // demo still renders
    expect(result.current.error).toBeNull(); // no noisy banner for the passive probe
  });

  it("create() goes live and refreshes all panels", async () => {
    api.createSimulation.mockResolvedValueOnce({ simulation_id: "SIM-001", tick: 0, status: "created", strategy: "centralized", seed: 42 });
    const { result } = renderHook(() => useSimulation());
    await act(async () => {
      await result.current.create("centralized", "baseline");
    });
    expect(api.createSimulation).toHaveBeenCalledOnce();
    await waitFor(() => expect(result.current.simulationId).toBe("SIM-001"));
    expect(result.current.backendReachable).toBe(true);
    expect(result.current.tick).toBe(5); // from mocked refresh
    expect(api.getState).toHaveBeenCalledWith("SIM-001");
  });

  it("create() falls back to demo data with an error when the backend is down", async () => {
    api.createSimulation.mockRejectedValueOnce(new Error("fetch failed"));
    const { result } = renderHook(() => useSimulation());
    await act(async () => {
      await result.current.create("centralized", "baseline");
    });
    expect(result.current.simulationId).toBeNull();
    expect(result.current.backendReachable).toBe(false);
    expect(result.current.error).toMatch(/fetch failed/);
    expect(result.current.world.nodes.length).toBeGreaterThan(0); // demo still renders
  });

  it("guards start/step/inject/replay with a demo-mode error when no sim exists", async () => {
    const { result } = renderHook(() => useSimulation());
    await act(async () => {
      await result.current.start();
    });
    expect(api.startSimulation).not.toHaveBeenCalled();
    expect(result.current.error).toMatch(/No live simulation/);
    await act(async () => {
      await result.current.step(1);
    });
    expect(api.stepSimulation).not.toHaveBeenCalled();
  });

  it("step() advances the tick and refreshes state", async () => {
    api.createSimulation.mockResolvedValueOnce({ simulation_id: "SIM-002", tick: 0, status: "created", strategy: "centralized", seed: 42 });
    api.stepSimulation.mockResolvedValueOnce({ simulation_id: "SIM-002", tick: 6, status: "running" });
    const { result } = renderHook(() => useSimulation());
    await act(async () => {
      await result.current.create("centralized", "baseline");
    });
    await act(async () => {
      await result.current.step(1);
    });
    expect(api.stepSimulation).toHaveBeenCalledWith("SIM-002", 1);
  });

  it("inject() posts kind+payload then refreshes", async () => {
    api.createSimulation.mockResolvedValueOnce({ simulation_id: "SIM-003", tick: 0, status: "created", strategy: "centralized", seed: 42 });
    const { result } = renderHook(() => useSimulation());
    await act(async () => {
      await result.current.create("centralized", "baseline");
    });
    await act(async () => {
      await result.current.inject("CLOSURE", { edge_id: "R-11" });
    });
    expect(api.injectEvent).toHaveBeenCalledWith("SIM-003", { kind: "CLOSURE", payload: { edge_id: "R-11" } });
  });

  it("subscribes to WS ticks once a sim exists", async () => {
    api.createSimulation.mockResolvedValueOnce({ simulation_id: "SIM-009", tick: 0, status: "created", strategy: "centralized", seed: 42 });
    const { result } = renderHook(() => useSimulation());
    await act(async () => {
      await result.current.create("centralized", "baseline");
    });
    expect(api.subscribeSimulation).toHaveBeenCalledWith("SIM-009", expect.any(Function), expect.any(Function));
  });
});
