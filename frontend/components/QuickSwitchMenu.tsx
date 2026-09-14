"use client";
import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";

const USERS: { key: string; name: string; role: string; email: string }[] = [
  { key: "maya", name: "Maya Chen", role: "Builder", email: "maya.chen@orioncommerce.example" },
  { key: "jordan", name: "Jordan Brooks", role: "Reviewer", email: "jordan.brooks@orioncommerce.example" },
  { key: "priya", name: "Priya Shah", role: "Reviewer", email: "priya.shah@orioncommerce.example" },
  { key: "alex", name: "Alex Rivera", role: "Admin", email: "alex.rivera@orioncommerce.example" },
];

/** Testing convenience (see app/api/auth/quick-switch/route.ts) - switches
 * the real signed-in Identity Platform session between the four seeded
 * Orion Commerce users without re-typing a password. Only rendered by Nav
 * when QUICK_SWITCH_ENABLED is set and the current user isn't the demo
 * actor. */
export function QuickSwitchMenu({ currentEmail }: { currentEmail: string }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);

  function switchTo(key: string) {
    setError(null);
    setOpen(false);
    startTransition(async () => {
      const res = await fetch("/api/auth/quick-switch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user: key }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({ error: "Could not switch users" }));
        setError(body.error ?? "Could not switch users");
        return;
      }
      router.push("/overview");
      router.refresh();
    });
  }

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        disabled={pending}
        title="Testing convenience - switches the real signed-in session, RBAC still applies"
        className="rounded-md border border-border px-2 py-1 text-[11px] text-text-faint hover:border-border-strong hover:text-text-muted disabled:opacity-50"
      >
        {pending ? "Switching…" : "Switch user"}
      </button>
      {open && (
        <div className="absolute right-0 z-30 mt-1 w-44 rounded-md border border-border bg-bg-elevated py-1 shadow-lg">
          {USERS.map((u) => (
            <button
              key={u.key}
              type="button"
              onClick={() => switchTo(u.key)}
              className="flex w-full items-center justify-between gap-2 px-2.5 py-1.5 text-left text-[12px] text-text hover:bg-white/5 disabled:opacity-50"
              disabled={u.email === currentEmail}
            >
              <span>{u.name}</span>
              <span className="text-text-faint">{u.role}</span>
            </button>
          ))}
        </div>
      )}
      {error && <p className="absolute right-0 mt-1 w-48 text-[11px] text-danger">{error}</p>}
    </div>
  );
}
