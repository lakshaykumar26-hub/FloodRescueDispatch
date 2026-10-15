/**
 * Typed fetch client for the Flood Rescue Dispatch REST + WS API.
 *
 * All field-name adaptation lives here (normalizers): components consume
 * the canonical shapes from `types/index.ts` only. Unknown/extra backend
 * fields are tolerated; missing fields fall back to safe defaults so the
 * dashboard renders a "backend unreachable / degraded" state instead of
 * crashing when the backend is built in parallel.
 */
import type {
  Assignment,
  AssignmentHistoryEntry,
  Boat,
  CommsMessage,
  CommsState,
  CreateSimulationInput,
  Edge,
  GroundTeam,
  Incident,
  MapNode,
  Shelter,
  SimEvent,
  SimulationMetrics,
  WorldState,
} from "../types";

export function apiBase(): string {
  const raw = process.env.NEXT_PUBLIC_API_URL;
  if (raw && raw.trim().length > 0) return raw.replace(/\/+$/, "");
  return "http://localhost:8000";
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${apiBase()}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`API ${res.status} ${path}: ${text.slice(0, 200)}`);
  }
  return (await res.json()) as T;
}

/** Backend may send dicts keyed by id (Pydantic World) or arrays. Accept both. */
function asArray<T>(v: unknown): T[] {
  if (Array.isArray(v)) return v as T[];
  if (v && typeof v === "object") return Object.values(v as Record<string, T>);
  return [];
}

function num(v: unknown, dflt = 0): number {
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? (n as number) : dflt;
}

function str(v: unknown, dflt = ""): string {
  return typeof v === "string" ? v : dflt;
}

function normalizeNode(r: Record<string, unknown>): MapNode {
  return {
    node_id: str(r.node_id ?? r.id),
    neighborhood: str(r.neighborhood, "—"),
    kind: (r.kind as MapNode["kind"]) ?? "intersection",
    x: num(r.x),
    y: num(r.y),
  };
}

function normalizeEdge(r: Record<string, unknown>): Edge {
  return {
    edge_id: str(r.edge_id ?? r.id),
    from_node: str(r.from_node ?? r.from),
    to_node: str(r.to_node ?? r.to),
    mode: (r.mode as Edge["mode"]) ?? "road",
    travel_time: num(r.travel_time, 1),
    status: (r.status as Edge["status"]) ?? "open",
    risk_level: num(r.risk_level),
    capacity: num(r.capacity, 1),
    last_updated_tick: num(r.last_updated_tick ?? r.updated_tick),
  };
}

function normalizeIncident(r: Record<string, unknown>): Incident {
  return {
    incident_id: str(r.incident_id ?? r.id),
    node_id: str(r.node_id ?? r.node),
    urgency: num(r.urgency, 1),
    people: num(r.people, 1),
    required_capabilities: Array.isArray(r.required_capabilities) ? (r.required_capabilities as string[]) : [],
    created_tick: num(r.created_tick),
    status: (r.status as Incident["status"]) ?? "OPEN",
    report_confidence: typeof r.report_confidence === "number" ? (r.report_confidence as number) : 1,
    kind: (r.kind as Incident["kind"]) ?? "standard",
    caused_by: typeof r.caused_by === "string" ? (r.caused_by as string) : null,
  };
}

function normalizeBoat(r: Record<string, unknown>): Boat {
  return {
    boat_id: str(r.boat_id ?? r.id ?? r.resource_id),
    node_id: str(r.node_id ?? r.node),
    capacity: num(r.capacity, 1),
    fuel: num(r.fuel),
    fuel_reserve: num(r.fuel_reserve),
    speed: num(r.speed, 1),
    status: (r.status as Boat["status"]) ?? "AVAILABLE",
    assignment_id: typeof r.assignment_id === "string" ? (r.assignment_id as string) : null,
    passengers: num(r.passengers),
    needs_recovery: r.needs_recovery === true,
    history: Array.isArray(r.history) ? (r.history as Record<string, unknown>[]) : [],
  };
}

function normalizeTeam(r: Record<string, unknown>): GroundTeam {
  return {
    team_id: str(r.team_id ?? r.id ?? r.resource_id),
    node_id: str(r.node_id ?? r.node),
    capabilities: Array.isArray(r.capabilities) ? (r.capabilities as string[]) : [],
    status: (r.status as GroundTeam["status"]) ?? "AVAILABLE",
    assignment_id: typeof r.assignment_id === "string" ? (r.assignment_id as string) : null,
    history: Array.isArray(r.history) ? (r.history as Record<string, unknown>[]) : [],
  };
}

function normalizeShelter(r: Record<string, unknown>): Shelter {
  const res = r.reservations;
  const reservations: Record<string, number> = {};
  if (res && typeof res === "object" && !Array.isArray(res)) {
    for (const [k, v] of Object.entries(res as Record<string, unknown>)) reservations[k] = num(v);
  }
  return {
    shelter_id: str(r.shelter_id ?? r.id),
    node_id: str(r.node_id ?? r.node),
    capacity: num(r.capacity, 1),
    occupancy: num(r.occupancy),
    reservations,
    accepting: r.accepting !== false,
    history: Array.isArray(r.history) ? (r.history as Record<string, unknown>[]) : [],
  };
}

export function normalizeWorld(raw: unknown): WorldState {
  const r = (raw ?? {}) as Record<string, unknown>;
  const world = (r.world ?? r) as Record<string, unknown>;
  return {
    nodes: asArray<Record<string, unknown>>(world.nodes).map(normalizeNode),
    edges: asArray<Record<string, unknown>>(world.edges).map(normalizeEdge),
    incidents: asArray<Record<string, unknown>>(world.incidents).map(normalizeIncident),
    boats: asArray<Record<string, unknown>>(world.boats).map(normalizeBoat),
    teams: asArray<Record<string, unknown>>(world.teams).map(normalizeTeam),
    shelters: asArray<Record<string, unknown>>(world.shelters).map(normalizeShelter),
  };
}

export function normalizeEvents(raw: unknown): SimEvent[] {
  const r = (raw ?? {}) as Record<string, unknown>;
  const list = asArray<Record<string, unknown>>(r.events ?? raw);
  return list.map((e) => ({
    tick: num(e.tick),
    kind: str(e.kind ?? e.type, "UNKNOWN"),
    actor: str(e.actor ?? e.sender_id, "sim"),
    detail: (e.detail && typeof e.detail === "object" ? e.detail : { ...e }) as Record<string, unknown>,
  }));
}

export function normalizeAssignments(raw: unknown): { assignments: Assignment[]; history: AssignmentHistoryEntry[] } {
  const r = (raw ?? {}) as Record<string, unknown>;
  const list = asArray<Record<string, unknown>>(r.assignments ?? raw);
  const assignments: Assignment[] = list.map((a) => ({
    assignment_id: str(a.assignment_id ?? a.id),
    version: num(a.version, 1),
    proposal_id: str(a.proposal_id),
    incident_id: str(a.incident_id),
    resource_id: str(a.resource_id),
    resource_kind: (a.resource_kind as Assignment["resource_kind"]) ?? "boat",
    shelter_id: typeof a.shelter_id === "string" ? (a.shelter_id as string) : null,
    seats: num(a.seats),
    route_edge_ids: Array.isArray(a.route_edge_ids) ? (a.route_edge_ids as string[]) : [],
    status: (a.status as Assignment["status"]) ?? "COMMITTED",
    cost: num(a.cost),
    created_tick: num(a.created_tick),
    history: Array.isArray(a.history) ? (a.history as AssignmentHistoryEntry[]) : [],
  }));
  const history = asArray<AssignmentHistoryEntry>(r.history).map((h) => ({
    tick: num((h as unknown as Record<string, unknown>).tick),
    from: str((h as unknown as Record<string, unknown>).from),
    to: str((h as unknown as Record<string, unknown>).to),
    reason: str((h as unknown as Record<string, unknown>).reason, "—"),
    actor: str((h as unknown as Record<string, unknown>).actor, "sim"),
  }));
  return { assignments, history };
}

export function normalizeMetrics(raw: unknown): SimulationMetrics {
  const r = (raw ?? {}) as Record<string, unknown>;
  const m = (r.metrics ?? r) as Record<string, unknown>;
  const rejected = (m.rejected_by_reason ?? m.rejected ?? {}) as Record<string, unknown>;
  const rejected_by_reason: Record<string, number> = {};
  if (rejected && typeof rejected === "object") {
    for (const [k, v] of Object.entries(rejected)) rejected_by_reason[k] = num(v);
  }
  const extra: Record<string, number> = {};
  for (const k of ["avg_service_time", "unmet", "idle", "violations", "fairness_gap", "recovery_time", "latency"]) {
    if (typeof m[k] === "number") extra[k] = m[k] as number;
  }
  return {
    ticks: num(m.ticks ?? m.tick),
    strategy: str(m.strategy, "—"),
    served: num(m.served),
    unserved: num(m.unserved ?? m.unresolved),
    committed: num(m.committed),
    rejected_by_reason,
    extra,
  };
}

function normalizeCommsMessage(r: Record<string, unknown>): CommsMessage {
  const statusRaw = str(r.status ?? r.delivery_status, "QUEUED").toUpperCase();
  const status = (["QUEUED", "DELIVERED", "ACKED", "EXPIRED", "RETRY", "DROPPED"] as string[]).includes(statusRaw)
    ? (statusRaw as CommsMessage["status"])
    : "QUEUED";
  return {
    message_id: str(r.message_id ?? r.id),
    type: str(r.type, "UNKNOWN"),
    sender_id: str(r.sender_id ?? r.sender),
    recipient_id: str(r.recipient_id ?? r.recipient),
    created_at_tick: num(r.created_at_tick ?? r.tick),
    expires_at_tick: num(r.expires_at_tick ?? r.created_at_tick, num(r.created_at_tick)),
    status,
    retries: typeof r.retries === "number" ? (r.retries as number) : undefined,
    detail: (r.payload && typeof r.payload === "object" ? r.payload : {}) as Record<string, unknown>,
  };
}

export function normalizeComms(raw: unknown): CommsState {
  const r = (raw ?? {}) as Record<string, unknown>;
  const queue = asArray<Record<string, unknown>>(r.queue).map(normalizeCommsMessage);
  const messages = asArray<Record<string, unknown>>(r.messages ?? r.delivered).map(normalizeCommsMessage);
  const connected = Array.isArray(r.connected) ? (r.connected as string[]) : [];
  const disconnected = Array.isArray(r.disconnected) ? (r.disconnected as string[]) : [];
  const partitionsRaw = asArray<Record<string, unknown>>(r.partitions);
  const recRaw = asArray<Record<string, unknown>>(r.reconciliation_log ?? r.reconciliation);
  return {
    tick: num(r.tick),
    connected,
    disconnected,
    queue,
    messages,
    reconciliation_log: recRaw.map((e) => ({
      tick: num(e.tick),
      agent_id: str(e.agent_id ?? e.agent),
      status: str(e.status, "—"),
      detail: str(e.detail ?? e.reason, "—"),
    })),
    partitions: partitionsRaw.map((p) => ({
      agent_id: str(p.agent_id ?? p.boat_id ?? p.agent),
      from_tick: num(p.from_tick ?? p.from),
      to_tick: typeof p.to_tick === "number" ? (p.to_tick as number) : null,
    })),
  };
}

// ---- REST calls (match the Phase 6 API contract exactly) ----

/** Lightweight liveness probe for the mount-time badge. Never throws. */
export async function checkBackend(timeoutMs = 3000): Promise<boolean> {
  try {
    const res = await fetch(`${apiBase()}/health`, {
      signal: AbortSignal.timeout(timeoutMs),
    });
    return res.ok;
  } catch {
    return false;
  }
}

export interface CreateSimResponse {
  simulation_id: string;
  tick: number;
  status: string;
  strategy: string;
  seed: number;
}

export async function createSimulation(input: CreateSimulationInput): Promise<CreateSimResponse> {
  const body: Record<string, unknown> = {
    strategy: input.strategy,
    seed: input.seed ?? 42,
    ticks: input.ticks ?? 120,
  };
  if (input.scenario !== undefined && typeof input.scenario !== "string") {
    // Inline scenario document — backend uses it directly.
    body.scenario = input.scenario;
    if (input.scenario_name) body.scenario_name = input.scenario_name;
  } else {
    // Name only. Never send `scenario` as a string: older backends validate
    // it as a dict and 422 the whole request (dict_type at body.scenario).
    body.scenario_name = input.scenario_name ?? input.scenario ?? "baseline";
  }
  const raw = await req<Record<string, unknown>>("/api/simulations", {
    method: "POST",
    body: JSON.stringify(body),
  });
  return {
    simulation_id: str(raw.simulation_id ?? raw.id, "SIM-001"),
    tick: num(raw.tick),
    status: str(raw.status, "created"),
    strategy: str(raw.strategy, input.strategy),
    seed: num(raw.seed, input.seed ?? 42),
  };
}

export interface SimControlResponse {
  simulation_id: string;
  tick: number;
  status: string;
}

async function control(path: string, body?: Record<string, unknown>): Promise<SimControlResponse> {
  const raw = await req<Record<string, unknown>>(path, {
    method: "POST",
    body: JSON.stringify(body ?? {}),
  });
  return {
    simulation_id: str(raw.simulation_id ?? raw.id),
    tick: num(raw.tick),
    status: str(raw.status, "unknown"),
  };
}

export const startSimulation = (id: string) => control(`/api/simulations/${id}/start`);
export const pauseSimulation = (id: string) => control(`/api/simulations/${id}/pause`);
export const stepSimulation = (id: string, steps = 1) =>
  control(`/api/simulations/${id}/step`, { steps });

export async function getState(id: string): Promise<{ tick: number; status: string; world: WorldState; snapshots: number[] }> {
  const raw = await req<Record<string, unknown>>(`/api/simulations/${id}/state`);
  const r = raw as Record<string, unknown>;
  return {
    tick: num(r.tick),
    status: str(r.status, "unknown"),
    world: normalizeWorld(r.world ?? raw),
    snapshots: Array.isArray(r.snapshots) ? (r.snapshots as number[]) : [],
  };
}

export async function getEvents(id: string, sinceTick = 0, kind?: string): Promise<SimEvent[]> {
  const q = new URLSearchParams({ since_tick: String(sinceTick) });
  if (kind) q.set("kind", kind);
  const raw = await req<unknown>(`/api/simulations/${id}/events?${q.toString()}`);
  return normalizeEvents(raw);
}

export async function getAssignments(id: string) {
  const raw = await req<unknown>(`/api/simulations/${id}/assignments`);
  return normalizeAssignments(raw);
}

export async function getMetrics(id: string): Promise<SimulationMetrics> {
  const raw = await req<unknown>(`/api/simulations/${id}/metrics`);
  return normalizeMetrics(raw);
}

export async function getCommunications(id: string): Promise<CommsState> {
  const raw = await req<unknown>(`/api/simulations/${id}/communications`);
  return normalizeComms(raw);
}

export async function injectEvent(
  id: string,
  evt: { kind: string; payload: Record<string, unknown>; event_id?: string; tick?: number },
): Promise<{ event_id: string; tick: number }> {
  const raw = await req<Record<string, unknown>>(`/api/simulations/${id}/events`, {
    method: "POST",
    body: JSON.stringify(evt),
  });
  return { event_id: str(raw.event_id), tick: num(raw.tick) };
}

export async function replaySimulation(id: string, fromSnapshotTick?: number) {
  const raw = await req<Record<string, unknown>>(`/api/simulations/${id}/replay`, {
    method: "POST",
    body: JSON.stringify(fromSnapshotTick !== undefined ? { from_snapshot_tick: fromSnapshotTick } : {}),
  });
  return {
    simulation_id: str(raw.simulation_id ?? raw.id, id),
    tick: num(raw.tick),
    summary: (raw.summary ?? raw) as Record<string, unknown>,
  };
}

// ---- WebSocket helper ----

export interface WsServerMessage {
  tick: number;
  state_digest?: Record<string, unknown>;
  events?: SimEvent[];
  assignments_delta?: Assignment[];
  comms_digest?: Record<string, unknown>;
}

export function wsUrl(simulationId: string): string {
  const base = apiBase().replace(/^http/, "ws");
  return `${base}/ws/simulations/${simulationId}`;
}

/** Subscribe to the sim WS feed. Returns an unsubscribe function. Never throws on connect. */
export function subscribeSimulation(
  simulationId: string,
  onMessage: (msg: WsServerMessage) => void,
  onStatus?: (connected: boolean) => void,
): () => void {
  let ws: WebSocket | null = null;
  let closed = false;
  try {
    ws = new WebSocket(wsUrl(simulationId));
  } catch {
    onStatus?.(false);
    return () => {};
  }
  ws.onopen = () => onStatus?.(true);
  ws.onclose = () => {
    if (!closed) onStatus?.(false);
  };
  ws.onerror = () => onStatus?.(false);
  ws.onmessage = (ev: MessageEvent) => {
    try {
      const raw = JSON.parse(String(ev.data)) as Record<string, unknown>;
      onMessage({
        tick: num(raw.tick),
        state_digest: (raw.state_digest ?? raw.state) as Record<string, unknown> | undefined,
        events: raw.events ? normalizeEvents({ events: raw.events }) : undefined,
        assignments_delta: Array.isArray(raw.assignments_delta)
          ? normalizeAssignments({ assignments: raw.assignments_delta }).assignments
          : undefined,
        comms_digest: (raw.comms_digest ?? raw.comms) as Record<string, unknown> | undefined,
      });
    } catch {
      // Ignore malformed frames; polling covers gaps.
    }
  };
  return () => {
    closed = true;
    try {
      ws?.close();
    } catch {
      // Already closed.
    }
  };
}

export function sendWsAction(simulationId: string, action: "pause" | "step" | "inject", extra?: Record<string, unknown>): void {
  // Best-effort control over an ad-hoc socket; the hook keeps a single
  // shared socket for streaming and uses REST for control, so this opens
  // a transient socket only when explicitly asked.
  try {
    const ws = new WebSocket(wsUrl(simulationId));
    ws.onopen = () => {
      ws.send(JSON.stringify({ action, ...(extra ?? {}) }));
      window.setTimeout(() => {
        try {
          ws.close();
        } catch {
          // ignore
        }
      }, 500);
    };
  } catch {
    // ignore — caller falls back to REST.
  }
}
