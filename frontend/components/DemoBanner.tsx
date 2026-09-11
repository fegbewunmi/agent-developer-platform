import Link from "next/link";
import { apiGet } from "@/lib/api";
import type { Me } from "@/lib/types";
import { DemoBannerSwitchButton } from "./DemoBannerSwitchButton";

interface DemoStatus {
  demo_agent_id: string;
  demo_agent_name: string;
  demo_team_id: string;
}

/**
 * Shown site-wide only to the two public demo identities (Phase 7) - never
 * to a real Orion Commerce user. Server-rendered so the "is this a demo
 * user" check is the same real GET /v1/me team_id the rest of auth relies
 * on (lib/auth.ts), not a client-side guess.
 */
export async function DemoBanner({ user }: { user: Me }) {
  const status = await apiGet<DemoStatus>("/v1/demo/status");
  if (!status.ok || status.data.demo_team_id !== user.team_id) return null;

  const otherRole = user.role === "builder" ? "reviewer" : "builder";
  const otherLabel = otherRole === "builder" ? "Builder" : "Reviewer";
  const thisLabel = user.role === "builder" ? "Builder" : "Reviewer";

  return (
    <div className="border-b border-accent/30 bg-accent/10 px-5 py-2">
      <div className="mx-auto flex max-w-[1400px] flex-wrap items-center gap-x-4 gap-y-1 text-[12px] text-text">
        <span className="font-medium">Public demo</span>
        <span className="text-text-muted">
          You&apos;re signed in as the demo {thisLabel} - every action here is real and contained to{" "}
          <Link href={`/agents/${status.data.demo_agent_id}`} className="underline hover:text-accent">
            {status.data.demo_agent_name}
          </Link>
          .
        </span>
        <div className="ml-auto">
          <DemoBannerSwitchButton role={otherRole} label={otherLabel} />
        </div>
      </div>
    </div>
  );
}
