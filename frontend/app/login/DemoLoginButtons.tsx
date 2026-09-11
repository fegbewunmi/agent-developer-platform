"use client";
import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";

/**
 * "Continue as demo Builder/Reviewer" (Phase 7) - a real sign-in
 * (app/api/auth/login-demo/route.ts calls Identity Platform directly),
 * just without the visitor typing a credential. See
 * docs/phase-notes/phase-7.md for the sandbox this signs them into.
 */
export function DemoLoginButtons({ next }: { next?: string }) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const [pendingRole, setPendingRole] = useState<"builder" | "reviewer" | null>(null);

  function continueAs(role: "builder" | "reviewer") {
    setError(null);
    setPendingRole(role);
    startTransition(async () => {
      const res = await fetch("/api/auth/login-demo", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ role }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({ error: "Could not start the demo" }));
        setError(body.error ?? "Could not start the demo");
        return;
      }
      router.push(next || "/overview");
      router.refresh();
    });
  }

  return (
    <div className="flex flex-col gap-2">
      <button
        type="button"
        disabled={pending}
        onClick={() => continueAs("builder")}
        className="rounded-md border border-border bg-bg-inset px-3 py-2 text-[13px] font-medium text-text hover:border-accent disabled:opacity-50"
      >
        {pending && pendingRole === "builder" ? "Starting demo…" : "Continue as demo Builder"}
      </button>
      <button
        type="button"
        disabled={pending}
        onClick={() => continueAs("reviewer")}
        className="rounded-md border border-border bg-bg-inset px-3 py-2 text-[13px] font-medium text-text hover:border-accent disabled:opacity-50"
      >
        {pending && pendingRole === "reviewer" ? "Starting demo…" : "Continue as demo Reviewer"}
      </button>
      {error && <p className="text-[12px] text-danger">{error}</p>}
    </div>
  );
}
