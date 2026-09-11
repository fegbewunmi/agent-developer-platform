"use client";
import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import type { DevLoginUser } from "@/lib/types";
import { RoleBadge } from "@/components/Badge";

export function LoginForm({ users, next }: { users: DevLoginUser[]; next?: string }) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);

  function signIn(email: string) {
    setError(null);
    setSelected(email);
    startTransition(async () => {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({ error: "Sign-in failed" }));
        setError(body.error ?? "Sign-in failed");
        return;
      }
      router.push(next || "/overview");
      router.refresh();
    });
  }

  return (
    <div className="flex flex-col gap-2">
      {users.map((u) => (
        <button
          key={u.email}
          onClick={() => signIn(u.email)}
          disabled={pending}
          className="flex items-center justify-between rounded-md border border-border px-3 py-2.5 text-left transition-colors hover:border-accent/50 hover:bg-accent-muted/40 disabled:opacity-50"
        >
          <span>
            <span className="block text-[13px] font-medium text-text">{u.name}</span>
            <span className="block text-[11px] text-text-faint">{u.email}</span>
          </span>
          <span className="flex items-center gap-2">
            <RoleBadge role={u.role} />
            {pending && selected === u.email && <span className="text-[11px] text-text-faint">…</span>}
          </span>
        </button>
      ))}
      {error && <p className="mt-1 text-[12px] text-danger">{error}</p>}
    </div>
  );
}
