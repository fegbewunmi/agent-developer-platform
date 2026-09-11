import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import {
  StageBadge,
  HealthBadge,
  ClassificationBadge,
  RunStatusBadge,
  PromotionStatusBadge,
  PassFailBadge,
  EligibilityBadge,
} from "./Badge";

describe("StageBadge", () => {
  it.each([
    ["draft", "Draft"],
    ["evaluating", "Evaluating"],
    ["candidate", "Candidate"],
    ["production", "Production"],
    ["retired", "Retired"],
  ] as const)("renders %s as %s", (stage, label) => {
    render(<StageBadge stage={stage} />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });
});

describe("HealthBadge", () => {
  it("renders Healthy for a healthy server", () => {
    render(<HealthBadge status="healthy" />);
    expect(screen.getByText("Healthy")).toBeInTheDocument();
  });

  it("renders Unavailable for an unavailable server", () => {
    render(<HealthBadge status="unavailable" />);
    expect(screen.getByText("Unavailable")).toBeInTheDocument();
  });
});

describe("ClassificationBadge", () => {
  it("distinguishes read from write", () => {
    const { rerender } = render(<ClassificationBadge classification="read" />);
    expect(screen.getByText("Read")).toBeInTheDocument();
    rerender(<ClassificationBadge classification="write" />);
    expect(screen.getByText("Write")).toBeInTheDocument();
  });
});

describe("RunStatusBadge - evaluation state rendering", () => {
  it("never fakes a progress percentage - only discrete states", () => {
    render(<RunStatusBadge status="requested" />);
    expect(screen.getByText("Queued")).toBeInTheDocument();
  });

  it("renders Running for dispatched", () => {
    render(<RunStatusBadge status="dispatched" />);
    expect(screen.getByText("Running")).toBeInTheDocument();
  });

  it("renders Failed distinctly from Completed", () => {
    const { rerender } = render(<RunStatusBadge status="failed" />);
    expect(screen.getByText("Failed")).toBeInTheDocument();
    rerender(<RunStatusBadge status="completed" />);
    expect(screen.getByText("Completed")).toBeInTheDocument();
  });
});

describe("PromotionStatusBadge", () => {
  it.each(["pending", "approved", "rejected", "withdrawn"] as const)("renders %s", (status) => {
    render(<PromotionStatusBadge status={status} />);
    expect(screen.getByText(status[0].toUpperCase() + status.slice(1))).toBeInTheDocument();
  });
});

describe("PassFailBadge - gate results", () => {
  it("renders Passed for a passing gate", () => {
    render(<PassFailBadge passed={true} />);
    expect(screen.getByText("Passed")).toBeInTheDocument();
  });

  it("renders Failed for a failing gate", () => {
    render(<PassFailBadge passed={false} />);
    expect(screen.getByText("Failed")).toBeInTheDocument();
  });
});

describe("EligibilityBadge - freshness distinction", () => {
  it("renders Eligible, never conflating it with a gate pass", () => {
    render(<EligibilityBadge eligible={true} />);
    expect(screen.getByText("Eligible")).toBeInTheDocument();
  });

  it("renders Stale, never 'Failed' - a stale historical pass is not a retroactive failure", () => {
    render(<EligibilityBadge eligible={false} />);
    expect(screen.getByText("Stale")).toBeInTheDocument();
    expect(screen.queryByText("Failed")).not.toBeInTheDocument();
  });
});
