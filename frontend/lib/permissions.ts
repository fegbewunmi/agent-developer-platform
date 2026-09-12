// Pure UI-side mirror of backend/app/services/permissions.py - used only to
// decide what to SHOW (hide a button that would just fail). The backend is
// always the real authority: every mutation re-checks this independently
// and returns a real 403/409 regardless of what the UI decided to render.
// No server dependency here on purpose, so this logic is trivially unit
// testable (see lib/permissions.test.ts) without mocking Next.js internals.
import type { Me, Role } from "./types";

const ELEVATED: Role[] = ["reviewer", "admin"];

export function canRequestPromotion(user: Me, teamId: string): boolean {
  if (user.role === "builder") return user.team_id === teamId;
  return ELEVATED.includes(user.role);
}

export function canDecidePromotion(user: Me, requestedBy: string): boolean {
  if (user.id === requestedBy) return false;
  return ELEVATED.includes(user.role);
}

export function canManageRegistry(user: Me): boolean {
  return user.role === "admin";
}

export function canRevokeGrant(user: Me): boolean {
  return ELEVATED.includes(user.role);
}

export function canRequestEvaluation(user: Me, teamId: string): boolean {
  if (user.role === "builder") return user.team_id === teamId;
  return ELEVATED.includes(user.role);
}

// Phase 9: same shape as promotion - a Builder may request review for their
// own team's skill; Reviewer/Admin for any team. Never the requester.
export function canRequestSkillReview(user: Me, ownerTeamId: string): boolean {
  if (user.role === "builder") return user.team_id === ownerTeamId;
  return ELEVATED.includes(user.role);
}

export function canDecideSkillReview(user: Me, requestedBy: string): boolean {
  if (user.id === requestedBy) return false;
  return ELEVATED.includes(user.role);
}
