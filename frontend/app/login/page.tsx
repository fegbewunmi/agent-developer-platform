import { getSession } from "@/lib/auth";
import { redirect } from "next/navigation";
import { LoginForm } from "./LoginForm";
import type { DevLoginUser } from "@/lib/types";

const BACKEND_URL = process.env.BACKEND_API_URL ?? "http://127.0.0.1:8000";

async function getDevLoginUsers(): Promise<{ users: DevLoginUser[]; unavailable: boolean }> {
  try {
    const res = await fetch(`${BACKEND_URL}/v1/dev-login/users`, { cache: "no-store" });
    if (!res.ok) return { users: [], unavailable: true };
    return { users: await res.json(), unavailable: false };
  } catch {
    return { users: [], unavailable: true };
  }
}

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string }>;
}) {
  const existing = await getSession();
  const { next } = await searchParams;
  if (existing) {
    redirect(next || "/overview");
  }

  const { users, unavailable } = await getDevLoginUsers();

  return (
    <div className="flex min-h-screen items-center justify-center bg-bg px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center gap-2">
          <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-accent text-[16px] font-bold text-white">O</span>
          <h1 className="text-[16px] font-semibold text-text">Orion Agent Developer Platform</h1>
          <p className="text-[13px] text-text-faint">Sign in to continue</p>
        </div>
        <div className="rounded-lg border border-border bg-bg-raised p-5">
          {unavailable ? (
            <p className="text-[13px] text-danger">
              The Orion API is unreachable. Confirm the backend is running at {BACKEND_URL}.
            </p>
          ) : users.length === 0 ? (
            <p className="text-[13px] text-text-muted">
              Dev login is not enabled on this backend (no <code className="mono">AUTH_JWKS_FILE</code> configured).
              In a real deployment, sign-in goes through Identity Platform instead.
            </p>
          ) : (
            <LoginForm users={users} next={next} />
          )}
        </div>
        <p className="mt-4 text-center text-[11px] text-text-faint">
          Dev-only login - mints a real, backend-verified JWT for a seeded Orion Commerce user.
        </p>
      </div>
    </div>
  );
}
