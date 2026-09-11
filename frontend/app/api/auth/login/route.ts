import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import { TOKEN_COOKIE } from "@/lib/api";

const BACKEND_URL = process.env.BACKEND_API_URL ?? "http://127.0.0.1:8000";

/**
 * Dev login only - mirrors backend/app/api/dev_auth.py's own gating
 * (that endpoint only exists at all when the backend is configured with
 * AUTH_JWKS_FILE, i.e. never in a real Identity-Platform-backed
 * deployment). This route just forwards the choice of seeded user to the
 * backend, which does the actual signing - see lib/auth.ts's module
 * docstring for why this isn't "fake auth."
 */
export async function POST(request: Request) {
  const { email } = await request.json();

  let response: Response;
  try {
    response = await fetch(`${BACKEND_URL}/v1/dev-login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email }),
      cache: "no-store",
    });
  } catch {
    return NextResponse.json({ error: "The Orion API is unreachable." }, { status: 502 });
  }

  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: "Login failed" }));
    return NextResponse.json({ error: body.detail ?? "Login failed" }, { status: response.status });
  }

  const { token } = await response.json();
  const cookieStore = await cookies();
  cookieStore.set(TOKEN_COOKIE, token, {
    httpOnly: true,
    sameSite: "lax",
    path: "/",
    maxAge: 60 * 60 * 12,
  });

  return NextResponse.json({ ok: true });
}
