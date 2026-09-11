import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// The real actions call the backend via a server-only fetch wrapper - not
// exercised here (that's covered by the live browser verification in
// docs/phase-notes/phase-5.md). This test covers the approve/reject UI
// itself: which mode is shown, and that both paths are reachable and
// distinct - not whether the network call succeeds.
vi.mock("./actions", () => ({
  approvePromotionAction: vi.fn(),
  rejectPromotionAction: vi.fn(),
}));

const { ReviewActions } = await import("./ReviewActions");

describe("ReviewActions - approve/reject UI", () => {
  it("shows both Approve and Reject entry points by default", () => {
    render(<ReviewActions requestId="req-1" />);
    expect(screen.getByRole("button", { name: "Approve" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reject" })).toBeInTheDocument();
  });

  it("switches to the approval confirmation form, distinct from rejection", async () => {
    const user = userEvent.setup();
    render(<ReviewActions requestId="req-1" />);
    await user.click(screen.getByRole("button", { name: "Approve" }));
    expect(screen.getByText("Approve this promotion")).toBeInTheDocument();
    expect(screen.queryByText("Reject this promotion")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Confirm approval/ })).toBeInTheDocument();
  });

  it("switches to the rejection confirmation form, distinct from approval", async () => {
    const user = userEvent.setup();
    render(<ReviewActions requestId="req-1" />);
    await user.click(screen.getByRole("button", { name: "Reject" }));
    expect(screen.getByText("Reject this promotion")).toBeInTheDocument();
    expect(screen.queryByText("Approve this promotion")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Confirm rejection/ })).toBeInTheDocument();
  });

  it("returns to the initial choice on cancel", async () => {
    const user = userEvent.setup();
    render(<ReviewActions requestId="req-1" />);
    await user.click(screen.getByRole("button", { name: "Approve" }));
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getByRole("button", { name: "Approve" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reject" })).toBeInTheDocument();
  });
});
