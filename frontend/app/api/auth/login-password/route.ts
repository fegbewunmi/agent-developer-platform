import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import { TOKEN_COOKIE } from "@/lib/api";

/**
 * The real deployed authentication path (Phase 6) - Identity Platform
 * email/password sign-in, replacing dev-login. Calls Identity Platform's
 * REST API directly (no Firebase SDK needed for this one call) using a
 * public, API-target-restricted browser key (IDENTITY_API_KEY - safe to be
 * public, it can only initiate sign-in, never read/write data on its own).
 * The resulting token is a genuine Identity-Platform-issued, Google-signed
 * ID token - verified on the backend by the exact same, unmodified
 * RemoteJWKSProvider/verify_id_token path every other request uses.
 */
export async function POST(request: Request) {
  const { email, password } = await request.json();
  const apiKey = process.env.IDENTITY_API_KEY;

  if (!apiKey) {
    return NextResponse.json({ error: "Sign-in is not configured on this deployment." }, { status: 500 });
  }

  let response: Response;
  try {
    response = await fetch(`https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=${apiKey}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password, returnSecureToken: true }),
      cache: "no-store",
    });
  } catch {
    return NextResponse.json({ error: "Identity Platform is unreachable." }, { status: 502 });
  }

  const body = await response.json();
  if (!response.ok) {
    const message = body?.error?.message === "INVALID_LOGIN_CREDENTIALS" ? "Incorrect email or password." : "Sign-in failed.";
    return NextResponse.json({ error: message }, { status: 401 });
  }

  const cookieStore = await cookies();
  cookieStore.set(TOKEN_COOKIE, body.idToken, {
    httpOnly: true,
    sameSite: "lax",
    path: "/",
    maxAge: 60 * 60, // Identity Platform ID tokens are valid 1h
  });

  return NextResponse.json({ ok: true });
}
