import { describe, it, expect } from "vitest";
import {
  canRequestPromotion,
  canDecidePromotion,
  canManageRegistry,
  canRevokeGrant,
  canRequestEvaluation,
  canRequestSkillReview,
  canDecideSkillReview,
} from "./permissions";
import type { Me } from "./types";

function user(overrides: Partial<Me> = {}): Me {
  return {
    id: "user-1",
    name: "Test User",
    email: "test@orioncommerce.example",
    team_id: "team-a",
    role: "builder",
    ...overrides,
  };
}

describe("canDecidePromotion - self-approval prevention", () => {
  it("never allows the requester to decide their own request, even as Admin", () => {
    const admin = user({ id: "admin-1", role: "admin" });
    expect(canDecidePromotion(admin, "admin-1")).toBe(false);
  });

  it("never allows the requester to decide their own request as Reviewer", () => {
    const reviewer = user({ id: "reviewer-1", role: "reviewer" });
    expect(canDecidePromotion(reviewer, "reviewer-1")).toBe(false);
  });

  it("allows a Reviewer to decide a different user's request", () => {
    const reviewer = user({ id: "reviewer-1", role: "reviewer" });
    expect(canDecidePromotion(reviewer, "builder-1")).toBe(true);
  });

  it("allows an Admin to decide a different user's request", () => {
    const admin = user({ id: "admin-1", role: "admin" });
    expect(canDecidePromotion(admin, "builder-1")).toBe(true);
  });

  it("never allows a Builder to decide any request, even someone else's", () => {
    const builder = user({ id: "builder-1", role: "builder" });
    expect(canDecidePromotion(builder, "builder-2")).toBe(false);
  });

  it("never allows a Viewer to decide any request", () => {
    const viewer = user({ id: "viewer-1", role: "viewer" });
    expect(canDecidePromotion(viewer, "builder-2")).toBe(false);
  });
});

describe("canRequestPromotion - team scoping", () => {
  it("allows a Builder to request for their own team", () => {
    const builder = user({ role: "builder", team_id: "team-a" });
    expect(canRequestPromotion(builder, "team-a")).toBe(true);
  });

  it("denies a Builder requesting for a different team", () => {
    const builder = user({ role: "builder", team_id: "team-a" });
    expect(canRequestPromotion(builder, "team-b")).toBe(false);
  });

  it("allows a Reviewer to request for any team", () => {
    const reviewer = user({ role: "reviewer", team_id: "team-a" });
    expect(canRequestPromotion(reviewer, "team-b")).toBe(true);
  });

  it("allows an Admin to request for any team", () => {
    const admin = user({ role: "admin", team_id: "team-a" });
    expect(canRequestPromotion(admin, "team-b")).toBe(true);
  });

  it("denies a Viewer regardless of team", () => {
    const viewer = user({ role: "viewer", team_id: "team-a" });
    expect(canRequestPromotion(viewer, "team-a")).toBe(false);
  });
});

describe("canRequestEvaluation - team scoping", () => {
  it("allows a Builder to request for their own team only", () => {
    const builder = user({ role: "builder", team_id: "team-a" });
    expect(canRequestEvaluation(builder, "team-a")).toBe(true);
    expect(canRequestEvaluation(builder, "team-b")).toBe(false);
  });

  it("allows Reviewer/Admin for any team", () => {
    expect(canRequestEvaluation(user({ role: "reviewer" }), "team-z")).toBe(true);
    expect(canRequestEvaluation(user({ role: "admin" }), "team-z")).toBe(true);
  });
});

describe("canManageRegistry", () => {
  it("is Admin-only", () => {
    expect(canManageRegistry(user({ role: "admin" }))).toBe(true);
    expect(canManageRegistry(user({ role: "reviewer" }))).toBe(false);
    expect(canManageRegistry(user({ role: "builder" }))).toBe(false);
    expect(canManageRegistry(user({ role: "viewer" }))).toBe(false);
  });
});

describe("canRevokeGrant", () => {
  it("allows Reviewer and Admin only", () => {
    expect(canRevokeGrant(user({ role: "reviewer" }))).toBe(true);
    expect(canRevokeGrant(user({ role: "admin" }))).toBe(true);
    expect(canRevokeGrant(user({ role: "builder" }))).toBe(false);
    expect(canRevokeGrant(user({ role: "viewer" }))).toBe(false);
  });
});

describe("canRequestSkillReview - team scoping", () => {
  it("allows a Builder to request for their own team's skill only", () => {
    const builder = user({ role: "builder", team_id: "team-a" });
    expect(canRequestSkillReview(builder, "team-a")).toBe(true);
    expect(canRequestSkillReview(builder, "team-b")).toBe(false);
  });

  it("allows Reviewer/Admin for any team", () => {
    expect(canRequestSkillReview(user({ role: "reviewer" }), "team-z")).toBe(true);
    expect(canRequestSkillReview(user({ role: "admin" }), "team-z")).toBe(true);
  });
});

describe("canDecideSkillReview", () => {
  it("blocks the requester even if elevated (no self-approval)", () => {
    const reviewer = user({ id: "u-1", role: "reviewer" });
    expect(canDecideSkillReview(reviewer, "u-1")).toBe(false);
  });

  it("allows a different Reviewer/Admin", () => {
    const reviewer = user({ id: "u-1", role: "reviewer" });
    expect(canDecideSkillReview(reviewer, "u-2")).toBe(true);
  });

  it("blocks a Builder regardless", () => {
    const builder = user({ id: "u-1", role: "builder" });
    expect(canDecideSkillReview(builder, "u-2")).toBe(false);
  });
});
