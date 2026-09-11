"use client";
import { useRouter } from "next/navigation";
import { useTransition } from "react";

export function LogoutButton() {
  const router = useRouter();
  const [pending, startTransition] = useTransition();

  return (
    <button
      onClick={() =>
        startTransition(async () => {
          await fetch("/api/auth/logout", { method: "POST" });
          router.push("/login");
          router.refresh();
        })
      }
      disabled={pending}
      className="rounded-md border border-border px-2.5 py-1 text-[12px] text-text-muted transition-colors hover:border-border-strong hover:text-text disabled:opacity-50"
    >
      {pending ? "…" : "Sign out"}
    </button>
  );
}
