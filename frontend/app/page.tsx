"use client";

import { useMemo, useState } from "react";
import CommunicationsPanel from "../components/communications-panel";
import ExplanationPanel from "../components/explanation-panel";
import IncidentPanel from "../components/incident-panel";
import MetricsPanel from "../components/metrics-panel";
import SyntheticMap from "../components/synthetic-map";
import TimelinePanel from "../components/timeline-panel";
import { useSimulation } from "../hooks/useSimulation";
import { DEFAULT_SCENARIO, SCENARIOS } from "../lib/scenarios";
import type { SimEvent, SimulationMetrics } from "../types";

const ACTIVE_ASSIGNMENT = new Set(["COMMITTED", "ACKNOWLEDGED", "IN_PROGRESS"]);

function prettyStatus(status: string) {
  return status.toLowerCase().replaceAll("_", " ").replace(/^./, (c) => c.toUpperCase());
}

export default function DashboardPage() {
  const sim = useSimulation();
  const [selectedIncident, setSelectedIncident] = useState<string | null>(null);
  const [selectedAssignment, setSelectedAssignment] = useState<string | null>(null);
  const [scrubTick, setScrubTick] = useState<number | null>(null);
  const [compareA, setCompareA] = useState<SimulationMetrics | null>(null);
  const [compareB, setCompareB] = useState<SimulationMetrics | null>(null);
  const [scenario, setScenario] = useState(DEFAULT_SCENARIO);
  const [eventBusy, setEventBusy] = useState(false);
  const [eventNotice, setEventNotice] = useState("");
  const openWaterways = sim.world.edges.filter((edge) => edge.mode === "water" && edge.status === "open");
  const closedWaterways = sim.world.edges.filter((edge) => edge.mode === "water" && edge.status === "closed");
  const riskiestWaterway = [...sim.world.edges].filter((edge) => edge.mode === "water" && edge.risk_level < 1).sort((a, b) => b.risk_level - a.risk_level || a.edge_id.localeCompare(b.edge_id))[0];
  const notFailedBoats = sim.world.boats.filter((boat) => boat.status !== "FAILED" && boat.status !== "STRANDED");
  const primaryBoat = sim.world.boats[0];
  const primaryBoatOffline = Boolean(primaryBoat && sim.comms?.disconnected.includes(primaryBoat.boat_id));
  const acceptingShelters = sim.world.shelters.filter((shelter) => shelter.accepting);
  const incidentNode = sim.world.nodes.find((node) => node.kind === "incident_site");
  const usedIncidentIds = new Set(sim.world.incidents.map((incident) => incident.incident_id));
  let nextIncidentNumber = 1;
  while (usedIncidentIds.has(`INC-TEST-${String(nextIncidentNumber).padStart(2, "0")}`)) nextIncidentNumber += 1;
  const nextIncidentId = `INC-TEST-${String(nextIncidentNumber).padStart(2, "0")}`;
  const started = sim.status !== "created" && sim.status !== "idle";
  const activeScenario = SCENARIOS.find((s) => s.name === scenario) ?? SCENARIOS[0];

  // Active assignment routes are drawn on the map so rescuers visibly
  // travel along a path instead of drifting between bare nodes.
  const activeAssignments = useMemo(
    () => sim.assignments.filter((a) => ACTIVE_ASSIGNMENT.has(a.status)),
    [sim.assignments],
  );
  const activeRouteEdgeIds = useMemo(
    () => activeAssignments.flatMap((a) => a.route_edge_ids ?? []),
    [activeAssignments],
  );
  const selectedRouteEdgeIds = useMemo(() => {
    const direct = sim.assignments.find((a) => a.assignment_id === selectedAssignment)?.route_edge_ids;
    if (direct?.length) return direct;
    if (selectedIncident) {
      return sim.assignments.find((a) => a.incident_id === selectedIncident && ACTIVE_ASSIGNMENT.has(a.status))?.route_edge_ids ?? [];
    }
    return [];
  }, [sim.assignments, selectedAssignment, selectedIncident]);

  const pickTimelineEvent = (event: SimEvent) => {
    const assignmentId = event.detail?.assignment_id;
    setSelectedAssignment(typeof assignmentId === "string" ? assignmentId : null);
  };

  const selectResource = (resourceId: string) => {
    const assignment = activeAssignments.find((a) => a.resource_id === resourceId) ?? null;
    setSelectedAssignment(assignment ? assignment.assignment_id : null);
  };

  const fireEvent = async (label: string, kind: string, payload: Record<string, unknown>) => {
    if (!sim.simulationId || eventBusy) return;
    setEventBusy(true);
    setEventNotice("");
    try {
      const scheduledTick = await sim.inject(kind, payload);
      if (scheduledTick === null) return;
      if (kind === "PARTITION_START" || kind === "PARTITION_HEAL") {
        setEventNotice(`${label} applied Â· step ${scheduledTick}`);
      } else if (sim.status === "running") {
        setEventNotice(`${label} added · applies on step ${scheduledTick}`);
      } else {
        await sim.step(1);
        setEventNotice(`${label} applied · step ${scheduledTick}`);
      }
    } finally {
      setEventBusy(false);
    }
  };

  return (
    <main className="demo-shell">
      <header className="demo-header">
        <div>
          <p className="eyebrow">Flood response · live demo</p>
          <h1>Flood Rescue Dispatch — Command Dashboard</h1>
          <p className="subheading">Requests, boats, shelters, and changing road conditions in one view.</p>
        </div>
      </header>
      {sim.status === "running" && (
        <div className="tick-progress" style={{ animationDuration: `${sim.pollIntervalMs}ms` }} role="progressbar" aria-label="Next tick progress" />
      )}

      {sim.error && <div className="demo-error" role="alert">{sim.error}</div>}

      <section className="action-card" aria-label="Simulation controls">
        <div className="action-copy">
          <strong>{sim.simulationId ? `Scenario: ${activeScenario.label}` : "Start a scenario"}</strong>
          <span>{activeScenario.blurb}</span>
        </div>
        <div className="action-buttons">
          <label className="scenario-picker">
            <span className="scenario-picker-label">Scenario</span>
            <select aria-label="Scenario" value={scenario} onChange={(e) => setScenario(e.target.value)}>
              {SCENARIOS.map((s) => <option key={s.name} value={s.name}>{s.label}</option>)}
            </select>
          </label>
          {!sim.simulationId ? (
            <button className="button button-primary" disabled={sim.loading} onClick={() => void sim.create("centralized", scenario).then(() => sim.start())}>{sim.loading ? "Starting…" : `Start ${activeScenario.label}`}</button>
          ) : <>
            <button className="button button-primary" disabled={sim.loading || sim.status === "running"} onClick={() => void sim.start()}>Play</button>
            <button className="button button-secondary" disabled={sim.loading || !started || sim.status !== "running"} onClick={() => void sim.pause()}>Pause</button>
            <button className="button button-secondary" disabled={sim.loading || !started} onClick={() => void sim.step(1)}>Step</button>
            <button className="button button-secondary" disabled={sim.loading} onClick={() => void sim.create("centralized", scenario).then(() => sim.start())}>Reset {activeScenario.label}</button>
          </>}
        </div>
      </section>

      <section className="demo-grid">
        <div className="map-card">
          <div className="section-heading">
            <div><h2>Response map</h2><p>Markers are labeled. Select a request to highlight it.</p></div>
            <span className="live-label"><span className={`status-dot ${sim.simulationId ? "is-running" : ""}`} />{sim.simulationId ? "Live" : "Sample view"}</span>
          </div>
          <section className="event-builder" aria-label="Quick simulation events">
            <div className="event-toolbar-heading"><h3>Add an event</h3><span>One click · applies next step</span></div>
            <div className="quick-events">
              <button disabled={!sim.simulationId || !openWaterways.length || eventBusy} onClick={() => void fireEvent(`Closed ${openWaterways[0]?.edge_id}`, "CLOSURE", { edge_id: openWaterways[0]?.edge_id })}>{eventBusy ? "Adding…" : `Close ${openWaterways[0]?.edge_id ?? "waterway"}`}</button>
              <button disabled={!sim.simulationId || !riskiestWaterway || eventBusy} onClick={() => riskiestWaterway && void fireEvent(`Flood risk rose on ${riskiestWaterway.edge_id}`, "FLOOD_RISE", { edge_ids: [riskiestWaterway.edge_id], risk_delta: 0.25 })}>{`Raise risk · ${riskiestWaterway?.edge_id ?? "waterway"}`}</button>
              <button disabled={!sim.simulationId || !incidentNode || eventBusy} onClick={() => incidentNode && void fireEvent(`Added ${nextIncidentId}`, "INCIDENT_ARRIVAL", { incident_id: nextIncidentId, node_id: incidentNode.node_id, urgency: 5, people: 2, required_capabilities: ["boat"] })}>Add high-risk rescue</button>
              <button disabled={!sim.simulationId || !acceptingShelters.length || eventBusy} onClick={() => acceptingShelters[0] && void fireEvent(`${acceptingShelters[0].shelter_id} marked full`, "SHELTER_OVERFLOW", { shelter_id: acceptingShelters[0].shelter_id })}>{`Fill ${acceptingShelters[0]?.shelter_id ?? "shelter"}`}</button>
              <button disabled={!sim.simulationId || !notFailedBoats.length || eventBusy} onClick={() => notFailedBoats[0] && void fireEvent(`${notFailedBoats[0].boat_id} breakdown`, "BOAT_FAILURE", { boat_id: notFailedBoats[0].boat_id })}>{`Break down ${notFailedBoats[0]?.boat_id ?? "boat"}`}</button>
              {primaryBoat && <button disabled={!sim.simulationId || eventBusy} onClick={() => void fireEvent(primaryBoatOffline ? `Radio restored for ${primaryBoat.boat_id}` : `Radio outage for ${primaryBoat.boat_id}`, primaryBoatOffline ? "PARTITION_HEAL" : "PARTITION_START", primaryBoatOffline ? { agent_id: primaryBoat.boat_id } : { agent_id: primaryBoat.boat_id, duration_ticks: 20 })}>{primaryBoatOffline ? `Restore radio Â· ${primaryBoat.boat_id}` : `Radio outage Â· ${primaryBoat.boat_id}`}</button>}
              {closedWaterways.length > 0 && <button disabled={!sim.simulationId || eventBusy} onClick={() => void fireEvent(`Reopened ${closedWaterways[0].edge_id}`, "EDGE_REOPEN", { edge_id: closedWaterways[0].edge_id })}>{`Reopen ${closedWaterways[0].edge_id}`}</button>}
            </div>
            {eventNotice && <p className="event-notice" role="status">{eventNotice}</p>}
            {!sim.simulationId && <p className="connection-note">Start a scenario to enable events.</p>}
          </section>
          <SyntheticMap
            world={sim.world}
            events={sim.events}
            tick={sim.tick}
            motionDurationMs={Math.round(sim.pollIntervalMs * 0.85)}
            selectedIncidentId={selectedIncident}
            selectedResourceId={null}
            disconnectedIds={sim.comms?.disconnected ?? []}
            selectedRouteEdgeIds={selectedRouteEdgeIds}
            changedRouteEdgeIds={activeRouteEdgeIds}
            onSelectIncident={setSelectedIncident}
            onSelectResource={selectResource}
          />
        </div>

        <aside className="side-column">
          <IncidentPanel incidents={sim.world.incidents} selectedId={selectedIncident} onSelect={setSelectedIncident} tick={sim.tick} />

          <section className="list-card boats-card">
            <div className="section-heading compact-heading"><div><h2>Boats</h2><p>Current location and assigned destination</p></div><span className="count-pill">{sim.world.boats.length}</span></div>
            <ul className="boat-list">
              {sim.world.boats.length ? sim.world.boats.map((boat) => {
                const assignment = sim.assignments.find((item) => item.resource_id === boat.boat_id && ["COMMITTED", "ACKNOWLEDGED", "IN_PROGRESS"].includes(item.status));
                const incident = assignment ? sim.world.incidents.find((item) => item.incident_id === assignment.incident_id) : null;
                const shelter = assignment?.shelter_id ? sim.world.shelters.find((item) => item.shelter_id === assignment.shelter_id) : null;
                const location = sim.world.nodes.find((node) => node.node_id === boat.node_id);
                const destination = incident ? `${sim.world.nodes.find((node) => node.node_id === incident.node_id)?.neighborhood ?? incident.node_id} rescue${shelter ? ` \u2192 ${shelter.shelter_id}` : ""}` : "No active destination";
                return <li key={boat.boat_id}><span className="boat-icon">B</span><span className="row-main"><strong>{boat.boat_id} <span className={`boat-status boat-${boat.status.toLowerCase()}`}>{prettyStatus(boat.status)}</span></strong><small>From: {location?.neighborhood ?? boat.node_id} ({boat.node_id})</small><small>To: {destination}</small></span></li>;
              }) : <li className="empty-state">No boats in this run</li>}
            </ul>
          </section>

          <section className="list-card shelter-card">
            <div className="section-heading compact-heading"><div><h2>Shelters</h2><p>People housed / total spaces</p></div></div>
            <ul className="shelter-list">
              {sim.world.shelters.map((shelter) => {
                const reserved = Object.values(shelter.reservations).reduce((sum, value) => sum + value, 0);
                const place = sim.world.nodes.find((node) => node.node_id === shelter.node_id);
                return <li key={shelter.shelter_id}><span className="shelter-icon">+</span><span className="row-main"><strong>{shelter.shelter_id}</strong><small>{place?.neighborhood ?? shelter.node_id}{" · "}{shelter.accepting ? "Accepting people" : "Full or closed"}</small><span className="capacity-track"><i style={{ width: `${Math.min(100, shelter.capacity ? shelter.occupancy / shelter.capacity * 100 : 0)}%` }} /></span><small>{reserved} reserved</small></span><span className="capacity-label"><strong>{shelter.occupancy}</strong><span> / {shelter.capacity}<br />occupied</span></span></li>;
              })}
            </ul>
          </section>

          {!sim.backendReachable && <p className="connection-note">Showing sample data. Start the backend to run a live simulation.</p>}
        </aside>
      </section>



      <section className="panel-grid" aria-label="Detail panels">
        <TimelinePanel
          events={sim.events}
          tick={sim.tick}
          maxTick={Math.max(sim.tick, ...sim.snapshots, 60)}
          scrubTick={scrubTick}
          onScrub={setScrubTick}
          onPickEvent={pickTimelineEvent}
        />
        <ExplanationPanel
          assignments={sim.assignments}
          events={sim.events}
          selectedId={selectedAssignment}
          onSelect={setSelectedAssignment}
        />
        <CommunicationsPanel comms={sim.comms} />
        <MetricsPanel
          metrics={sim.metrics}
          compareA={compareA}
          compareB={compareB}
          onCompareLoaded={(a, b) => { setCompareA(a); setCompareB(b); }}
          liveStrategy={sim.strategy}
        />
      </section>

      <footer className="demo-footer">Deterministic ticks only · synthetic data · lifecycle PROPOSED→COMMITTED→ACKNOWLEDGED→IN_PROGRESS→COMPLETED</footer>
    </main>
  );
}
