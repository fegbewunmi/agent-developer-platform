import { NextResponse } from "next/server";
import { signInWithPassword } from "@/lib/identityPlatformSignIn";

/**
 * Testing convenience only - explicitly requested so a solo tester isn't
 * logging out/back in to move between the four seeded Orion Commerce
 * personas. This is a REAL Identity Platform sign-in (same call
 * login-password/login-demo make), just with the credential supplied by
 * the server. It does NOT touch authorization: RBAC and no-self-approval
 * (ADR-0009) are enforced by the backend on every write regardless of how
 * the session was established - this only changes who you're signed in as,
 * the same as typing a different password would.
 *
 * Gated by QUICK_SWITCH_ENABLED so it's off by default - never exposed to
 * a real portfolio visitor unless explicitly turned on for testing.
 */
const CANONICAL_USERS = {
  maya: { email: "maya.chen@orioncommerce.example", envVar: "ORION_MAYA_PASSWORD", name: "Maya Chen" },
  jordan: { email: "jordan.brooks@orioncommerce.example", envVar: "ORION_JORDAN_PASSWORD", name: "Jordan Brooks" },
  priya: { email: "priya.shah@orioncommerce.example", envVar: "ORION_PRIYA_PASSWORD", name: "Priya Shah" },
  alex: { email: "alex.rivera@orioncommerce.example", envVar: "ORION_ALEX_PASSWORD", name: "Alex Rivera" },
} as const;

type UserKey = keyof typeof CANONICAL_USERS;

export async function POST(request: Request) {
  if (!process.env.QUICK_SWITCH_ENABLED) {
    return NextResponse.json({ error: "Quick-switch is not enabled on this deployment." }, { status: 404 });
  }

  const { user } = (await request.json()) as { user?: string };
  const account = user && user in CANONICAL_USERS ? CANONICAL_USERS[user as UserKey] : null;
  if (!account) {
    return NextResponse.json({ error: "Unknown user." }, { status: 400 });
  }

  const password = process.env[account.envVar];
  if (!password) {
    return NextResponse.json({ error: "Quick-switch is not configured on this deployment." }, { status: 500 });
  }

  const result = await signInWithPassword(account.email, password);
  if (!result.ok) {
    return NextResponse.json({ error: result.error }, { status: result.status });
  }
  return NextResponse.json({ ok: true });
}
