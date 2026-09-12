import Link from "next/link";
import { requireSession } from "@/lib/auth";
import { apiGet } from "@/lib/api";
import type { DashboardSummary } from "@/lib/types";
import { PageHeader, StatCard, Panel, EmptyState, ErrorPanel } from "@/components/Layout";
import { NeedsAttentionList } from "./NeedsAttentionList";
import { ActivityFeed } from "@/components/ActivityFeed";

export default async function OverviewPage() {
  const user = await requireSession();
  const result = await apiGet<DashboardSummary>("/v1/dashboard/summary");

  if (!result.ok) {
    return (
      <>
        <PageHeader title="Overview" subtitle={`Welcome back, ${user.name.split(" ")[0]}.`} />
        <ErrorPanel message={`Couldn't load the dashboard: ${result.message}`} />
      </>
    );
  }

  const { counts, needs_attention, recent_activity, ecosystem, updates } = result.data;

  return (
    <>
      <PageHeader title="Overview" subtitle={`Welcome back, ${user.name.split(" ")[0]}. Here's what's happening across Orion's shared registry.`} />

      <p className="mb-2 text-[11px] font-medium uppercase tracking-wide text-text-faint">Developer ecosystem</p>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard label="Agents" value={ecosystem.agent_count} href="/agents" />
        <StatCard label="Skills" value={ecosystem.skill_count} href="/skills" />
        <StatCard label="Publishing teams" value={ecosystem.publishing_team_count} href="/agents" />
        <StatCard
          label="Pending skill reviews"
          value={ecosystem.pending_skill_reviews}
          tone={ecosystem.pending_skill_reviews > 0 ? "warn" : "neutral"}
          href="/skills"
        />
      </div>

      <p className="mb-2 mt-5 text-[11px] font-medium uppercase tracking-wide text-text-faint">Governance</p>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <StatCard label="Recommended agents" value={counts.recommended_agents} href="/agents" />
        <StatCard label="Evaluated versions" value={counts.evaluated_versions} href="/agents" />
        <StatCard
          label="Pending my review"
          value={counts.pending_reviews}
          tone={counts.pending_reviews > 0 ? "warn" : "neutral"}
          href="/promotions"
        />
        <StatCard
          label="Blocked reviews"
          value={counts.blocked_reviews}
          tone={counts.blocked_reviews > 0 ? "danger" : "neutral"}
          href="/promotions"
        />
        <StatCard
          label="Stale evidence"
          value={counts.stale_evaluated_evidence}
          tone={counts.stale_evaluated_evidence > 0 ? "warn" : "neutral"}
          href="/agents"
        />
        <StatCard
          label="Unhealthy MCP"
          value={counts.unhealthy_mcp_servers}
          tone={counts.unhealthy_mcp_servers > 0 ? "danger" : "neutral"}
          href="/mcp"
        />
      </div>

      {updates.length > 0 && (
        <div className="mt-5">
          <Panel title="Updates" subtitle="New capabilities published to the registry, and what they affect">
            <ul className="flex flex-col divide-y divide-border -mx-4 -my-4">
              {updates.map((u, i) => (
                <li key={i} className="px-4 py-2.5 text-[12.5px]">
                  {u.type === "skill_update_available" ? (
                    <Link href={`/skills/${u.skill_id}`} className="flex items-center justify-between gap-2 hover:text-accent">
                      <span className="text-text">
                        {u.skill_name} <span className="text-text-faint">{u.latest_version} published</span>
                      </span>
                      <span className="text-text-faint">
                        {u.agents_on_older_version} agent{u.agents_on_older_version === 1 ? "" : "s"} on an older version
                      </span>
                    </Link>
                  ) : (
                    <Link href={`/agents/${u.agent_id}/versions/${u.agent_version_id}`} className="flex items-center justify-between gap-2 hover:text-accent">
                      <span className="text-text">
                        {u.agent_name} <span className="mono text-text-faint">{u.version_label}</span> published from GitHub
                      </span>
                      <span className="text-text-faint">awaiting evaluation</span>
                    </Link>
                  )}
                </li>
              ))}
            </ul>
          </Panel>
        </div>
      )}

      <div className="mt-5 grid grid-cols-1 gap-4 lg:grid-cols-5">
        <div className="lg:col-span-3">
          <Panel title="Needs attention" subtitle="Real signals from live backend state - nothing here is invented.">
            {needs_attention.length === 0 ? (
              <EmptyState title="All clear" detail="No pending reviews, blocked reviews, stale evidence, or unhealthy integrations right now." />
            ) : (
              <NeedsAttentionList items={needs_attention} />
            )}
          </Panel>
        </div>
        <div className="lg:col-span-2">
          <Panel title="Recent activity" subtitle="Live AuditEvent trail">
            <ActivityFeed events={recent_activity} compact />
          </Panel>
        </div>
      </div>
    </>
  );
}
