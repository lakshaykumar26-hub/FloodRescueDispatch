"use client";

import { useState } from "react";
import type { Strategy } from "../types";

interface Props {
  status: string;
  strategy: Strategy;
  loading: boolean;
  hasSim: boolean;
  /** True once the sim has started (running/paused/completed). The API
   * rejects step/replay before start with 409 NOT_STARTED, so keep those
   * buttons disabled until then instead of letting the call fail. */
  started: boolean;
  speed: number;
  onCreate: (strategy: Strategy, scenario: string) => void;
  onStart: () => void;
  onPause: () => void;
  onStep: (steps: number) => void;
  onSpeed: (s: number) => void;
  onStrategy: (s: Strategy) => void;
  onInject: (kind: string, payload: Record<string, unknown>) => void;
  onReplay: (fromTick?: number) => void;
}

const INJECTS: { label: string; kind: string; payload: Record<string, unknown> }[] = [
  { label: "Bridge closure R-11", kind: "CLOSURE", payload: { edge_id: "R-11" } },
  { label: "Boat failure BOAT-02", kind: "BOAT_FAILURE", payload: { boat_id: "BOAT-02" } },
  { label: "Shelter overflow 02", kind: "SHELTER_OVERFLOW", payload: { shelter_id: "SHELTER-02" } },
  { label: "New incident N-14", kind: "INCIDENT_ARRIVAL", payload: { incident_id: "INC-13", node_id: "N-14", urgency: 4, people: 2, required_capabilities: ["ground"] } },
  { label: "Partition BOAT-03", kind: "PARTITION_START", payload: { agent_id: "BOAT-03", duration_ticks: 20 } },
  { label: "Heal partition", kind: "PARTITION_HEAL", payload: { agent_id: "BOAT-03" } },
];

export default function ControlsBar(p: Props) {
  const [scenario, setScenario] = useState("baseline");
  const [replayTick, setReplayTick] = useState("");
  return (
    <div className="rounded border border-slate-700 bg-slate-900 p-3">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <select value={scenario} onChange={(e) => setScenario(e.target.value)} className="rounded bg-slate-800 px-2 py-1" aria-label="Scenario">
          {["baseline", "bridge_closure", "boat_failure", "shelter_overflow", "combined_disaster"].map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
        <select value={p.strategy} onChange={(e) => p.onStrategy(e.target.value as Strategy)} className="rounded bg-slate-800 px-2 py-1" aria-label="Strategy">
          <option value="centralized">centralized</option>
          <option value="negotiation">negotiation</option>
        </select>
        <button disabled={p.loading} onClick={() => p.onCreate(p.strategy, scenario)} className="rounded bg-emerald-700 px-2 py-1 hover:bg-emerald-600 disabled:opacity-50">Create sim</button>
        <span className="text-slate-500">|</span>
        <button disabled={!p.hasSim} onClick={p.onStart} className="rounded bg-sky-700 px-2 py-1 hover:bg-sky-600 disabled:opacity-50">▶ Play ({p.status})</button>
        <button
          disabled={!p.started}
          title={p.started ? "Pause the run" : "Press Play first"}
          onClick={p.onPause}
          className="rounded bg-slate-700 px-2 py-1 hover:bg-slate-600 disabled:opacity-50"
        >
          ⏸ Pause
        </button>
        <button
          disabled={!p.started}
          title={p.started ? "Advance one tick" : "Press Play first — the API rejects steps before start (409 NOT_STARTED)"}
          onClick={() => p.onStep(1)}
          className="rounded bg-slate-700 px-2 py-1 hover:bg-slate-600 disabled:opacity-50"
        >
          Step +1
        </button>
        <select value={p.speed} onChange={(e) => p.onSpeed(Number(e.target.value))} className="rounded bg-slate-800 px-2 py-1" aria-label="Speed">
          <option value={1}>1×</option>
          <option value={2}>2×</option>
          <option value={4}>4×</option>
        </select>
        <span className="text-slate-500">|</span>
        <input value={replayTick} onChange={(e) => setReplayTick(e.target.value)} placeholder="replay from tick" className="w-28 rounded bg-slate-800 px-2 py-1" aria-label="Replay from tick" />
        <button
          disabled={!p.started}
          title={p.started ? "Re-execute deterministically" : "Press Play first — replay needs a started sim"}
          onClick={() => p.onReplay(replayTick ? Number(replayTick) : undefined)}
          className="rounded bg-purple-700 px-2 py-1 hover:bg-purple-600 disabled:opacity-50"
        >
          ↺ Replay
        </button>
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5 text-xs">
        <span className="py-1 text-slate-400">Inject:</span>
        {INJECTS.map((inj) => (
          <button
            key={inj.label}
            disabled={!p.hasSim}
            onClick={() => p.onInject(inj.kind, inj.payload)}
            className="rounded bg-amber-800 px-2 py-1 hover:bg-amber-700 disabled:opacity-50"
          >
            {inj.label}
          </button>
        ))}
      </div>
    </div>
  );
}
