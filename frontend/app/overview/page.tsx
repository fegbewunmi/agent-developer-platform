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

  const { counts, needs_attention, recent_activity } = result.data;

  return (
    <>
      <PageHeader title="Overview" subtitle={`Welcome back, ${user.name.split(" ")[0]}. Here's what's happening across Orion's agents.`} />

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <StatCard label="Production agents" value={counts.production_agents} href="/agents" />
        <StatCard label="Candidate versions" value={counts.candidate_versions} href="/agents" />
        <StatCard
          label="Pending my review"
          value={counts.pending_promotion_reviews}
          tone={counts.pending_promotion_reviews > 0 ? "warn" : "neutral"}
          href="/promotions"
        />
        <StatCard
          label="Blocked promotions"
          value={counts.blocked_promotions}
          tone={counts.blocked_promotions > 0 ? "danger" : "neutral"}
          href="/promotions"
        />
        <StatCard
          label="Stale evidence"
          value={counts.stale_candidate_evidence}
          tone={counts.stale_candidate_evidence > 0 ? "warn" : "neutral"}
          href="/agents"
        />
        <StatCard
          label="Unhealthy MCP"
          value={counts.unhealthy_mcp_servers}
          tone={counts.unhealthy_mcp_servers > 0 ? "danger" : "neutral"}
          href="/mcp"
        />
      </div>

      <div className="mt-5 grid grid-cols-1 gap-4 lg:grid-cols-5">
        <div className="lg:col-span-3">
          <Panel title="Needs attention" subtitle="Real signals from live backend state - nothing here is invented.">
            {needs_attention.length === 0 ? (
              <EmptyState title="All clear" detail="No pending reviews, blocked promotions, stale evidence, or unhealthy integrations right now." />
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
