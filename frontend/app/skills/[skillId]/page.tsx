import Link from "next/link";
import { notFound } from "next/navigation";
import { requireSession } from "@/lib/auth";
import { apiGet } from "@/lib/api";
import type { Skill, SkillVersion, Team } from "@/lib/types";
import { PageHeader, Panel, EmptyState, ErrorPanel, KeyValue } from "@/components/Layout";
import { Badge } from "@/components/Badge";
import { formatDateTime } from "@/lib/format";

interface PinningAgentVersion {
  id: string;
  agent_id: string;
  version_label: string;
}

export default async function SkillDetailPage({ params }: { params: Promise<{ skillId: string }> }) {
  await requireSession();
  const { skillId } = await params;

  const skillResult = await apiGet<Skill>(`/v1/skills/${skillId}`);
  if (!skillResult.ok) {
    if (skillResult.status === 404) notFound();
    return <ErrorPanel message={`Couldn't load this skill: ${skillResult.message}`} />;
  }
  const skill = skillResult.data;

  const [versionsResult, teamsResult] = await Promise.all([
    apiGet<SkillVersion[]>(`/v1/skills/${skillId}/versions`),
    apiGet<Team[]>("/v1/teams"),
  ]);
  const versions = versionsResult.ok ? [...versionsResult.data].reverse() : [];
  const team = teamsResult.ok ? teamsResult.data.find((t) => t.id === skill.owner_team_id) : undefined;

  const pinnedByResults = await Promise.all(
    versions.map((v) => apiGet<PinningAgentVersion[]>(`/v1/skill-versions/${v.id}/agent-versions`))
  );
  const pinnedBy = new Map(versions.map((v, i) => [v.id, pinnedByResults[i].ok ? pinnedByResults[i].data : []]));

  return (
    <>
      <PageHeader
        breadcrumb={<Link href="/skills" className="hover:text-text">Skills</Link>}
        title={skill.name}
        subtitle={skill.description ?? undefined}
      />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <Panel title="Versions" subtitle="Immutable once published - a change is always a new version">
            {versions.length === 0 ? (
              <EmptyState title="No versions published" />
            ) : (
              <div className="flex flex-col gap-3">
                {versions.map((v) => (
                  <div key={v.id} className="rounded-md border border-border p-3">
                    <div className="flex items-center justify-between">
                      <span className="text-[13px] font-medium text-text">{v.version}</span>
                      <div className="flex gap-1">
                        {v.compatible_frameworks.map((f) => (
                          <Badge key={f} tone="neutral">{f}</Badge>
                        ))}
                      </div>
                    </div>
                    <p className="mt-1 text-[12px] text-text-muted">{v.purpose}</p>
                    <p className="mt-1 text-[11px] text-text-faint">published {formatDateTime(v.created_at)}</p>

                    <div className="mt-2 border-t border-border pt-2">
                      <p className="text-[11px] font-medium uppercase tracking-wide text-text-faint">Pinned by</p>
                      {(pinnedBy.get(v.id) ?? []).length === 0 ? (
                        <p className="mt-1 text-[12px] text-text-faint">No agent versions pin this yet.</p>
                      ) : (
                        <div className="mt-1 flex flex-wrap gap-1.5">
                          {(pinnedBy.get(v.id) ?? []).map((av) => (
                            <Link
                              key={av.id}
                              href={`/agents/${av.agent_id}/versions/${av.id}`}
                              className="mono rounded border border-border px-1.5 py-0.5 text-[11px] text-text-muted hover:border-accent/40 hover:text-accent"
                            >
                              {av.version_label}
                            </Link>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Panel>
        </div>
        <Panel title="Ownership">
          <dl className="divide-y divide-border">
            <KeyValue label="Owner team">{team?.name ?? "—"}</KeyValue>
            <KeyValue label="Skill ID"><span className="mono text-[12px] text-text-faint">{skill.id}</span></KeyValue>
          </dl>
        </Panel>
      </div>
    </>
  );
}
