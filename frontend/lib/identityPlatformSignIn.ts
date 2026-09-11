import "server-only";
import { cookies } from "next/headers";
import { TOKEN_COOKIE } from "./api";

/**
 * The one real sign-in call both app/api/auth/login-password/route.ts and
 * app/api/auth/login-demo/route.ts make - Identity Platform's REST API,
 * setting the same httpOnly session cookie either way. Extracted so the
 * demo login route is a real authentication, not a shortcut around one.
 */
export async function signInWithPassword(
  email: string,
  password: string
): Promise<{ ok: true } | { ok: false; status: number; error: string }> {
  const apiKey = process.env.IDENTITY_API_KEY;
  if (!apiKey) {
    return { ok: false, status: 500, error: "Sign-in is not configured on this deployment." };
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
    return { ok: false, status: 502, error: "Identity Platform is unreachable." };
  }

  const body = await response.json();
  if (!response.ok) {
    const message = body?.error?.message === "INVALID_LOGIN_CREDENTIALS" ? "Incorrect email or password." : "Sign-in failed.";
    return { ok: false, status: 401, error: message };
  }

  const cookieStore = await cookies();
  cookieStore.set(TOKEN_COOKIE, body.idToken, {
    httpOnly: true,
    sameSite: "lax",
    path: "/",
    maxAge: 60 * 60, // Identity Platform ID tokens are valid 1h
  });

  return { ok: true };
}
