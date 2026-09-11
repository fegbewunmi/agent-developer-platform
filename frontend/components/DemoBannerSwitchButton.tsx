"use client";
import { useTransition } from "react";
import { useRouter } from "next/navigation";

/** The role-switch half of the demo banner - see DemoBanner.tsx. */
export function DemoBannerSwitchButton({ role, label }: { role: "builder" | "reviewer"; label: string }) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();

  function switchRole() {
    startTransition(async () => {
      const res = await fetch("/api/auth/login-demo", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ role }),
      });
      if (res.ok) {
        router.push("/overview");
        router.refresh();
      }
    });
  }

  return (
    <button
      type="button"
      disabled={pending}
      onClick={switchRole}
      className="whitespace-nowrap rounded-md border border-accent/40 px-2.5 py-1 text-[12px] font-medium text-accent hover:bg-accent/10 disabled:opacity-50"
    >
      {pending ? "Switching…" : `Switch to demo ${label}`}
    </button>
  );
}
