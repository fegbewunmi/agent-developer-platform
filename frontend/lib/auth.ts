import "server-only";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { apiGet, TOKEN_COOKIE } from "./api";
import type { Me } from "./types";

export {
  canRequestPromotion,
  canDecidePromotion,
  canManageRegistry,
  canRevokeGrant,
  canRequestEvaluation,
  canRequestSkillReview,
  canDecideSkillReview,
} from "./permissions";

/**
 * The real Phase 1 auth model, integrated - not a frontend mock. The token
 * in the cookie is a genuine RS256-signed JWT (either minted by the dev
 * login flow, app/api/dev_auth.py, or a real Identity Platform token in a
 * real deployment) and every call to getSession() re-verifies it against
 * the backend's own GET /v1/me, which runs the exact same
 * get_current_user() dependency every other authenticated endpoint uses.
 * There is no separate frontend notion of "who is logged in" - the backend
 * is always asked.
 */
export async function getSession(): Promise<Me | null> {
  const token = (await cookies()).get(TOKEN_COOKIE)?.value;
  if (!token) return null;
  const result = await apiGet<Me>("/v1/me");
  if (!result.ok) return null;
  return result.data;
}

export async function requireSession(): Promise<Me> {
  const session = await getSession();
  if (!session) {
    redirect("/login");
  }
  return session;
}
