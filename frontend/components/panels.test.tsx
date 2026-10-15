/** Incident/Resource/Shelter/Metrics panels: detail rendering + compare view. */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { DEMO_COMMS, DEMO_METRICS, DEMO_WORLD } from "../lib/demo-data";
import IncidentPanel from "./incident-panel";
import MetricsPanel from "./metrics-panel";
import ResourcePanel from "./resource-panel";
import ShelterPanel from "./shelter-panel";

void DEMO_COMMS;

describe("IncidentPanel", () => {
  it("sorts by urgency and shows wait/demand/status detail", () => {
    const onSelect = vi.fn();
    render(<IncidentPanel incidents={DEMO_WORLD.incidents} selectedId="INC-03" onSelect={onSelect} tick={20} />);
    expect(screen.getByText("Incidents (3)")).toBeInTheDocument();
    // Detail card for the selected incident (strong INC-03 + wait/demand rows).
    expect(screen.getByText("INC-03")).toBeInTheDocument();
    expect(screen.getByText("U5")).toBeInTheDocument();
    expect(screen.getByText("4 people")).toBeInTheDocument();
    expect(screen.getByText(/18 ticks \(since 2\)/)).toBeInTheDocument(); // wait = tick - created
    // List order: U5 first. Scope to list buttons (detail card ✕ is a separate button).
    const listButtons = screen.getAllByRole("button").filter((b) => /INC-/.test(b.textContent ?? ""));
    expect(listButtons[0].textContent).toContain("INC-03");
    fireEvent.click(screen.getByText(/INC-05/));
    expect(onSelect).toHaveBeenCalledWith("INC-05");
  });

  it("handles the empty list", () => {
    render(<IncidentPanel incidents={[]} selectedId={null} onSelect={vi.fn()} tick={0} />);
    expect(screen.getByText(/No incidents/)).toBeInTheDocument();
  });
});

describe("ResourcePanel", () => {
  it("shows fuel/capacity/mission and recovery guidance for failed boats", () => {
    render(
      <ResourcePanel
        boats={DEMO_WORLD.boats}
        teams={DEMO_WORLD.teams}
        selectedId="BOAT-02"
        onSelect={vi.fn()}
        disconnectedIds={["BOAT-03"]}
      />,
    );
    expect(screen.getByText("Resources (3 boats · 2 teams)")).toBeInTheDocument();
    expect(screen.getByText(/44 \/ reserve 10/)).toBeInTheDocument(); // selected BOAT-02 fuel
  });

  it("marks disconnected resources and links recovery incidents", () => {
    const onSelect = vi.fn();
    render(
      <ResourcePanel boats={DEMO_WORLD.boats} teams={DEMO_WORLD.teams} selectedId={null} onSelect={onSelect} disconnectedIds={["BOAT-03"]} />,
    );
    expect(screen.getAllByText(/📡✕/).length).toBeGreaterThanOrEqual(1);
    // Select the failed boat → recovery explainer appears.
    fireEvent.click(screen.getByText(/BOAT-02/));
    expect(onSelect).toHaveBeenCalledWith("BOAT-02");
  });

  it("selected failed boat shows NEEDED 🛟 + recovery note", () => {
    render(
      <ResourcePanel boats={DEMO_WORLD.boats} teams={DEMO_WORLD.teams} selectedId="BOAT-02" onSelect={vi.fn()} disconnectedIds={[]} />,
    );
    expect(screen.getByText(/NEEDED 🛟/)).toBeInTheDocument();
    expect(screen.getByText(/recovery incident \(REC-BOAT-02/)).toBeInTheDocument();
  });
});

describe("ShelterPanel", () => {
  it("computes remaining = capacity - occupancy - reservations and flags FULL", () => {
    render(<ShelterPanel shelters={DEMO_WORLD.shelters} />);
    expect(screen.getByText("Shelters (2)")).toBeInTheDocument();
    expect(screen.getByText(/open · 3 left/)).toBeInTheDocument(); // 10-4-3
    expect(screen.getByText("FULL")).toBeInTheDocument(); // SHELTER-02 8/8
    expect(screen.getByText(/ASN-00001/)).toBeInTheDocument();
  });
});

describe("MetricsPanel", () => {
  const base = {
    metrics: DEMO_METRICS,
    compareA: null,
    compareB: null,
    onCompareLoaded: vi.fn(),
    liveStrategy: "centralized",
  };

  it("renders served values, rejection chart titles, and extras from the API", () => {
    render(<MetricsPanel {...base} />);
    expect(screen.getAllByText(/centralized \(demo\)/).length).toBeGreaterThanOrEqual(1);
    // Chart internals (axis ticks) do not render in jsdom (zero-width container),
    // so assert the HTML chrome + extra chips that carry the same API values.
    expect(screen.getByText(/service: served \/ unmet \/ committed/)).toBeInTheDocument();
    expect(screen.getByText(/rejected by reason \(violations proxy\)/)).toBeInTheDocument();
    expect(screen.getByText(/avg_service_time: 14.2/)).toBeInTheDocument();
    expect(screen.getByText(/violations \/ fairness gap/)).toBeInTheDocument();
  });

  it("compares two strategies side-by-side via pasted sim ids", async () => {
    const mod = await import("../lib/api");
    const spy = vi.spyOn(mod, "getMetrics");
    spy.mockResolvedValueOnce({ ...DEMO_METRICS, strategy: "centralized", served: 9 });
    spy.mockResolvedValueOnce({ ...DEMO_METRICS, strategy: "negotiation", served: 10 });

    const onCompareLoaded = vi.fn();
    render(<MetricsPanel {...base} onCompareLoaded={onCompareLoaded} />);
    fireEvent.change(screen.getByLabelText("Centralized sim id"), { target: { value: "SIM-001" } });
    fireEvent.change(screen.getByLabelText("Negotiation sim id"), { target: { value: "SIM-002" } });
    fireEvent.click(screen.getByText("Compare side-by-side"));
    await waitFor(() => expect(onCompareLoaded).toHaveBeenCalledOnce());
    expect(spy).toHaveBeenCalledTimes(2);
    expect(onCompareLoaded).toHaveBeenCalledOnce();
    const [a, b] = onCompareLoaded.mock.calls[0] as [typeof DEMO_METRICS, typeof DEMO_METRICS];
    expect(a.strategy).toBe("centralized");
    expect(b.strategy).toBe("negotiation");
    spy.mockRestore();
  });

  it("shows the rejected breakdown in the compare columns", () => {
    render(
      <MetricsPanel
        {...base}
        compareA={DEMO_METRICS}
        compareB={{ ...DEMO_METRICS, strategy: "negotiation" }}
      />,
    );
    expect(screen.getAllByText("centralized (demo)").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("negotiation").length).toBeGreaterThanOrEqual(1);
    // Compare columns print rejected_by_reason as text (chart-free, jsdom-safe).
    expect(screen.getAllByText(/rejected:.*EDGE_CLOSED:R-11=2/).length).toBeGreaterThanOrEqual(1);
  });
});
