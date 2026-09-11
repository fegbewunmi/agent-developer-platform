"use client";
import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";

export function HealthCheckButton({ serverId }: { serverId: string }) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);

  return (
    <div className="flex items-center gap-2">
      <button
        onClick={() =>
          startTransition(async () => {
            setError(null);
            const res = await fetch(`/api/proxy/v1/mcp-servers/${serverId}/health-check`, { method: "POST" });
            if (!res.ok) {
              const body = await res.json().catch(() => ({ detail: "Health check failed" }));
              setError(body.detail ?? "Health check failed");
              return;
            }
            router.refresh();
          })
        }
        disabled={pending}
        className="rounded-md border border-border px-2.5 py-1 text-[12px] text-text-muted transition-colors hover:border-border-strong hover:text-text disabled:opacity-50"
      >
        {pending ? "Checking…" : "Check health now"}
      </button>
      {error && <span className="text-[11px] text-danger">{error}</span>}
    </div>
  );
}
