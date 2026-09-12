import Link from "next/link";
import { notFound } from "next/navigation";
import { requireSession } from "@/lib/auth";
import { apiGet } from "@/lib/api";
import type { Agent, AgentVersion, AgentVersionDetail, Team, PromotionRequest, AuditEvent } from "@/lib/types";
import { PageHeader, Panel, KeyValue, EmptyState, ErrorPanel } from "@/components/Layout";
import { Badge, StageBadge, PromotionStatusBadge } from "@/components/Badge";
import { ActivityFeed } from "@/components/ActivityFeed";
import { formatDateTime, formatRelative } from "@/lib/format";

export default async function AgentDetailPage({ params }: { params: Promise<{ agentId: string }> }) {
  await requireSession();
  const { agentId } = await params;

  const agentResult = await apiGet<Agent>(`/v1/agents/${agentId}`);
  if (!agentResult.ok) {
    if (agentResult.status === 404) notFound();
    return <ErrorPanel message={`Couldn't load this agent: ${agentResult.message}`} />;
  }
  const agent = agentResult.data;

  const [versionsResult, teamsResult, historyResult] = await Promise.all([
    apiGet<AgentVersion[]>(`/v1/agents/${agentId}/versions`),
    apiGet<Team[]>("/v1/teams"),
    apiGet<PromotionRequest[]>(`/v1/agents/${agentId}/promotion-history`),
  ]);

  const versions = versionsResult.ok ? [...versionsResult.data].reverse() : [];
  const team = teamsResult.ok ? teamsResult.data.find((t) => t.id === agent.team_id) : undefined;
  const history = historyResult.ok ? historyResult.data : [];

  const stageResults = await Promise.all(versions.map((v) => apiGet<AgentVersionDetail>(`/v1/agent-versions/${v.id}`)));
  const stageByVersion = new Map(versions.map((v, i) => [v.id, stageResults[i].ok ? stageResults[i].data.stage : null]));

  // Recent activity: the Agent's own events, plus its most recent version's -
  // a bounded, real query (not a synthetic merge across everything this
  // agent has ever touched).
  const recentVersionIds = versions.slice(0, 3).map((v) => v.id);
  const activityResults = await Promise.all([
    apiGet<AuditEvent[]>(`/v1/audit-events?entity_type=agent&entity_id=${agentId}&limit=10`),
    ...recentVersionIds.map((id) => apiGet<AuditEvent[]>(`/v1/audit-events?entity_type=agent_version&entity_id=${id}&limit=10`)),
  ]);
  const activity = activityResults
    .flatMap((r) => (r.ok ? r.data : []))
    .sort((a, b) => new Date(b.occurred_at).getTime() - new Date(a.occurred_at).getTime())
    .slice(0, 10);

  return (
    <>
      <PageHeader
        breadcrumb={<Link href="/agents" className="hover:text-text">Agents</Link>}
        title={
          <span className="flex items-center gap-2">
            {agent.name}
            {agent.is_representative_data ? <Badge tone="neutral">Representative demo</Badge> : <Badge tone="accent">Live integration</Badge>}
          </span>
        }
        subtitle={agent.description ?? undefined}
      />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2 flex flex-col gap-4">
          <Panel title="Version history">
            {versions.length === 0 ? (
              <EmptyState title="No versions yet" />
            ) : (
              <div className="overflow-x-auto scrollbar-thin">
                <table className="w-full text-left text-[13px]">
                  <thead>
                    <tr className="border-b border-border text-[11px] uppercase tracking-wide text-text-faint">
                      <th className="px-2 py-2 font-medium">Version</th>
                      <th className="px-2 py-2 font-medium">Stage</th>
                      <th className="px-2 py-2 font-medium">Created</th>
                      <th className="px-2 py-2 font-medium">Source</th>
                    </tr>
                  </thead>
                  <tbody>
                    {versions.map((v) => (
                      <tr key={v.id} className="border-b border-border last:border-0 hover:bg-white/[0.03]">
                        <td className="px-2 py-2.5">
                          <Link href={`/agents/${agentId}/versions/${v.id}`} className="mono font-medium text-text hover:text-accent">
                            {v.version_label}
                          </Link>
                          {v.id === agent.recommended_version_id && <span className="ml-2 text-[11px] text-ok">current recommended</span>}
                        </td>
                        <td className="px-2 py-2.5">
                          {stageByVersion.get(v.id) ? <StageBadge stage={stageByVersion.get(v.id)!} /> : <span className="text-text-faint">—</span>}
                        </td>
                        <td className="px-2 py-2.5 text-text-muted">{formatDateTime(v.created_at)}</td>
                        <td className="px-2 py-2.5 text-text-faint mono">{v.source_ref ?? v.content_hash.slice(0, 10)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>

          <Panel title="Review history" subtitle="Why is the current version actually recommended?">
            {history.length === 0 ? (
              <EmptyState title="No promotion requests yet" />
            ) : (
              <ul className="flex flex-col divide-y divide-border -mx-4 -my-4">
                {[...history]
                  .sort((a, b) => new Date(b.requested_at).getTime() - new Date(a.requested_at).getTime())
                  .map((r) => (
                    <li key={r.id}>
                      <Link href={`/promotions/${r.id}`} className="flex items-start justify-between gap-3 px-4 py-3 hover:bg-white/[0.03]">
                        <div>
                          <p className="text-[13px] text-text">
                            <span className="mono">{r.version_label}</span>: {r.from_stage} → {r.to_stage}
                          </p>
                          <p className="mt-0.5 text-[11px] text-text-faint">
                            requested by {r.requested_by_name ?? r.requested_by} {formatRelative(r.requested_at)}
                            {r.decision && ` · decided by ${r.decision.decided_by_name ?? r.decision.decided_by}`}
                          </p>
                        </div>
                        <PromotionStatusBadge status={r.status} />
                      </Link>
                    </li>
                  ))}
              </ul>
            )}
          </Panel>
        </div>

        <div className="flex flex-col gap-4">
          <Panel title="Identity">
            <dl className="divide-y divide-border">
              <KeyValue label="Team">{team?.name ?? "—"}</KeyValue>
              <KeyValue label="Latest published version">
                {agent.latest_version_id ? (
                  <Link href={`/agents/${agentId}/versions/${agent.latest_version_id}`} className="mono text-accent hover:underline">
                    {agent.latest_version_label}
                  </Link>
                ) : (
                  <span className="text-text-faint">none</span>
                )}
              </KeyValue>
              <KeyValue label="Recommended version">
                {agent.recommended_version_id ? (
                  <Link href={`/agents/${agentId}/versions/${agent.recommended_version_id}`} className="mono text-accent hover:underline">
                    {agent.recommended_version_label}
                  </Link>
                ) : (
                  <span className="text-text-faint">none</span>
                )}
              </KeyValue>
              <KeyValue label="Agent ID"><span className="mono text-[12px] text-text-faint">{agent.id}</span></KeyValue>
            </dl>
          </Panel>

          <Panel title="Version publishing">
            {agent.requires_ci_provenance ? (
              <div className="flex flex-col gap-2">
                <Badge tone="accent">CI managed</Badge>
                <p className="text-[12px] text-text-muted">
                  New versions are published automatically from the source repository through CI - real source
                  provenance is required for every version, so there is no manual "create version" flow for this agent.
                </p>
              </div>
            ) : (
              <div className="flex flex-col gap-2">
                <Badge tone="neutral">Manual / representative</Badge>
                <p className="text-[12px] text-text-muted">
                  {agent.is_representative_data
                    ? "Representative platform data - versions are seeded for demonstration, not published by a real pipeline."
                    : "Not yet integrated with a CI pipeline - versions are created directly against the API."}
                </p>
              </div>
            )}
          </Panel>

          <Panel title="Recent activity">
            <ActivityFeed events={activity} compact />
          </Panel>
        </div>
      </div>
    </>
  );
}
