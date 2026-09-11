import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import type { Candidacy } from "@/lib/types";

// See EvaluationSection.test.tsx's comment - same reasoning.
vi.mock("./actions", () => ({ requestPromotionAction: vi.fn() }));

const { FreshnessDisplay } = await import("./PromotionSection");

function candidacy(overrides: Partial<Candidacy> = {}): Candidacy {
  return {
    agent_version_id: "v1",
    current_stage: "candidate",
    evaluation_run_reference_id: "ref-1",
    historically_passed: true,
    currently_eligible: true,
    stale_findings: [],
    ...overrides,
  };
}

describe("FreshnessDisplay - the core freshness UX differentiator", () => {
  it("shows both Passed and Eligible when fresh", () => {
    render(<FreshnessDisplay candidacy={candidacy()} />);
    expect(screen.getByText("Passed")).toBeInTheDocument();
    expect(screen.getByText("Eligible")).toBeInTheDocument();
  });

  it("never turns a historically passing evaluation into a failure when it goes stale", () => {
    render(
      <FreshnessDisplay
        candidacy={candidacy({
          historically_passed: true,
          currently_eligible: false,
          stale_findings: [{ reason: "capability_grants_changed", detail: "grants changed since evaluation" }],
        })}
      />
    );
    // Evaluation itself still reads Passed, not Failed/Not passed.
    expect(screen.getByText("Passed")).toBeInTheDocument();
    expect(screen.queryByText("Not passed")).not.toBeInTheDocument();
    // Eligibility is what's marked stale, distinctly.
    expect(screen.getByText("Stale")).toBeInTheDocument();
  });

  it("shows the explanatory note distinguishing historical pass from current staleness", () => {
    render(
      <FreshnessDisplay
        candidacy={candidacy({
          historically_passed: true,
          currently_eligible: false,
          stale_findings: [{ reason: "policy_changed", detail: "the policy moved on" }],
        })}
      />
    );
    expect(screen.getByText(/genuinely passed/i)).toBeInTheDocument();
    expect(screen.getByText(/evidence has simply drifted/i)).toBeInTheDocument();
  });

  it("does not show the explanatory note when nothing went stale", () => {
    render(<FreshnessDisplay candidacy={candidacy()} />);
    expect(screen.queryByText(/genuinely passed/i)).not.toBeInTheDocument();
  });

  it("renders every explicit stale reason with its detail, never a generic 'stale' blob", () => {
    render(
      <FreshnessDisplay
        candidacy={candidacy({
          currently_eligible: false,
          stale_findings: [
            { reason: "capability_grants_changed", detail: "grants changed" },
            { reason: "dataset_changed", detail: "dataset drifted" },
          ],
        })}
      />
    );
    // Rendered with CSS `capitalize` (visual only) - actual text content is lowercase.
    expect(screen.getByText("capability grants changed")).toBeInTheDocument();
    expect(screen.getByText("dataset changed")).toBeInTheDocument();
    expect(screen.getByText(/dataset drifted/)).toBeInTheDocument();
  });

  it("shows a failed evaluation as Not passed, distinct from stale", () => {
    render(<FreshnessDisplay candidacy={candidacy({ historically_passed: false, currently_eligible: false, stale_findings: [] })} />);
    expect(screen.getByText("Not passed")).toBeInTheDocument();
  });
});
