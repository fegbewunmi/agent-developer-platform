import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import type { GateResult } from "@/lib/types";

// EvaluationSection.tsx imports ./actions.ts, which imports lib/api.ts
// (a server-only module) - fine in the real Next.js server runtime, but
// these tests only exercise the pure, exported GateRow display component,
// so the server action itself is mocked out rather than pulled in.
vi.mock("./actions", () => ({ requestEvaluationAction: vi.fn() }));

const { GateRow } = await import("./EvaluationSection");

function gate(overrides: Partial<GateResult> = {}): GateResult {
  return {
    id: "gate-1",
    evaluation_run_reference_id: "ref-1",
    gate_type: "min_dimension_score",
    criterion: "grounding >= 0.9",
    expected: "0.9",
    actual: "0.82",
    passed: false,
    reason: null,
    evidence_ref: null,
    evaluated_at: "2026-09-11T00:00:00Z",
    ...overrides,
  };
}

describe("GateRow - making failures useful, never a blended score", () => {
  it("shows the criterion, required, and observed values for a failing gate", () => {
    render(<GateRow gate={gate({ criterion: "grounding >= 0.9", expected: "0.9", actual: "0.82" })} />);
    expect(screen.getByText("grounding >= 0.9")).toBeInTheDocument();
    expect(screen.getByText(/Required: 0.9/)).toBeInTheDocument();
    expect(screen.getByText(/Observed: 0.82/)).toBeInTheDocument();
    expect(screen.getByText("Failed")).toBeInTheDocument();
  });

  it("surfaces the failure reason when present", () => {
    render(<GateRow gate={gate({ passed: false, reason: "mean score 0.82 is below the required 0.9" })} />);
    expect(screen.getByText("mean score 0.82 is below the required 0.9")).toBeInTheDocument();
  });

  it("does not show a reason line for a passing gate", () => {
    render(<GateRow gate={gate({ passed: true, actual: "0.95", reason: null })} />);
    expect(screen.getByText("Passed")).toBeInTheDocument();
    expect(screen.queryByText(/below the required/)).not.toBeInTheDocument();
  });

  it("renders a regression gate the same way - required/observed/status, no blended score", () => {
    render(<GateRow gate={gate({ criterion: "new regressions <= 0", expected: "0", actual: "2", passed: false, reason: "2 new regression(s)" })} />);
    expect(screen.getByText("new regressions <= 0")).toBeInTheDocument();
    expect(screen.getByText(/Required: 0/)).toBeInTheDocument();
    expect(screen.getByText(/Observed: 2/)).toBeInTheDocument();
    expect(screen.getByText("2 new regression(s)")).toBeInTheDocument();
  });
});
