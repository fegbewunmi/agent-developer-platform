import { NextResponse } from "next/server";
import { signInWithPassword } from "@/lib/identityPlatformSignIn";

/**
 * "Continue as demo Builder/Reviewer" (Phase 7) - docs/phase-notes/phase-7.md.
 * A real Identity Platform sign-in, same as login-password, just with the
 * credential supplied by the server instead of typed by the visitor. The
 * demo accounts' blast radius is contained on the backend
 * (app/services/permissions.py::demo_containment_ok), not by keeping this
 * password secret - there is nothing sensitive behind it.
 */
const DEMO_ACCOUNTS = {
  builder: { email: "demo-builder@agent-platform-demo.example", envVar: "DEMO_BUILDER_PASSWORD" },
  reviewer: { email: "demo-reviewer@agent-platform-demo.example", envVar: "DEMO_REVIEWER_PASSWORD" },
} as const;

export async function POST(request: Request) {
  const { role } = (await request.json()) as { role?: string };
  const account = role === "builder" || role === "reviewer" ? DEMO_ACCOUNTS[role as "builder" | "reviewer"] : null;
  if (!account) {
    return NextResponse.json({ error: "Unknown demo role." }, { status: 400 });
  }

  const password = process.env[account.envVar];
  if (!password) {
    return NextResponse.json({ error: "The public demo is not configured on this deployment." }, { status: 500 });
  }

  const result = await signInWithPassword(account.email, password);
  if (!result.ok) {
    return NextResponse.json({ error: result.error }, { status: result.status });
  }
  return NextResponse.json({ ok: true });
}
