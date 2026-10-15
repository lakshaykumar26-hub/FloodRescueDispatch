"use client";

import { useMemo, useState } from "react";
import CommunicationsPanel from "../components/communications-panel";
import ControlsBar from "../components/controls-bar";
import ExplanationPanel from "../components/explanation-panel";
import IncidentPanel from "../components/incident-panel";
import MetricsPanel from "../components/metrics-panel";
import ResourcePanel from "../components/resource-panel";
import ShelterPanel from "../components/shelter-panel";
import SyntheticMap from "../components/synthetic-map";
import TimelinePanel from "../components/timeline-panel";
import { useSimulation } from "../hooks/useSimulation";
import type { SimEvent, SimulationMetrics } from "../types";

export default function DashboardPage() {
  const sim = useSimulation();
  const [selectedIncident, setSelectedIncident] = useState<string | null>(null);
  const [selectedResource, setSelectedResource] = useState<string | null>(null);
  const [selectedAssignment, setSelectedAssignment] = useState<string | null>(null);
  const [scrubTick, setScrubTick] = useState<number | null>(null);
  const [compareA, setCompareA] = useState<SimulationMetrics | null>(null);
  const [compareB, setCompareB] = useState<SimulationMetrics | null>(null);

  const visibleEvents = useMemo(
    () => (scrubTick === null ? sim.events : sim.events.filter((e) => e.tick <= scrubTick)),
    [sim.events, scrubTick],
  );

  const selAssignment = sim.assignments.find((a) => a.assignment_id === selectedAssignment) ?? null;
  const selectedRouteEdgeIds = selAssignment?.route_edge_ids ?? [];
  // Changed-route highlight: edges mentioned in replan/reassign history.
  const changedRouteEdgeIds = useMemo(() => {
    if (!selAssignment) return [] as string[];
    const edges = new Set<string>();
    for (const h of selAssignment.history) {
      for (const eid of selAssignment.route_edge_ids) {
        if (h.reason.includes(eid)) edges.add(eid);
      }
      const m = h.reason.match(/[RW]-\d+/g);
      if (m && /REPLAN|reassign|EDGE_|SHELTER/i.test(h.reason)) m.forEach((e) => edges.add(e));
    }
    return [...edges].filter((e) => !selectedRouteEdgeIds.includes(e));
  }, [selAssignment, selectedRouteEdgeIds]);

  const disconnectedIds = sim.comms?.disconnected ?? [];

  const pickEvent = (e: SimEvent) => {
    setScrubTick(e.tick);
    const blob = JSON.stringify(e.detail);
    const asn = sim.assignments.find((a) => blob.includes(a.assignment_id));
    if (asn) {
      setSelectedAssignment(asn.assignment_id);
      setSelectedIncident(asn.incident_id);
      setSelectedResource(asn.resource_id);
    }
    const inc = sim.world.incidents.find((i) => blob.includes(i.incident_id));
    if (inc) setSelectedIncident(inc.incident_id);
  };

  const maxTick = Math.max(sim.tick, ...sim.events.map((e) => e.tick), ...sim.snapshots, 0);

  return (
    <main className="min-h-screen p-3">
      <header className="mb-3 flex flex-wrap items-center gap-3">
        <div>
          <h1 className="text-lg font-bold">Flood Rescue Dispatch — Command Dashboard</h1>
          <p className="text-xs text-slate-400">Synthetic data only · not a real emergency system · map is pure SVG (no tiles)</p>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2 text-xs">
          <span className="rounded bg-slate-800 px-2 py-1">sim: {sim.simulationId ?? "—"}</span>
          <span className="rounded bg-slate-800 px-2 py-1">tick: {scrubTick ?? sim.tick}</span>
          <span className="rounded bg-slate-800 px-2 py-1">status: {sim.status}</span>
          <span className={`rounded px-2 py-1 ${sim.backendReachable ? "bg-emerald-800" : "bg-amber-800"}`}>
            {!sim.backendReachable
              ? "backend unreachable — DEMO data"
              : sim.simulationId
                ? `backend live${sim.wsConnected ? " · WS ✓" : " · WS ✕"}`
                : "backend live · DEMO preview (create a sim)"}
           </span>
        </div>
      </header>

      {sim.error && (
        <div className="mb-2 rounded border border-amber-700 bg-amber-900/30 p-2 text-xs text-amber-200" role="alert">
          {sim.error}
        </div>
      )}

      <div className="mb-3">
        <ControlsBar
          status={sim.status}
          strategy={sim.strategy}
          loading={sim.loading}
          hasSim={sim.simulationId !== null}
          started={sim.simulationId !== null && sim.status !== "created" && sim.status !== "idle"}
          speed={sim.speed}
          onCreate={(s, sc) => void sim.create(s, sc)}
          onStart={() => void sim.start()}
          onPause={() => void sim.pause()}
          onStep={(n) => void sim.step(n)}
          onSpeed={sim.setSpeed}
          onStrategy={sim.setStrategy}
          onInject={(k, p) => void sim.inject(k, p)}
          onReplay={(t) => void sim.replay(t)}
        />
      </div>

      <div className="grid grid-cols-1 gap-3 xl:grid-cols-3">
        <div className="space-y-3 xl:col-span-2">
          <SyntheticMap
            world={sim.world}
            selectedRouteEdgeIds={selectedRouteEdgeIds}
            changedRouteEdgeIds={changedRouteEdgeIds}
            selectedIncidentId={selectedIncident}
            selectedResourceId={selectedResource}
            disconnectedIds={disconnectedIds}
            onSelectIncident={(id) => {
              setSelectedIncident(id);
              const asn = sim.assignments.find((a) => a.incident_id === id);
              if (asn) {
                setSelectedAssignment(asn.assignment_id);
                setSelectedResource(asn.resource_id);
              }
            }}
            onSelectResource={setSelectedResource}
          />
          <TimelinePanel
            events={sim.events}
            tick={sim.tick}
            maxTick={maxTick}
            scrubTick={scrubTick}
            onScrub={setScrubTick}
            onPickEvent={pickEvent}
          />
          <MetricsPanel
            metrics={sim.metrics}
            compareA={compareA}
            compareB={compareB}
            onCompareLoaded={(a, b) => {
              setCompareA(a);
              setCompareB(b);
            }}
            liveStrategy={sim.strategy}
          />
        </div>
        <div className="space-y-3">
          <IncidentPanel incidents={visibleEvents.length ? sim.world.incidents : []} selectedId={selectedIncident} onSelect={setSelectedIncident} tick={scrubTick ?? sim.tick} />
          <ResourcePanel boats={sim.world.boats} teams={sim.world.teams} selectedId={selectedResource} onSelect={setSelectedResource} disconnectedIds={disconnectedIds} />
          <ShelterPanel shelters={sim.world.shelters} />
          <ExplanationPanel assignments={sim.assignments} events={visibleEvents} selectedId={selectedAssignment} onSelect={setSelectedAssignment} />
          <CommunicationsPanel comms={sim.comms} />
        </div>
      </div>

      <footer className="mt-3 text-[11px] text-slate-500">
        Deterministic ticks only (wall-clock for display). Assignment lifecycle PROPOSED→COMMITTED→ACKNOWLEDGED→IN_PROGRESS→COMPLETED (+REJECTED/EXPIRED/CANCELLED/REQUIRES_RECONCILIATION). Safety rejections are hard rejects with reasons.
      </footer>
    </main>
  );
}
