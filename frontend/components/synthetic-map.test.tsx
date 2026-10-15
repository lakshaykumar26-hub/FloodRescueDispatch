/** SyntheticMap: pure-SVG rendering, edge styles, badges, selection. No tile stack. */
import { fireEvent, render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it, vi } from "vitest";
import SyntheticMap from "./synthetic-map";
import { DEMO_WORLD } from "../lib/demo-data";

describe("SyntheticMap", () => {
  it("renders an offline SVG graph with legend and counts, no tiles", () => {
    const src = readFileSync(resolve(__dirname, "synthetic-map.tsx"), "utf8");
    expect(src).not.toMatch(/leaflet/i);
    expect(src).not.toMatch(/tilelayer|openstreetmap|tile\.|\.png|\.jpg/i);

    const { container } = render(<SyntheticMap world={DEMO_WORLD} />);
    const svg = container.querySelector("svg");
    expect(svg).not.toBeNull();
    expect(svg?.getAttribute("aria-label")).toMatch(/no tiles/i);
    expect(screen.getByText(/disputed ⚠/)).toBeInTheDocument();
    expect(screen.getByText(/nodes · .* edges/)).toBeInTheDocument();
  });

  it("marks closed edges with ✕ and disputed edges with ⚠", () => {
    const { container } = render(<SyntheticMap world={DEMO_WORLD} />);
    // <title> per edge carries "edge_id mode status tt=.."
    expect(container.querySelector("svg")?.textContent).toContain("R-11 road closed");
    expect(container.querySelector("svg")?.textContent).toContain("R-06 road disputed");
    expect(screen.getByText("✕")).toBeInTheDocument();
    expect(screen.getByText("⚠")).toBeInTheDocument();
  });

  it("badges failed boats with 🔥 and disconnected ones with 📡✕", () => {
    const { rerender } = render(<SyntheticMap world={DEMO_WORLD} disconnectedIds={["BOAT-03"]} />);
    expect(screen.getByText("🔥")).toBeInTheDocument(); // BOAT-02 FAILED in demo
    expect(screen.getByText("📡✕")).toBeInTheDocument(); // BOAT-03 disconnected
    rerender(<SyntheticMap world={DEMO_WORLD} disconnectedIds={[]} />);
    expect(screen.queryByText("📡✕")).toBeNull();
  });

  it("forwards incident/resource clicks to the panels", () => {
    const onSelectIncident = vi.fn();
    const onSelectResource = vi.fn();
    const { container } = render(
      <SyntheticMap
        world={DEMO_WORLD}
        onSelectIncident={onSelectIncident}
        onSelectResource={onSelectResource}
      />,
    );
    // Incident circles carry urgency text inside a clickable <g>.
    const incidentNodes = container.querySelectorAll("svg circle");
    expect(incidentNodes.length).toBeGreaterThan(0);
    fireEvent.click(incidentNodes[0]);
    expect(onSelectIncident).toHaveBeenCalledOnce();
    expect(onSelectIncident.mock.calls[0][0]).toMatch(/^INC-/);
  });

  it("renders recovery 🛟 markers for recovery-kind incidents", () => {
    const world = {
      ...DEMO_WORLD,
      incidents: [
        {
          incident_id: "REC-BOAT-02-0033",
          node_id: "N-11",
          urgency: 4,
          people: 2,
          required_capabilities: ["boat"],
          created_tick: 33,
          status: "OPEN",
          report_confidence: 1,
          kind: "recovery",
          caused_by: "ASN-00003",
        },
      ],
    } as typeof DEMO_WORLD;
    render(<SyntheticMap world={world} />);
    expect(screen.getByText("🛟")).toBeInTheDocument();
  });
});
