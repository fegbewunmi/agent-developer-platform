"use client";
import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";

const USERS = [
  { key: "maya", name: "Maya Chen", role: "Builder" },
  { key: "jordan", name: "Jordan Brooks", role: "Reviewer" },
  { key: "priya", name: "Priya Shah", role: "Reviewer" },
  { key: "alex", name: "Alex Rivera", role: "Admin" },
] as const;

/** Testing convenience (see app/api/auth/quick-switch/route.ts) - lets a
 * solo tester sign in as any of the four seeded Orion Commerce users
 * without knowing their password, mirroring DemoLoginButtons. Only
 * rendered when QUICK_SWITCH_ENABLED is set. */
export function QuickSwitchLoginButtons({ next }: { next?: string }) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const [pendingUser, setPendingUser] = useState<string | null>(null);

  function continueAs(key: string) {
    setError(null);
    setPendingUser(key);
    startTransition(async () => {
      const res = await fetch("/api/auth/quick-switch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user: key }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({ error: "Could not sign in" }));
        setError(body.error ?? "Could not sign in");
        return;
      }
      router.push(next || "/overview");
      router.refresh();
    });
  }

  return (
    <div className="flex flex-col gap-2">
      {USERS.map((u) => (
        <button
          key={u.key}
          type="button"
          disabled={pending}
          onClick={() => continueAs(u.key)}
          className="flex items-center justify-between rounded-md border border-border bg-bg-inset px-3 py-2 text-[13px] font-medium text-text hover:border-accent disabled:opacity-50"
        >
          <span>{pending && pendingUser === u.key ? "Signing in…" : u.name}</span>
          <span className="text-[11px] font-normal text-text-faint">{u.role}</span>
        </button>
      ))}
      {error && <p className="text-[12px] text-danger">{error}</p>}
    </div>
  );
}
