/** Shared shapes mirroring backend Pydantic schemas (world.py, scheduler_interface.py, communications/models.py). */

export type EdgeStatus = "open" | "closed" | "disputed";
export type EdgeMode = "road" | "water";
export type IncidentStatus = "OPEN" | "ASSIGNED" | "IN_PROGRESS" | "SERVED" | "CANCELLED" | "UNRESOLVED";
export type BoatStatus =
  | "AVAILABLE" | "ASSIGNED" | "EN_ROUTE_TO_INCIDENT" | "RESCUING"
  | "TRANSPORTING_TO_SHELTER" | "RECOVERY" | "UNAVAILABLE" | "FAILED"
  | "STRANDED" | "RETURNING" | "MAINTENANCE";
export type GroundTeamStatus = "AVAILABLE" | "ASSIGNED" | "ON_SCENE" | "RETURNING" | "UNAVAILABLE";
export type AssignmentStatus =
  | "PROPOSED" | "COMMITTED" | "ACKNOWLEDGED" | "IN_PROGRESS" | "COMPLETED"
  | "REJECTED" | "EXPIRED" | "CANCELLED" | "REQUIRES_RECONCILIATION";
export type Strategy = "centralized" | "negotiation";

export interface MapNode {
  node_id: string;
  neighborhood: string;
  kind: "intersection" | "incident_site" | "shelter" | "station" | "transfer";
  x: number;
  y: number;
}

export interface Edge {
  edge_id: string;
  from_node: string;
  to_node: string;
  mode: EdgeMode;
  travel_time: number;
  status: EdgeStatus;
  risk_level: number;
  capacity: number;
  last_updated_tick: number;
}

export interface Incident {
  incident_id: string;
  node_id: string;
  urgency: number;
  people: number;
  required_capabilities: string[];
  created_tick: number;
  status: IncidentStatus;
  report_confidence: number;
  kind: "standard" | "recovery";
  caused_by?: string | null;
}

export interface Boat {
  boat_id: string;
  node_id: string;
  capacity: number;
  fuel: number;
  fuel_reserve: number;
  speed: number;
  status: BoatStatus;
  assignment_id?: string | null;
  passengers: number;
  needs_recovery: boolean;
  history: Record<string, unknown>[];
}

export interface GroundTeam {
  team_id: string;
  node_id: string;
  capabilities: string[];
  status: GroundTeamStatus;
  assignment_id?: string | null;
  history: Record<string, unknown>[];
}

export interface Shelter {
  shelter_id: string;
  node_id: string;
  capacity: number;
  occupancy: number;
  reservations: Record<string, number>;
  accepting: boolean;
  history: Record<string, unknown>[];
}

export interface WorldState {
  nodes: MapNode[];
  edges: Edge[];
  incidents: Incident[];
  boats: Boat[];
  teams: GroundTeam[];
  shelters: Shelter[];
}

export interface AssignmentHistoryEntry {
  tick: number;
  from?: string;
  to?: string;
  reason: string;
  actor: string;
}

export interface Assignment {
  assignment_id: string;
  version: number;
  proposal_id: string;
  incident_id: string;
  resource_id: string;
  resource_kind: "boat" | "team";
  shelter_id?: string | null;
  seats: number;
  route_edge_ids: string[];
  status: AssignmentStatus;
  cost: number;
  created_tick: number;
  history: AssignmentHistoryEntry[];
}

export interface ProposedAssignment {
  proposal_id: string;
  incident_id: string;
  resource_id: string;
  resource_kind: "boat" | "team";
  shelter_id?: string | null;
  seats: number;
  route_edge_ids: string[];
  eta_ticks: number;
  cost: number;
  reasons: string[];
  created_tick: number;
}

export interface SimEvent {
  tick: number;
  kind: string;
  actor: string;
  detail: Record<string, unknown>;
}

export interface SimulationMetrics {
  ticks: number;
  strategy: string;
  served: number;
  unserved: number;
  committed: number;
  rejected_by_reason: Record<string, number>;
  extra?: Record<string, number>;
}

export type CommsMessageStatus = "QUEUED" | "DELIVERED" | "ACKED" | "EXPIRED" | "RETRY" | "DROPPED";

export interface CommsMessage {
  message_id: string;
  type: string;
  sender_id: string;
  recipient_id: string;
  created_at_tick: number;
  expires_at_tick: number;
  status: CommsMessageStatus;
  retries?: number;
  detail?: Record<string, unknown>;
}

export interface CommsState {
  tick: number;
  connected: string[];
  disconnected: string[];
  queue: CommsMessage[];
  messages: CommsMessage[];
  reconciliation_log: { tick: number; agent_id: string; status: string; detail: string }[];
  partitions: { agent_id: string; from_tick: number; to_tick?: number | null }[];
}

export interface CreateSimulationInput {
  /** Scenario file name (e.g. "baseline") or an inline scenario document. */
  scenario?: string | Record<string, unknown>;
  scenario_name?: string;
  strategy: Strategy;
  seed?: number;
  ticks?: number;
}
