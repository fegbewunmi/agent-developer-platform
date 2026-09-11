import { NextResponse } from "next/server";
import { signInWithPassword } from "@/lib/identityPlatformSignIn";

/**
 * The real deployed authentication path (Phase 6) - Identity Platform
 * email/password sign-in, replacing dev-login. The resulting token is a
 * genuine Identity-Platform-issued, Google-signed ID token - verified on
 * the backend by the exact same, unmodified RemoteJWKSProvider/
 * verify_id_token path every other request uses.
 */
export async function POST(request: Request) {
  const { email, password } = await request.json();
  const result = await signInWithPassword(email, password);
  if (!result.ok) {
    return NextResponse.json({ error: result.error }, { status: result.status });
  }
  return NextResponse.json({ ok: true });
}
