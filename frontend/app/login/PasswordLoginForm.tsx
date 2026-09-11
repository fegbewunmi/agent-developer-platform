"use client";
import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";

/**
 * The real deployed sign-in form - Identity Platform email/password, not a
 * dev convenience. See app/api/auth/login-password/route.ts.
 */
export function PasswordLoginForm({ next }: { next?: string }) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    startTransition(async () => {
      const res = await fetch("/api/auth/login-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
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
    <form onSubmit={submit} className="flex flex-col gap-3">
      <div className="flex flex-col gap-1">
        <label className="text-[11px] font-medium uppercase tracking-wide text-text-faint">Email</label>
        <input
          type="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="rounded-md border border-border bg-bg-inset px-2.5 py-2 text-[13px] text-text focus:border-accent focus:outline-none"
        />
      </div>
      <div className="flex flex-col gap-1">
        <label className="text-[11px] font-medium uppercase tracking-wide text-text-faint">Password</label>
        <input
          type="password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="rounded-md border border-border bg-bg-inset px-2.5 py-2 text-[13px] text-text focus:border-accent focus:outline-none"
        />
      </div>
      <button
        type="submit"
        disabled={pending}
        className="mt-1 rounded-md bg-accent px-3 py-2 text-[13px] font-medium text-white hover:bg-accent/90 disabled:opacity-50"
      >
        {pending ? "Signing in…" : "Sign in"}
      </button>
      {error && <p className="text-[12px] text-danger">{error}</p>}
    </form>
  );
}
