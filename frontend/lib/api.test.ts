/** Unit tests for lib/api.ts: normalizers, env handling, REST calls, WS helpers. */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  apiBase,
  createSimulation,
  getAssignments,
  getCommunications,
  getEvents,
  getMetrics,
  getState,
  injectEvent,
  normalizeAssignments,
  normalizeComms,
  normalizeEvents,
  normalizeMetrics,
  normalizeWorld,
  replaySimulation,
  stepSimulation,
  subscribeSimulation,
  wsUrl,
} from "./api";

const ENV_KEY = "NEXT_PUBLIC_API_URL";

beforeEach(() => {
  vi.unstubAllGlobals();
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      json: async () => ({}),
      text: async () => "",
    })),
  );
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function jsonResponse(body: unknown, ok = true, status = 200) {
  return {
    ok,
    status,
    json: async () => body,
    text: async () => (ok ? "" : JSON.stringify(body)),
  } as unknown as Response;
}

describe("apiBase / wsUrl", () => {
  it("prefers NEXT_PUBLIC_API_URL and strips trailing slashes", () => {
    vi.stubEnv(ENV_KEY, "https://cmd.example:9000///");
    expect(apiBase()).toBe("https://cmd.example:9000");
    expect(wsUrl("SIM-001")).toBe("wss://cmd.example:9000/ws/simulations/SIM-001");
  });

  it("falls back to localhost dev default and converts http->ws", () => {
    vi.stubEnv(ENV_KEY, "");
    expect(apiBase()).toBe("http://localhost:8000");
    expect(wsUrl("SIM-007")).toBe("ws://localhost:8000/ws/simulations/SIM-007");
  });
});

describe("normalizeWorld", () => {
  it("accepts dict-form backend payloads (Pydantic World keyed by id)", () => {
    const raw = {
      world: {
        nodes: { "N-01": { node_id: "N-01", x: 1, y: 2, kind: "station" } },
        edges: {
          "R-01": {
            edge_id: "R-01",
            from_node: "N-01",
            to_node: "N-02",
            mode: "road",
            status: "closed",
          },
        },
        incidents: {
          "INC-01": { incident_id: "INC-01", node_id: "N-02", urgency: 5, people: 3 },
        },
        boats: { "BOAT-01": { boat_id: "BOAT-01", node_id: "N-01", status: "FAILED" } },
        teams: {},
        shelters: {
          "SHELTER-01": { shelter_id: "SHELTER-01", node_id: "N-21", capacity: 10, occupancy: 8 },
        },
      },
    };
    const w = normalizeWorld(raw);
    expect(w.nodes).toHaveLength(1);
    expect(w.nodes[0]).toMatchObject({ node_id: "N-01", x: 1, y: 2 });
    expect(w.edges[0]).toMatchObject({ edge_id: "R-01", status: "closed" });
    expect(w.incidents[0]).toMatchObject({ incident_id: "INC-01", status: "OPEN" });
    expect(w.boats[0]).toMatchObject({ boat_id: "BOAT-01", status: "FAILED" });
    expect(w.shelters[0]).toMatchObject({ shelter_id: "SHELTER-01", accepting: true });
  });

  it("accepts array-form payloads and applies safe defaults", () => {
    const w = normalizeWorld({
      nodes: [{ node_id: "N-09" }],
      edges: [],
      incidents: [],
      boats: [],
      teams: [],
      shelters: [],
    });
    expect(w.nodes[0]).toMatchObject({ neighborhood: "—", kind: "intersection", x: 0, y: 0 });
  });

  it("tolerates null/undefined input", () => {
    const w = normalizeWorld(null);
    expect(w).toEqual({ nodes: [], edges: [], incidents: [], boats: [], teams: [], shelters: [] });
  });
});

describe("normalizeEvents", () => {
  it("maps backend event log entries to SimEvent", () => {
    const evs = normalizeEvents({
      events: [
        { tick: 40, kind: "EDGE_CLOSED", actor: "sim", detail: { edge_id: "R-11" } },
        { tick: 41, type: "REJECTED", sender_id: "dispatch", reason: "EDGE_CLOSED:R-11" },
      ],
    });
    expect(evs).toHaveLength(2);
    expect(evs[0]).toMatchObject({ tick: 40, kind: "EDGE_CLOSED", actor: "sim" });
    expect(evs[1].kind).toBe("REJECTED");
    expect(evs[1].actor).toBe("dispatch");
  });
});

describe("normalizeAssignments", () => {
  it("defaults missing status/cost and passes through history", () => {
    const { assignments, history } = normalizeAssignments({
      assignments: [{ assignment_id: "ASN-00001", incident_id: "INC-01", resource_id: "BOAT-01" }],
      history: [{ tick: 3, reason: "commit", actor: "dispatch" } as never],
    });
    expect(assignments[0]).toMatchObject({ status: "COMMITTED", version: 1 });
    expect(history).toHaveLength(1);
  });
});

describe("normalizeMetrics", () => {
  it("reads rejected_by_reason and extra Phase-8 fields", () => {
    const m = normalizeMetrics({
      ticks: 60,
      strategy: "centralized",
      served: 9,
      unserved: 3,
      committed: 12,
      rejected_by_reason: { "EDGE_CLOSED:R-11": 2 },
      avg_service_time: 14.2,
    });
    expect(m).toMatchObject({ ticks: 60, served: 9, committed: 12 });
    expect(m.rejected_by_reason["EDGE_CLOSED:R-11"]).toBe(2);
    expect(m.extra?.avg_service_time).toBe(14.2);
  });
});

describe("normalizeComms", () => {
  it("keeps QUEUED/DELIVERED/ACKED/EXPIRED distinct and never conflates them", () => {
    const c = normalizeComms({
      tick: 60,
      connected: ["BOAT-01"],
      disconnected: ["BOAT-03"],
      queue: [{ message_id: "M1", status: "QUEUED" }],
      messages: [
        { message_id: "M2", status: "DELIVERED" },
        { message_id: "M3", status: "ACKED" },
        { message_id: "M4", status: "EXPIRED" },
      ],
      reconciliation_log: [],
      partitions: [{ agent_id: "BOAT-03", from_tick: 45, to_tick: 60 }],
    });
    expect(c.queue[0].status).toBe("QUEUED");
    expect(c.messages.map((m) => m.status)).toEqual(["DELIVERED", "ACKED", "EXPIRED"]);
    expect(c.partitions[0]).toMatchObject({ agent_id: "BOAT-03", from_tick: 45, to_tick: 60 });
  });

  it("coerces unknown statuses to QUEUED instead of inventing delivery", () => {
    const c = normalizeComms({ messages: [{ message_id: "MX", status: "SENT" }] });
    expect(c.messages[0].status).toBe("QUEUED");
  });
});

describe("REST calls (mocked fetch)", () => {
  it("checkBackend returns true on /health 200, false otherwise", async () => {
    const fetchMock = vi.mocked(fetch);
    const { checkBackend } = await import("./api");
    fetchMock.mockResolvedValueOnce(jsonResponse({ status: "ok" }));
    expect(await checkBackend()).toBe(true);
    expect(fetchMock.mock.calls[0][0] as string).toContain("/health");
    fetchMock.mockResolvedValueOnce(jsonResponse({ reason: "x" }, false, 500));
    expect(await checkBackend()).toBe(false);
    fetchMock.mockRejectedValueOnce(new Error("down"));
    expect(await checkBackend()).toBe(false);
  });

  it("createSimulation posts strategy+scenario_name and never a string `scenario`", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ simulation_id: "SIM-010", tick: 0, status: "created", strategy: "negotiation", seed: 7 }),
    );
    const res = await createSimulation({ strategy: "negotiation", scenario_name: "baseline", seed: 7 });
    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/api/simulations");
    const body = JSON.parse(String(init.body)) as Record<string, unknown>;
    expect(body).toMatchObject({ strategy: "negotiation", scenario_name: "baseline" });
    // Regression: a string `scenario` key 422s older backends (dict_type at body.scenario).
    expect(body).not.toHaveProperty("scenario");
    expect(res).toMatchObject({ simulation_id: "SIM-010", strategy: "negotiation", seed: 7 });
  });

  it("createSimulation sends inline scenario documents under `scenario`", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ simulation_id: "SIM-011", tick: 0, status: "created", strategy: "centralized", seed: 1 }),
    );
    const inline = { scenario_name: "custom", nodes: [], edges: [] };
    await createSimulation({ strategy: "centralized", scenario: inline });
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(String(init.body)) as Record<string, unknown>;
    expect(body.scenario).toEqual(inline);
  });

  it("getState normalizes dict-form world + snapshots", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      jsonResponse({
        tick: 5,
        status: "running",
        world: { nodes: [], edges: [], incidents: [], boats: [], teams: [], shelters: [] },
        snapshots: [10],
      }),
    );
    const st = await getState("SIM-001");
    expect(st).toMatchObject({ tick: 5, status: "running", snapshots: [10] });
  });

  it("stepSimulation posts {steps} and injectEvent returns event_id+tick", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValueOnce(jsonResponse({ simulation_id: "SIM-001", tick: 6, status: "running" }));
    const r = await stepSimulation("SIM-001", 1);
    expect(r.tick).toBe(6);
    fetchMock.mockResolvedValueOnce(jsonResponse({ event_id: "EVT-1", tick: 6, kind: "CLOSURE", scheduled_tick: 7 }));
    const inj = await injectEvent("SIM-001", { kind: "CLOSURE", payload: { edge_id: "R-11" } });
    // Backend contract (store.inject_event) returns scheduled_tick alongside
    // tick; useSimulation.inject consumes it for the "applies on step" notice.
    expect(inj).toEqual({ event_id: "EVT-1", tick: 6, scheduled_tick: 7 });
  });

  it("getEvents/getAssignments/getMetrics/getCommunications/replay pass through normalizers", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValueOnce(jsonResponse({ events: [{ tick: 1, kind: "COMMITTED", actor: "d", detail: {} }] }));
    expect(await getEvents("SIM-001")).toHaveLength(1);
    fetchMock.mockResolvedValueOnce(jsonResponse({ assignments: [], history: [] }));
    expect((await getAssignments("SIM-001")).assignments).toEqual([]);
    fetchMock.mockResolvedValueOnce(jsonResponse({ ticks: 5, served: 2, rejected_by_reason: {} }));
    expect((await getMetrics("SIM-001")).served).toBe(2);
    fetchMock.mockResolvedValueOnce(jsonResponse({ tick: 5, queue: [], messages: [] }));
    expect((await getCommunications("SIM-001")).tick).toBe(5);
    fetchMock.mockResolvedValueOnce(jsonResponse({ simulation_id: "SIM-001", tick: 5, summary: { served: 2 } }));
    expect((await replaySimulation("SIM-001")).tick).toBe(5);
  });

  it("throws a short API error on non-OK responses", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ reason: "UNKNOWN_EDGE" }, false, 422));
    await expect(getState("SIM-001")).rejects.toThrow("API 422");
  });
});

describe("subscribeSimulation", () => {
  class FakeWS {
    static instances: FakeWS[] = [];
    onopen: (() => void) | null = null;
    onclose: (() => void) | null = null;
    onmessage: ((ev: { data: string }) => void) | null = null;
    closed = false;
    constructor() {
      FakeWS.instances.push(this);
    }
    close() {
      this.closed = true;
    }
  }

  beforeEach(() => {
    FakeWS.instances = [];
    vi.stubGlobal("WebSocket", FakeWS);
  });

  it("delivers normalized tick+events and reports connection status", () => {
    const seen: number[] = [];
    const statuses: boolean[] = [];
    const unsub = subscribeSimulation(
      "SIM-001",
      (m) => seen.push(m.tick),
      (ok) => statuses.push(ok),
    );
    const sock = FakeWS.instances[0];
    sock.onopen?.();
    sock.onmessage?.({
      data: JSON.stringify({ tick: 3, events: [{ tick: 3, kind: "COMMITTED", actor: "d", detail: {} }] }),
    });
    expect(statuses).toEqual([true]);
    expect(seen).toEqual([3]);
    unsub();
    expect(sock.closed).toBe(true);
  });

  it("ignores malformed frames without throwing", () => {
    const onMessage = vi.fn();
    subscribeSimulation("SIM-001", onMessage);
    const sock = FakeWS.instances[0];
    expect(() => sock.onmessage?.({ data: "not-json{{{" })).not.toThrow();
    expect(onMessage).not.toHaveBeenCalled();
  });

  it("returns a no-op unsub when WebSocket construction throws", () => {
    vi.stubGlobal(
      "WebSocket",
      class {
        constructor() {
          throw new Error("no ws");
        }
      },
    );
    const onStatus = vi.fn();
    const unsub = subscribeSimulation("SIM-001", () => {}, onStatus);
    expect(onStatus).toHaveBeenCalledWith(false);
    expect(() => unsub()).not.toThrow();
  });
});
