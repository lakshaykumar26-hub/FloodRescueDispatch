/** ExplanationPanel: selected vs alternatives, rejection reasons, replan chain, stale notes. */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { DEMO_ASSIGNMENTS, DEMO_EVENTS } from "../lib/demo-data";
import ExplanationPanel from "./explanation-panel";

const onSelect = vi.fn();

describe("ExplanationPanel", () => {
  it("prompts for a selection when nothing is chosen", () => {
    render(<ExplanationPanel assignments={DEMO_ASSIGNMENTS} events={DEMO_EVENTS} selectedId={null} onSelect={onSelect} />);
    expect(screen.getByText(/Select an assignment/i)).toBeInTheDocument();
    expect(screen.getByText(/ASN-00001 · IN_PROGRESS/)).toBeInTheDocument();
  });

  it("shows selected cost/route/version plus lifecycle history", () => {
    render(
      <ExplanationPanel assignments={DEMO_ASSIGNMENTS} events={DEMO_EVENTS} selectedId="ASN-00001" onSelect={onSelect} />,
    );
    expect(screen.getByText(/Selected: BOAT-01 → INC-08/)).toBeInTheDocument();
    expect(screen.getByText(/cost 7\.40/)).toBeInTheDocument();
    expect(screen.getByText(/W-02 → W-06/)).toBeInTheDocument();
    expect(screen.getByText(/PROPOSED → COMMITTED/)).toBeInTheDocument();
  });

  it("cites EDGE_CLOSED rejection reasons from related events", () => {
    // Related = events whose detail mentions the assignment/incident/resource/route keys.
    const events = [
      { tick: 40, kind: "EDGE_CLOSED", actor: "sim", detail: { edge_id: "R-05", reason: "bridge closure", assignment_id: "ASN-00002" } },
      { tick: 40, kind: "REJECTED", actor: "dispatch", detail: { proposal_id: "PROP-00007", incident_id: "INC-03", reason: "EDGE_CLOSED:R-05" } },
      { tick: 41, kind: "COMMITTED", actor: "dispatch", detail: { assignment_id: "ASN-00002", note: "rerouted" } },
    ] as never;
    render(
      <ExplanationPanel assignments={DEMO_ASSIGNMENTS} events={events} selectedId="ASN-00002" onSelect={onSelect} />,
    );
    expect(screen.getByText(/Rejection reasons & safety checks/)).toBeInTheDocument();
    expect(screen.getAllByText(/EDGE_CLOSED/).length).toBeGreaterThan(0);
  });

  it("surfaces the REPLAN_CHAIN for cancelled assignments", () => {
    render(
      <ExplanationPanel assignments={DEMO_ASSIGNMENTS} events={DEMO_EVENTS} selectedId="ASN-00003" onSelect={onSelect} />,
    );
    expect(screen.getByText(/Replan chain/)).toBeInTheDocument();
    expect(screen.getAllByText(/REPLAN_CHAIN ASN-00003/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/CANCELLED:RESOURCE_FAILED/).length).toBeGreaterThanOrEqual(1); // lifecycle + rejection + chain
  });

  it("flags REQUIRES_RECONCILIATION as stale/conflicting", () => {
    const assignments = [
      { ...DEMO_ASSIGNMENTS[0], assignment_id: "ASN-099", status: "REQUIRES_RECONCILIATION", history: [] },
    ] as never;
    render(<ExplanationPanel assignments={assignments} events={[]} selectedId="ASN-099" onSelect={onSelect} />);
    expect(screen.getByText(/Stale\/conflicting state flagged/i)).toBeInTheDocument();
  });

  it("toggles selection off when the active button is clicked again", () => {
    const sel = vi.fn();
    render(
      <ExplanationPanel assignments={DEMO_ASSIGNMENTS} events={DEMO_EVENTS} selectedId="ASN-00001" onSelect={sel} />,
    );
    fireEvent.click(screen.getByText(/ASN-00001 · IN_PROGRESS/));
    expect(sel).toHaveBeenCalledWith(null);
  });
});
