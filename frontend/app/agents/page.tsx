import Link from "next/link";
import { requireSession } from "@/lib/auth";
import { apiGet } from "@/lib/api";
import type { Agent, Team } from "@/lib/types";
import { PageHeader, Panel, ErrorPanel, EmptyState } from "@/components/Layout";
import { Badge, StageBadge } from "@/components/Badge";

export default async function AgentsPage() {
  await requireSession();
  const [agentsResult, teamsResult] = await Promise.all([apiGet<Agent[]>("/v1/agents"), apiGet<Team[]>("/v1/teams")]);

  if (!agentsResult.ok) {
    return (
      <>
        <PageHeader title="Agents" />
        <ErrorPanel message={`Couldn't load agents: ${agentsResult.message}`} />
      </>
    );
  }

  const teamNames = new Map((teamsResult.ok ? teamsResult.data : []).map((t) => [t.id, t.name]));
  const agents = agentsResult.data;

  return (
    <>
      <PageHeader title="Agents" subtitle="Every agent registered with Orion - representative seed systems and the real Incident Investigator integration." />
      <Panel>
        {agents.length === 0 ? (
          <EmptyState title="No agents registered yet" />
        ) : (
          <div className="overflow-x-auto scrollbar-thin">
            <table className="w-full text-left text-[13px]">
              <thead>
                <tr className="border-b border-border text-[11px] uppercase tracking-wide text-text-faint">
                  <th className="px-2 py-2 font-medium">Agent</th>
                  <th className="px-2 py-2 font-medium">Team</th>
                  <th className="px-2 py-2 font-medium">Recommended version</th>
                  <th className="px-2 py-2 font-medium">Lifecycle</th>
                  <th className="px-2 py-2 font-medium">Source</th>
                </tr>
              </thead>
              <tbody>
                {agents.map((agent) => (
                  <tr key={agent.id} className="border-b border-border last:border-0 hover:bg-white/[0.03]">
                    <td className="px-2 py-3">
                      <Link href={`/agents/${agent.id}`} className="font-medium text-text hover:text-accent">
                        {agent.name}
                      </Link>
                      {agent.description && <p className="mt-0.5 max-w-sm text-[12px] text-text-faint">{agent.description}</p>}
                    </td>
                    <td className="px-2 py-3 text-text-muted">{teamNames.get(agent.team_id) ?? "—"}</td>
                    <td className="px-2 py-3">
                      {agent.recommended_version_id ? (
                        <Link href={`/agents/${agent.id}/versions/${agent.recommended_version_id}`} className="mono text-text hover:text-accent">
                          {agent.recommended_version_label}
                        </Link>
                      ) : (
                        <span className="text-text-faint">none</span>
                      )}
                    </td>
                    <td className="px-2 py-3">
                      <StageCountBadges counts={agent.stage_counts ?? {}} />
                    </td>
                    <td className="px-2 py-3">
                      {agent.is_representative_data ? (
                        <Badge tone="neutral">Representative demo</Badge>
                      ) : (
                        <Badge tone="accent">Live integration</Badge>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </>
  );
}

function StageCountBadges({ counts }: { counts: Record<string, number> }) {
  const order = ["recommended", "evaluated", "evaluating", "draft", "deprecated"];
  const entries = order.filter((s) => counts[s]);
  if (entries.length === 0) return <span className="text-text-faint">—</span>;
  return (
    <div className="flex flex-wrap gap-1.5">
      {entries.map((stage) => (
        <span key={stage} className="inline-flex items-center gap-1">
          <StageBadge stage={stage as never} />
          {counts[stage] > 1 && <span className="text-[11px] text-text-faint">×{counts[stage]}</span>}
        </span>
      ))}
    </div>
  );
}
