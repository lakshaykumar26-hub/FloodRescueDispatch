/** Demo-data invariants: the offline fallback must always exercise every gate. */
import { describe, expect, it } from "vitest";
import { DEMO_ASSIGNMENTS, DEMO_COMMS, DEMO_EVENTS, DEMO_METRICS, DEMO_WORLD } from "./demo-data";

describe("DEMO_WORLD", () => {
  it("covers all node kinds with in-range coordinates", () => {
    const kinds = new Set(DEMO_WORLD.nodes.map((n) => n.kind));
    for (const k of ["station", "transfer", "incident_site", "shelter", "intersection"]) {
      expect(kinds.has(k as never)).toBe(true);
    }
    for (const n of DEMO_WORLD.nodes) {
      expect(n.x).toBeGreaterThanOrEqual(0);
      expect(n.y).toBeGreaterThanOrEqual(0);
    }
  });

  it("always includes one closed and one disputed edge (map-legend coverage)", () => {
    expect(DEMO_WORLD.edges.some((e) => e.status === "closed")).toBe(true);
    expect(DEMO_WORLD.edges.some((e) => e.status === "disputed")).toBe(true);
  });

  it("has a failed boat needing recovery and a full shelter", () => {
    expect(DEMO_WORLD.boats.some((b) => b.status === "FAILED" || b.needs_recovery)).toBe(true);
    expect(DEMO_WORLD.shelters.some((s) => !s.accepting)).toBe(true);
  });
});

describe("DEMO_ASSIGNMENTS", () => {
  it("spans IN_PROGRESS + CANCELLED with a REPLAN_CHAIN link", () => {
    const statuses = new Set(DEMO_ASSIGNMENTS.map((a) => a.status));
    expect(statuses.has("IN_PROGRESS")).toBe(true);
    expect(statuses.has("CANCELLED")).toBe(true);
    const chain = DEMO_ASSIGNMENTS.flatMap((a) => a.history).some((h) => /REPLAN_CHAIN/.test(h.reason));
    expect(chain).toBe(true);
  });
});

describe("DEMO_EVENTS", () => {
  it("covers the full disruption arc used by the manual demo script", () => {
    const kinds = new Set(DEMO_EVENTS.map((e) => e.kind));
    for (const k of ["EDGE_CLOSED", "EDGE_DISPUTED", "BOAT_FAILED", "REJECTED", "PARTITION_START", "RECONCILED"]) {
      expect(kinds.has(k)).toBe(true);
    }
  });
});

describe("DEMO_COMMS / DEMO_METRICS", () => {
  it("shows a disconnected agent with queued + expired + reconciled state", () => {
    expect(DEMO_COMMS.disconnected.length).toBeGreaterThan(0);
    expect(DEMO_COMMS.queue.length).toBeGreaterThan(0);
    expect(DEMO_COMMS.messages.some((m) => m.status === "EXPIRED")).toBe(true);
    expect(DEMO_COMMS.reconciliation_log.length).toBeGreaterThan(0);
    expect(DEMO_COMMS.partitions.length).toBeGreaterThan(0);
  });

  it("has served/unserved/committed plus rejection reasons and extras", () => {
    expect(DEMO_METRICS.served + DEMO_METRICS.unserved).toBeGreaterThan(0);
    expect(Object.keys(DEMO_METRICS.rejected_by_reason).length).toBeGreaterThan(0);
    expect(Object.keys(DEMO_METRICS.extra ?? {}).length).toBeGreaterThan(0);
  });
});
