/** Comms monitor: truthful queue/delay/retry/expiry/partition + reconciliation. */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { DEMO_COMMS } from "../lib/demo-data";
import CommunicationsPanel from "./communications-panel";

describe("CommunicationsPanel", () => {
  it("shows connected/disconnected agents with counts", () => {
    render(<CommunicationsPanel comms={DEMO_COMMS} />);
    expect(screen.getByText(/Connected \(4\)/)).toBeInTheDocument();
    expect(screen.getByText(/Disconnected \(1\)/)).toBeInTheDocument();
    expect(screen.getAllByText(/BOAT-03/).length).toBeGreaterThanOrEqual(2); // disconnected list + queue row + partition badge
  });

  it("keeps message statuses visually distinct (never conflated)", () => {
    render(<CommunicationsPanel comms={DEMO_COMMS} />);
    for (const status of ["QUEUED", "DELIVERED", "ACKED", "EXPIRED"]) {
      expect(screen.getAllByText(status, { exact: true }).length).toBeGreaterThanOrEqual(1);
    }
    expect(screen.getByText(/retry×2/)).toBeInTheDocument(); // retry count shown, not hidden
  });

  it("badges active partitions and reconciliation outcomes", () => {
    render(<CommunicationsPanel comms={DEMO_COMMS} />);
    expect(screen.getByText(/partition: BOAT-03 t45→60/)).toBeInTheDocument();
    expect(screen.getByText("STALE_ROUTE")).toBeInTheDocument();
    expect(screen.getByText(/re-acked after heal/)).toBeInTheDocument();
  });

  it("renders empty states instead of crashing on missing data", () => {
    render(<CommunicationsPanel comms={null} />);
    expect(screen.getByText(/No comms data yet/)).toBeInTheDocument();

    render(
      <CommunicationsPanel
        comms={{ tick: 0, connected: [], disconnected: [], queue: [], messages: [], reconciliation_log: [], partitions: [] }}
      />,
    );
    expect(screen.getByText(/Queue empty/)).toBeInTheDocument();
    expect(screen.getByText(/No messages yet/)).toBeInTheDocument();
    expect(screen.getByText(/No reconciliations yet/)).toBeInTheDocument();
  });

  it("paginates long message lists, opening on the latest page", () => {
    const messages = Array.from({ length: 25 }, (_, i) => ({
      message_id: `MSG-${String(i + 1).padStart(5, "0")}`,
      type: "BOAT_POSITION",
      sender_id: "BOAT-01",
      recipient_id: "DISPATCH-01",
      created_at_tick: i + 1,
      expires_at_tick: i + 11,
      status: "DELIVERED" as const,
    }));
    render(<CommunicationsPanel comms={{ ...DEMO_COMMS, messages }} />);
    expect(screen.getByText("Page 3 of 3")).toBeInTheDocument();
    expect(screen.getByText("MSG-00025")).toBeInTheDocument();
    expect(screen.queryByText("MSG-00001")).toBeNull();
    fireEvent.click(screen.getByText("‹ Prev"));
    expect(screen.getByText("Page 2 of 3")).toBeInTheDocument();
    expect(screen.queryByText("MSG-00025")).toBeNull();
  });
});
