import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ActivityFeed } from "./ActivityFeed";
import type { AuditEvent } from "@/lib/types";

function event(overrides: Partial<AuditEvent> = {}): AuditEvent {
  return {
    id: "evt-1",
    event_type: "agent.created",
    entity_type: "agent",
    entity_id: "agent-1",
    actor: "user-1",
    occurred_at: new Date().toISOString(),
    payload: {},
    ...overrides,
  };
}

describe("ActivityFeed - rollback history rendering as an ordinary promotion", () => {
  it("labels promotion.rollback distinctly, not as a separate magical event type dressed up", () => {
    render(<ActivityFeed events={[event({ event_type: "promotion.rollback", entity_type: "agent_version", entity_id: "v1" })]} />);
    expect(screen.getByText("Rollback promotion")).toBeInTheDocument();
  });

  it("labels agent_version.promoted the same way whether it's a rollback or an ordinary promotion", () => {
    render(<ActivityFeed events={[event({ event_type: "agent_version.promoted" })]} />);
    expect(screen.getByText("Became recommended")).toBeInTheDocument();
  });

  it("labels agent_version.retired as deprecated-superseded", () => {
    render(<ActivityFeed events={[event({ event_type: "agent_version.retired" })]} />);
    expect(screen.getByText("Deprecated (superseded)")).toBeInTheDocument();
  });

  it("shows an approval-blocked-stale event distinctly from a normal approval", () => {
    render(<ActivityFeed events={[event({ event_type: "promotion.approval_blocked_stale" })]} />);
    expect(screen.getByText("Approval blocked - stale evidence")).toBeInTheDocument();
  });

  it("shows the reason from the payload when present", () => {
    render(<ActivityFeed events={[event({ event_type: "promotion.rejected", payload: { reason: undefined, comment: "not ready yet" } })]} />);
    expect(screen.getByText(/not ready yet/)).toBeInTheDocument();
  });

  it("renders an empty state with no events", () => {
    render(<ActivityFeed events={[]} />);
    expect(screen.getByText("No activity yet")).toBeInTheDocument();
  });

  it("falls back to the raw event_type for an unmapped event rather than crashing", () => {
    render(<ActivityFeed events={[event({ event_type: "some.future.event" })]} />);
    expect(screen.getByText("some.future.event")).toBeInTheDocument();
  });
});
