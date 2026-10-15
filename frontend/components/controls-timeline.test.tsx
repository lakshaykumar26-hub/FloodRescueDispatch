/** ControlsBar + TimelinePanel: sim operation from the UI. */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { DEMO_EVENTS } from "../lib/demo-data";
import ControlsBar from "./controls-bar";
import TimelinePanel from "./timeline-panel";

const baseControls = {
  status: "running",
  strategy: "centralized" as const,
  loading: false,
  hasSim: true,
  started: true,
  speed: 1,
  onCreate: vi.fn(),
  onStart: vi.fn(),
  onPause: vi.fn(),
  onStep: vi.fn(),
  onSpeed: vi.fn(),
  onStrategy: vi.fn(),
  onInject: vi.fn(),
  onReplay: vi.fn(),
};

describe("ControlsBar", () => {
  it("fires play/pause/step and speed/strategy changes", () => {
    const p = { ...baseControls, onCreate: vi.fn(), onStart: vi.fn(), onPause: vi.fn(), onStep: vi.fn(), onSpeed: vi.fn(), onStrategy: vi.fn() };
    render(<ControlsBar {...p} />);
    fireEvent.click(screen.getByText(/▶ Play/));
    expect(p.onStart).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByText(/⏸ Pause/));
    expect(p.onPause).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByText("Step +1"));
    expect(p.onStep).toHaveBeenCalledWith(1);
    fireEvent.change(screen.getByLabelText("Speed"), { target: { value: "4" } });
    expect(p.onSpeed).toHaveBeenCalledWith(4);
    fireEvent.change(screen.getByLabelText("Strategy"), { target: { value: "negotiation" } });
    expect(p.onStrategy).toHaveBeenCalledWith("negotiation");
  });

  it("creates a sim with the chosen strategy + scenario", () => {
    const onCreate = vi.fn();
    render(<ControlsBar {...baseControls} onCreate={onCreate} />);
    fireEvent.change(screen.getByLabelText("Scenario"), { target: { value: "combined_disaster" } });
    fireEvent.click(screen.getByText("Create sim"));
    expect(onCreate).toHaveBeenCalledWith("centralized", "combined_disaster");
  });

  it("offers every predefined inject from the demo script", () => {
    const onInject = vi.fn();
    render(<ControlsBar {...baseControls} onInject={onInject} />);
    for (const label of ["Bridge closure R-11", "Boat failure BOAT-02", "Partition BOAT-03", "Heal partition"]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    fireEvent.click(screen.getByText("Bridge closure R-11"));
    expect(onInject).toHaveBeenCalledWith("CLOSURE", { edge_id: "R-11" });
    fireEvent.click(screen.getByText("Heal partition"));
    expect(onInject).toHaveBeenCalledWith("PARTITION_HEAL", { agent_id: "BOAT-03" });
  });

  it("passes the replay tick only when provided", () => {
    const onReplay = vi.fn();
    render(<ControlsBar {...baseControls} onReplay={onReplay} />);
    fireEvent.click(screen.getByText("↺ Replay"));
    expect(onReplay).toHaveBeenCalledWith(undefined);
    fireEvent.change(screen.getByLabelText("Replay from tick"), { target: { value: "40" } });
    fireEvent.click(screen.getByText("↺ Replay"));
    expect(onReplay).toHaveBeenCalledWith(40);
  });

  it("disables sim controls until a sim exists", () => {
    render(<ControlsBar {...baseControls} hasSim={false} started={false} />);
    expect(screen.getByText(/▶ Play/)).toBeDisabled();
    expect(screen.getByText("Step +1")).toBeDisabled();
    expect(screen.getByText("↺ Replay")).toBeDisabled();
    expect(screen.getByText(/⏸ Pause/)).toBeDisabled();
  });

  it("disables step/pause/replay on a created-but-unstarted sim (409 NOT_STARTED)", () => {
    const onStep = vi.fn();
    const onReplay = vi.fn();
    render(<ControlsBar {...baseControls} status="created" started={false} onStep={onStep} onReplay={onReplay} />);
    // Play stays enabled — it is the way out of this state.
    expect(screen.getByText(/▶ Play/)).not.toBeDisabled();
    for (const label of ["Step +1", "↺ Replay", /⏸ Pause/]) {
      expect(screen.getByText(label)).toBeDisabled();
    }
    expect(screen.getByText("Step +1").getAttribute("title")).toMatch(/Press Play first/);
    expect(onStep).not.toHaveBeenCalled();
    expect(onReplay).not.toHaveBeenCalled();
  });
});

describe("TimelinePanel", () => {
  it("lists events up to the scrub tick and reports kinds", () => {
    const onScrub = vi.fn();
    const onPickEvent = vi.fn();
    render(
      <TimelinePanel events={DEMO_EVENTS} tick={60} maxTick={60} scrubTick={null} onScrub={onScrub} onPickEvent={onPickEvent} />,
    );
    // EDGE_CLOSED appears both as an event row and in the "kinds:" summary line.
    expect(screen.getAllByText(/EDGE_CLOSED/).length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText(/kinds:/)).toBeInTheDocument();
    fireEvent.click(screen.getAllByText(/EDGE_CLOSED/)[0]);
    expect(onPickEvent).toHaveBeenCalledOnce();
    expect(onPickEvent.mock.calls[0][0]).toMatchObject({ kind: "EDGE_CLOSED", tick: 40 });
  });

  it("hides post-scrub events and offers back-to-live", () => {
    const onScrub = vi.fn();
    render(
      <TimelinePanel events={DEMO_EVENTS} tick={60} maxTick={60} scrubTick={40} onScrub={onScrub} onPickEvent={vi.fn()} />,
    );
    expect(screen.getByText(/scrubbing t40/)).toBeInTheDocument();
    // The tick-60 RECONCILED row is hidden past the scrub (only the kinds summary still names it).
    expect(screen.queryByText(/re-acked after heal/)).toBeNull();
    fireEvent.click(screen.getByText("back to live"));
    expect(onScrub).toHaveBeenCalledWith(null);
  });

  it("scrubbing back to the live tick clears the scrub", () => {
    const onScrub = vi.fn();
    render(
      <TimelinePanel events={DEMO_EVENTS} tick={60} maxTick={60} scrubTick={50} onScrub={onScrub} onPickEvent={vi.fn()} />,
    );
    fireEvent.change(screen.getByLabelText("Scrub ticks"), { target: { value: "60" } });
    expect(onScrub).toHaveBeenCalledWith(null);
  });
});
