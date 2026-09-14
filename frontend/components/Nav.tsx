import Link from "next/link";
import { apiGet } from "@/lib/api";
import type { Me } from "@/lib/types";
import { RoleBadge } from "./Badge";
import { LogoutButton } from "./LogoutButton";
import { QuickSwitchMenu } from "./QuickSwitchMenu";

const LINKS = [
  { href: "/overview", label: "Overview" },
  { href: "/agents", label: "Agents" },
  { href: "/skills", label: "Skills" },
  { href: "/mcp", label: "MCP" },
  { href: "/promotions", label: "Reviews" },
  { href: "/activity", label: "Activity" },
];

export async function Nav({ user }: { user: Me }) {
  // Same "is this the demo actor" check DemoBanner.tsx uses - quick-switch
  // must never be reachable from the public demo session, only real Orion
  // Commerce users, and only when explicitly enabled for testing.
  let showQuickSwitch = false;
  if (process.env.QUICK_SWITCH_ENABLED) {
    const status = await apiGet<{ demo_team_id: string }>("/v1/demo/status");
    showQuickSwitch = !status.ok || status.data.demo_team_id !== user.team_id;
  }

  return (
    <header className="sticky top-0 z-20 border-b border-border bg-bg/95 backdrop-blur">
      <div className="mx-auto flex h-12 max-w-[1400px] items-center gap-6 px-5">
        <Link href="/overview" className="flex items-center gap-2 text-[13px] font-semibold tracking-tight text-text">
          <span className="flex h-5 w-5 items-center justify-center rounded bg-accent text-[11px] font-bold text-white">O</span>
          Orion
        </Link>
        <nav className="flex items-center gap-1 text-[13px]">
          {LINKS.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className="rounded-md px-2.5 py-1.5 text-text-muted transition-colors hover:bg-white/5 hover:text-text"
            >
              {link.label}
            </Link>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-3">
          <div className="flex items-center gap-2 text-[12px] text-text-muted">
            <span>{user.name}</span>
            <RoleBadge role={user.role} />
          </div>
          {showQuickSwitch && <QuickSwitchMenu currentEmail={user.email} />}
          <LogoutButton />
        </div>
      </div>
    </header>
  );
}
