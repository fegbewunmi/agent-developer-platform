import { getSession } from "@/lib/auth";
import { redirect } from "next/navigation";
import { LoginForm } from "./LoginForm";
import { PasswordLoginForm } from "./PasswordLoginForm";
import { DemoLoginButtons } from "./DemoLoginButtons";
import type { DevLoginUser } from "@/lib/types";

const BACKEND_URL = process.env.BACKEND_API_URL ?? "http://127.0.0.1:8000";

type DevLoginState =
  | { kind: "unreachable" }
  | { kind: "unavailable" } // dev-login route doesn't exist - a real (deployed) environment
  | { kind: "available"; users: DevLoginUser[] };

async function getDevLoginState(): Promise<DevLoginState> {
  try {
    const res = await fetch(`${BACKEND_URL}/v1/dev-login/users`, { cache: "no-store" });
    if (res.status === 404) return { kind: "unavailable" };
    if (!res.ok) return { kind: "unreachable" };
    return { kind: "available", users: await res.json() };
  } catch {
    return { kind: "unreachable" };
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

  const devLogin = await getDevLoginState();

  return (
    <div className="flex min-h-screen items-center justify-center bg-bg px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center gap-2">
          <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-accent text-[16px] font-bold text-white">O</span>
          <h1 className="text-[16px] font-semibold text-text">Orion Agent Developer Platform</h1>
          <p className="text-[13px] text-text-faint">Sign in to continue</p>
        </div>
        <div className="rounded-lg border border-border bg-bg-raised p-5">
          {devLogin.kind === "unreachable" ? (
            <p className="text-[13px] text-danger">
              The Orion API is unreachable. Confirm the backend is running at {BACKEND_URL}.
            </p>
          ) : devLogin.kind === "available" && devLogin.users.length > 0 ? (
            <LoginForm users={devLogin.users} next={next} />
          ) : (
            <PasswordLoginForm next={next} />
          )}
        </div>

        {devLogin.kind !== "unreachable" && (
          <div className="mt-4 rounded-lg border border-border bg-bg-raised p-5">
            <p className="mb-3 text-[12px] font-medium uppercase tracking-wide text-text-faint">
              Or explore without an account
            </p>
            <DemoLoginButtons next={next} />
          </div>
        )}
      </div>
    </div>
  );
}
