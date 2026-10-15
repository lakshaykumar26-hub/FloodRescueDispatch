"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  checkBackend,
  createSimulation,
  getAssignments,
  getCommunications,
  getEvents,
  getMetrics,
  getState,
  injectEvent,
  normalizeComms,
  pauseSimulation,
  replaySimulation,
  startSimulation,
  stepSimulation,
  subscribeSimulation,
} from "../lib/api";
import { DEMO_ASSIGNMENTS, DEMO_COMMS, DEMO_EVENTS, DEMO_METRICS, DEMO_WORLD } from "../lib/demo-data";
import type {
  Assignment,
  AssignmentHistoryEntry,
  CommsState,
  SimEvent,
  SimulationMetrics,
  Strategy,
  WorldState,
} from "../types";

export interface UseSimulation {
  simulationId: string | null;
  tick: number;
  status: string;
  strategy: Strategy;
  world: WorldState;
  events: SimEvent[];
  assignments: Assignment[];
  assignmentHistory: AssignmentHistoryEntry[];
  metrics: SimulationMetrics | null;
  comms: CommsState | null;
  snapshots: number[];
  backendReachable: boolean;
  demoMode: boolean;
  wsConnected: boolean;
  loading: boolean;
  error: string | null;
  speed: number;
  setSpeed: (s: number) => void;
  /** Current auto-step cadence in ms (drives the next-tick progress bar). */
  pollIntervalMs: number;
  create: (strategy: Strategy, scenario?: string) => Promise<void>;
  start: () => Promise<void>;
  pause: () => Promise<void>;
  step: (steps?: number) => Promise<void>;
  inject: (kind: string, payload: Record<string, unknown>) => Promise<void>;
  replay: (fromSnapshotTick?: number) => Promise<void>;
  refresh: () => Promise<void>;
  setStrategy: (s: Strategy) => void;
}

const POLL_BY_SPEED: Record<number, number> = { 1: 2000, 2: 1000, 4: 500 };

export function useSimulation(): UseSimulation {
  const [simulationId, setSimulationId] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const [status, setStatus] = useState("idle");
  const [strategy, setStrategy] = useState<Strategy>("centralized");
  const [world, setWorld] = useState<WorldState>(DEMO_WORLD);
  const [events, setEvents] = useState<SimEvent[]>(DEMO_EVENTS);
  const [assignments, setAssignments] = useState<Assignment[]>(DEMO_ASSIGNMENTS);
  const [assignmentHistory, setAssignmentHistory] = useState<AssignmentHistoryEntry[]>([]);
  const [metrics, setMetrics] = useState<SimulationMetrics | null>(DEMO_METRICS);
  const [comms, setComms] = useState<CommsState | null>(DEMO_COMMS);
  const [snapshots, setSnapshots] = useState<number[]>([]);
  const [backendReachable, setBackendReachable] = useState(false);
  const [wsConnected, setWsConnected] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [speed, setSpeed] = useState(1);
  const simIdRef = useRef<string | null>(null);
  const statusRef = useRef(status);
  statusRef.current = status;

  // Mount-time liveness probe so the header badge reflects reality instead
  // of assuming "unreachable" until the first sim action. Demo data stays
  // on screen either way; only the flag (and badge) changes.
  useEffect(() => {
    let live = true;
    void checkBackend().then((ok) => {
      if (live) setBackendReachable(ok);
    });
    return () => {
      live = false;
    };
  }, []);

  const refresh = useCallback(async () => {
    const id = simIdRef.current;
    if (!id) return;
    try {
      const [st, ev, asg, met, cm] = await Promise.all([
        getState(id),
        getEvents(id, 0),
        getAssignments(id),
        getMetrics(id).catch(() => null),
        getCommunications(id).catch(() => null),
      ]);
      setTick(st.tick);
      setStatus(st.status);
      setWorld(st.world);
      setSnapshots(st.snapshots);
      setEvents(ev);
      setAssignments(asg.assignments);
      setAssignmentHistory(asg.history);
      if (met) setMetrics(met);
      if (cm) setComms(cm);
      setBackendReachable(true);
      setError(null);
    } catch (e) {
      setBackendReachable(false);
      setError(e instanceof Error ? e.message : "backend unreachable");
    }
  }, []);

  // WS subscription per simulation.
  useEffect(() => {
    if (!simulationId) return;
    const unsub = subscribeSimulation(
      simulationId,
      (msg) => {
        if (typeof msg.tick === "number" && msg.tick >= 0) setTick(msg.tick);
        if (msg.events && msg.events.length > 0) {
          setEvents((prev) => {
            const seen = new Set(prev.map((e) => `${e.tick}:${e.kind}:${JSON.stringify(e.detail)}`));
            const fresh = msg.events!.filter((e) => !seen.has(`${e.tick}:${e.kind}:${JSON.stringify(e.detail)}`));
            return [...prev, ...fresh].sort((a, b) => a.tick - b.tick);
          });
        }
        if (msg.comms_digest) {
          try {
            setComms(normalizeComms(msg.comms_digest));
          } catch {
            // keep last comms
          }
        }
        // State may have moved; throttle a refresh through polling loop.
      },
      (ok) => setWsConnected(ok),
    );
    return unsub;
  }, [simulationId]);

  // Auto-advance while running: Play means "run continuously". The engine
  // only moves when POST .../step is called (WS pushes on explicit actions
  // only), so each poll interval steps exactly one tick and then refreshes
  // the panels. Pause halts the loop; Step +1 is the manual one-tick path.
  useEffect(() => {
    if (!simulationId || !backendReachable) return;
    if (statusRef.current !== "running") return;
    const interval = POLL_BY_SPEED[speed] ?? 2000;
    let inFlight = false; // never overlap two step+refresh cycles
    const t = window.setInterval(() => {
      const id = simIdRef.current;
      if (!id || inFlight) return;
      inFlight = true;
      void (async () => {
        try {
          const r = await stepSimulation(id, 1);
          setTick(r.tick);
          setStatus(r.status);
          await refresh();
        } catch (e) {
          setError(e instanceof Error ? e.message : "auto-step failed");
        } finally {
          inFlight = false;
        }
      })();
    }, interval);
    return () => window.clearInterval(t);
  }, [simulationId, backendReachable, speed, status, refresh]);

  const create = useCallback(
    async (s: Strategy, scenario = "baseline") => {
      setLoading(true);
      setError(null);
      try {
        const res = await createSimulation({ scenario_name: scenario, scenario, strategy: s, seed: 42, ticks: 120 });
        simIdRef.current = res.simulation_id;
        setSimulationId(res.simulation_id);
        setStrategy(res.strategy === "negotiation" ? "negotiation" : "centralized");
        setTick(res.tick);
        setStatus(res.status);
        setBackendReachable(true);
        await refresh();
      } catch (e) {
        // Backend absent: stay in demo mode with synthetic data.
        setBackendReachable(false);
        setError(e instanceof Error ? e.message : "backend unreachable — demo data shown");
        simIdRef.current = null;
        setSimulationId(null);
        setWorld(DEMO_WORLD);
        setEvents(DEMO_EVENTS);
        setAssignments(DEMO_ASSIGNMENTS);
        setMetrics(DEMO_METRICS);
        setComms(DEMO_COMMS);
      } finally {
        setLoading(false);
      }
    },
    [refresh],
  );

  const guardDemo = useCallback(() => {
    if (!simIdRef.current) {
      setError("No live simulation — backend unreachable, demo data shown. Start backend and Create sim.");
      return true;
    }
    return false;
  }, []);

  const start = useCallback(async () => {
    if (guardDemo()) return;
    const id = simIdRef.current!;
    try {
      const r = await startSimulation(id);
      setTick(r.tick);
      setStatus(r.status);
    } catch (e) {
      setError(e instanceof Error ? e.message : "start failed");
    }
  }, [guardDemo]);

  const pause = useCallback(async () => {
    if (guardDemo()) return;
    const id = simIdRef.current!;
    try {
      const r = await pauseSimulation(id);
      setTick(r.tick);
      setStatus(r.status);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "pause failed");
    }
  }, [guardDemo, refresh]);

  const step = useCallback(
    async (steps = 1) => {
      if (guardDemo()) return;
      const id = simIdRef.current!;
      try {
        const r = await stepSimulation(id, steps);
        setTick(r.tick);
        setStatus(r.status);
        await refresh();
      } catch (e) {
        setError(e instanceof Error ? e.message : "step failed");
      }
    },
    [guardDemo, refresh],
  );

  const inject = useCallback(
    async (kind: string, payload: Record<string, unknown>) => {
      if (guardDemo()) return;
      const id = simIdRef.current!;
      try {
        await injectEvent(id, { kind, payload });
        await refresh();
      } catch (e) {
        setError(e instanceof Error ? e.message : "inject failed");
      }
    },
    [guardDemo, refresh],
  );

  const replay = useCallback(
    async (fromSnapshotTick?: number) => {
      if (guardDemo()) return;
      const id = simIdRef.current!;
      try {
        setLoading(true);
        await replaySimulation(id, fromSnapshotTick);
        await refresh();
      } catch (e) {
        setError(e instanceof Error ? e.message : "replay failed");
      } finally {
        setLoading(false);
      }
    },
    [guardDemo, refresh],
  );

  return {
    simulationId,
    tick,
    status,
    strategy,
    world,
    events,
    assignments,
    assignmentHistory,
    metrics,
    comms,
    snapshots,
    backendReachable,
    demoMode: !backendReachable,
    wsConnected,
    loading,
    error,
    speed,
    setSpeed,
    pollIntervalMs: POLL_BY_SPEED[speed] ?? 2000,
    create,
    start,
    pause,
    step,
    inject,
    replay,
    refresh,
    setStrategy,
  };
}
