/**
 * Synthetic demo fallback so the dashboard renders with zero backend.
 * Coordinates mirror scenarios/baseline.json (x in 0..6, y in 0..7).
 * Clearly labeled DEMO in the UI; replaced by live data when reachable.
 */
import type { CommsState, SimulationMetrics, WorldState } from "../types";
import type { Assignment, SimEvent } from "../types";

export const DEMO_WORLD: WorldState = {
  nodes: [
    { node_id: "N-01", neighborhood: "Riverside", kind: "station", x: 0, y: 0 },
    { node_id: "N-02", neighborhood: "Riverside", kind: "transfer", x: 2, y: 0 },
    { node_id: "N-03", neighborhood: "Riverside", kind: "incident_site", x: 4, y: 0 },
    { node_id: "N-04", neighborhood: "Riverside", kind: "incident_site", x: 6, y: 0 },
    { node_id: "N-05", neighborhood: "Old Town", kind: "station", x: 0, y: 2 },
    { node_id: "N-06", neighborhood: "Old Town", kind: "intersection", x: 2, y: 2 },
    { node_id: "N-07", neighborhood: "Old Town", kind: "incident_site", x: 4, y: 2 },
    { node_id: "N-08", neighborhood: "Old Town", kind: "incident_site", x: 6, y: 2 },
    { node_id: "N-09", neighborhood: "Marshgate", kind: "transfer", x: 0, y: 4 },
    { node_id: "N-10", neighborhood: "Marshgate", kind: "incident_site", x: 2, y: 4 },
    { node_id: "N-11", neighborhood: "Marshgate", kind: "incident_site", x: 4, y: 4 },
    { node_id: "N-12", neighborhood: "Marshgate", kind: "incident_site", x: 6, y: 4 },
    { node_id: "N-13", neighborhood: "Hillcrest", kind: "station", x: 0, y: 6 },
    { node_id: "N-14", neighborhood: "Hillcrest", kind: "intersection", x: 2, y: 6 },
    { node_id: "N-15", neighborhood: "Hillcrest", kind: "transfer", x: 4, y: 6 },
    { node_id: "N-16", neighborhood: "Hillcrest", kind: "incident_site", x: 6, y: 6 },
    { node_id: "N-17", neighborhood: "Riverside", kind: "incident_site", x: 1, y: 1 },
    { node_id: "N-18", neighborhood: "Old Town", kind: "incident_site", x: 5, y: 3 },
    { node_id: "N-19", neighborhood: "Marshgate", kind: "incident_site", x: 1, y: 5 },
    { node_id: "N-20", neighborhood: "Hillcrest", kind: "incident_site", x: 5, y: 7 },
    { node_id: "N-21", neighborhood: "Riverside", kind: "shelter", x: 5, y: 1 },
    { node_id: "N-22", neighborhood: "Old Town", kind: "shelter", x: 1, y: 3 },
    { node_id: "N-23", neighborhood: "Marshgate", kind: "shelter", x: 3, y: 5 },
    { node_id: "N-24", neighborhood: "Hillcrest", kind: "shelter", x: 4, y: 7 },
    { node_id: "N-25", neighborhood: "Marshgate", kind: "intersection", x: 5, y: 5 },
  ],
  edges: [
    { edge_id: "R-11", from_node: "N-10", to_node: "N-06", mode: "road", travel_time: 2, status: "closed", risk_level: 0.2, capacity: 2, last_updated_tick: 40 },
    { edge_id: "R-05", from_node: "N-06", to_node: "N-07", mode: "road", travel_time: 1, status: "open", risk_level: 0.2, capacity: 2, last_updated_tick: 0 },
    { edge_id: "R-06", from_node: "N-07", to_node: "N-08", mode: "road", travel_time: 2, status: "disputed", risk_level: 0.3, capacity: 1, last_updated_tick: 38 },
    { edge_id: "W-02", from_node: "N-02", to_node: "N-03", mode: "water", travel_time: 1, status: "open", risk_level: 0.2, capacity: 1, last_updated_tick: 0 },
    { edge_id: "W-03", from_node: "N-03", to_node: "N-04", mode: "water", travel_time: 2, status: "open", risk_level: 0.3, capacity: 1, last_updated_tick: 0 },
    { edge_id: "W-06", from_node: "N-18", to_node: "N-11", mode: "water", travel_time: 2, status: "open", risk_level: 0.3, capacity: 2, last_updated_tick: 0 },
    { edge_id: "W-11", from_node: "N-04", to_node: "N-12", mode: "water", travel_time: 3, status: "open", risk_level: 0.5, capacity: 1, last_updated_tick: 0 },
    { edge_id: "W-17", from_node: "N-23", to_node: "N-11", mode: "water", travel_time: 2, status: "open", risk_level: 0.3, capacity: 2, last_updated_tick: 0 },
  ],
  incidents: [
    { incident_id: "INC-03", node_id: "N-07", urgency: 5, people: 4, required_capabilities: ["ground"], created_tick: 2, status: "ASSIGNED", report_confidence: 1, kind: "standard", caused_by: null },
    { incident_id: "INC-08", node_id: "N-18", urgency: 5, people: 4, required_capabilities: ["boat"], created_tick: 12, status: "IN_PROGRESS", report_confidence: 1, kind: "standard", caused_by: null },
    { incident_id: "INC-05", node_id: "N-12", urgency: 4, people: 5, required_capabilities: ["boat"], created_tick: 6, status: "OPEN", report_confidence: 0.6, kind: "standard", caused_by: null },
  ],
  boats: [
    { boat_id: "BOAT-01", node_id: "N-03", capacity: 5, fuel: 52, fuel_reserve: 10, speed: 1, status: "EN_ROUTE_TO_INCIDENT", assignment_id: "ASN-00001", passengers: 0, needs_recovery: false, history: [] },
    { boat_id: "BOAT-02", node_id: "N-11", capacity: 5, fuel: 44, fuel_reserve: 10, speed: 1, status: "FAILED", assignment_id: null, passengers: 2, needs_recovery: true, history: [] },
    { boat_id: "BOAT-03", node_id: "N-02", capacity: 4, fuel: 60, fuel_reserve: 10, speed: 1, status: "AVAILABLE", assignment_id: null, passengers: 0, needs_recovery: false, history: [] },
  ],
  teams: [
    { team_id: "TEAM-01", node_id: "N-07", capabilities: ["ground"], status: "ON_SCENE", assignment_id: "ASN-00002", history: [] },
    { team_id: "TEAM-02", node_id: "N-05", capabilities: ["ground"], status: "AVAILABLE", assignment_id: null, history: [] },
  ],
  shelters: [
    { shelter_id: "SHELTER-01", node_id: "N-21", capacity: 10, occupancy: 4, reservations: { "ASN-00001": 3 }, accepting: true, history: [] },
    { shelter_id: "SHELTER-02", node_id: "N-22", capacity: 8, occupancy: 8, reservations: {}, accepting: false, history: [] },
  ],
};

export const DEMO_ASSIGNMENTS: Assignment[] = [
  {
    assignment_id: "ASN-00001",
    version: 1,
    proposal_id: "PROP-00001",
    incident_id: "INC-08",
    resource_id: "BOAT-01",
    resource_kind: "boat",
    shelter_id: "SHELTER-01",
    seats: 3,
    route_edge_ids: ["W-02", "W-06"],
    status: "IN_PROGRESS",
    cost: 7.4,
    created_tick: 12,
    history: [
      { tick: 12, from: "PROPOSED", to: "COMMITTED", reason: "commit ASN-00001 BOAT-01->INC-08", actor: "dispatch" },
      { tick: 13, from: "COMMITTED", to: "ACKNOWLEDGED", reason: "acknowledged", actor: "BOAT-01" },
      { tick: 14, from: "ACKNOWLEDGED", to: "IN_PROGRESS", reason: "started", actor: "BOAT-01" },
    ],
  },
  {
    assignment_id: "ASN-00002",
    version: 2,
    proposal_id: "PROP-00007",
    incident_id: "INC-03",
    resource_id: "TEAM-01",
    resource_kind: "team",
    shelter_id: null,
    seats: 4,
    route_edge_ids: ["R-05"],
    status: "IN_PROGRESS",
    cost: 5.1,
    created_tick: 4,
    history: [
      { tick: 4, from: "PROPOSED", to: "COMMITTED", reason: "commit ASN-00002 TEAM-01->INC-03", actor: "dispatch" },
      { tick: 40, from: "R-11", to: "R-05", reason: "SHELTER_FULL reassigned SHELTER-02->SHELTER-01", actor: "dispatch" },
    ],
  },
  {
    assignment_id: "ASN-00003",
    version: 1,
    proposal_id: "PROP-00009",
    incident_id: "INC-05",
    resource_id: "BOAT-02",
    resource_kind: "boat",
    shelter_id: "SHELTER-01",
    seats: 5,
    route_edge_ids: ["W-11"],
    status: "CANCELLED",
    cost: 9.9,
    created_tick: 20,
    history: [
      { tick: 20, from: "PROPOSED", to: "COMMITTED", reason: "commit ASN-00003 BOAT-02->INC-05", actor: "dispatch" },
      { tick: 33, from: "IN_PROGRESS", to: "CANCELLED", reason: "CANCELLED:RESOURCE_FAILED", actor: "dispatch" },
      { tick: 33, from: "CANCELLED", to: "CANCELLED", reason: "REPLAN_CHAIN ASN-00003->REC-BOAT-02-0033", actor: "dispatch" },
    ],
  },
];

export const DEMO_EVENTS: SimEvent[] = [
  { tick: 25, kind: "INCIDENT_ARRIVAL", actor: "sim", detail: { incident_id: "INC-13", node_id: "N-14" } },
  { tick: 33, kind: "BOAT_FAILED", actor: "dispatch", detail: { boat_id: "BOAT-02", assignment_id: "ASN-00003" } },
  { tick: 33, kind: "RECOVERY_TRIGGERED", actor: "dispatch", detail: { incident_id: "REC-BOAT-02-0033", caused_by: "ASN-00003" } },
  { tick: 38, kind: "EDGE_DISPUTED", actor: "reports", detail: { edge_id: "R-06", reports: ["RPT-017:CLOSED", "RPT-018:OPEN"] } },
  { tick: 40, kind: "EDGE_CLOSED", actor: "sim", detail: { edge_id: "R-11", reason: "bridge closure" } },
  { tick: 40, kind: "REJECTED", actor: "dispatch", detail: { proposal_id: "PROP-00011", reason: "EDGE_CLOSED:R-11" } },
  { tick: 41, kind: "COMMITTED", actor: "dispatch", detail: { assignment_id: "ASN-00002", note: "rerouted via R-05" } },
  { tick: 45, kind: "PARTITION_START", actor: "network", detail: { agent_id: "BOAT-03", until_tick: 60 } },
  { tick: 60, kind: "RECONCILED", actor: "gateway", detail: { agent_id: "BOAT-03", status: "STALE_ROUTE", note: "re-acked after heal" } },
];

export const DEMO_METRICS: SimulationMetrics = {
  ticks: 60,
  strategy: "centralized (demo)",
  served: 9,
  unserved: 3,
  committed: 12,
  rejected_by_reason: { "EDGE_CLOSED:R-11": 2, "RESOURCE_CONFLICT:WINNER=PROP-00007": 1, "SHELTER_FULL_AT_COMMIT": 1 },
  extra: { avg_service_time: 14.2, unmet: 3, idle: 6, violations: 0, fairness_gap: 1.8, recovery_time: 9, latency: 2 },
};

export const DEMO_COMMS: CommsState = {
  tick: 60,
  connected: ["BOAT-01", "BOAT-02", "TEAM-01", "TEAM-02"],
  disconnected: ["BOAT-03"],
  queue: [
    { message_id: "MSG-00142", type: "ASSIGNMENT_OFFER", sender_id: "DISPATCH-01", recipient_id: "BOAT-03", created_at_tick: 58, expires_at_tick: 68, status: "QUEUED", retries: 2, detail: {} },
  ],
  messages: [
    { message_id: "MSG-00139", type: "BOAT_POSITION", sender_id: "BOAT-01", recipient_id: "DISPATCH-01", created_at_tick: 57, expires_at_tick: 67, status: "ACKED", detail: {} },
    { message_id: "MSG-00140", type: "HAZARD_REPORTED", sender_id: "TEAM-01", recipient_id: "DISPATCH-01", created_at_tick: 56, expires_at_tick: 66, status: "DELIVERED", detail: {} },
    { message_id: "MSG-00138", type: "ASSIGNMENT_OFFER", sender_id: "DISPATCH-01", recipient_id: "BOAT-03", created_at_tick: 44, expires_at_tick: 50, status: "EXPIRED", retries: 3, detail: {} },
  ],
  reconciliation_log: [
    { tick: 60, agent_id: "BOAT-03", status: "STALE_ROUTE", detail: "re-acked after heal; stale-route warning issued" },
  ],
  partitions: [{ agent_id: "BOAT-03", from_tick: 45, to_tick: 60 }],
};
