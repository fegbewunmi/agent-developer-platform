import Link from "next/link";
import { notFound } from "next/navigation";
import { requireSession } from "@/lib/auth";
import { apiGet } from "@/lib/api";
import type { Skill, SkillVersion, SkillVersionConsumer, SkillReviewRequest, SkillImpact, Team } from "@/lib/types";
import { PageHeader, Panel, EmptyState, ErrorPanel, KeyValue } from "@/components/Layout";
import { SkillStageBadge } from "@/components/Badge";
import { SkillVersionCard } from "./SkillVersionCard";

export default async function SkillDetailPage({ params }: { params: Promise<{ skillId: string }> }) {
  const user = await requireSession();
  const { skillId } = await params;

  const skillResult = await apiGet<Skill>(`/v1/skills/${skillId}`);
  if (!skillResult.ok) {
    if (skillResult.status === 404) notFound();
    return <ErrorPanel message={`Couldn't load this skill: ${skillResult.message}`} />;
  }
  const skill = skillResult.data;

  const [versionsResult, teamsResult, impactResult] = await Promise.all([
    apiGet<SkillVersion[]>(`/v1/skills/${skillId}/versions`),
    apiGet<Team[]>("/v1/teams"),
    apiGet<SkillImpact>(`/v1/skills/${skillId}/impact`),
  ]);
  const versions = versionsResult.ok ? [...versionsResult.data].reverse() : [];
  const team = teamsResult.ok ? teamsResult.data.find((t) => t.id === skill.owner_team_id) : undefined;
  const impact = impactResult.ok ? impactResult.data : null;

  const [consumerResults, reviewResults] = await Promise.all([
    Promise.all(versions.map((v) => apiGet<SkillVersionConsumer[]>(`/v1/skill-versions/${v.id}/agent-versions`))),
    Promise.all(versions.map((v) => apiGet<SkillReviewRequest[]>(`/v1/skill-versions/${v.id}/review-requests`))),
  ]);
  const consumersByVersion = new Map(versions.map((v, i) => [v.id, consumerResults[i].ok ? consumerResults[i].data : []]));
  const reviewsByVersion = new Map(versions.map((v, i) => [v.id, reviewResults[i].ok ? reviewResults[i].data : []]));

  const recommendedVersion = versions.find((v) => v.stage === "recommended");
  const currentImpactByAgent = new Map((impact?.current_impact ?? []).map((c) => [c.agent_version_id, c]));

  return (
    <>
      <PageHeader
        breadcrumb={<Link href="/skills" className="hover:text-text">Skills</Link>}
        title={skill.name}
        subtitle={skill.description ?? undefined}
      />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2 flex flex-col gap-4">
          {impact && impact.latest_version && impact.current_impact.length > 0 && (
            <Panel
              title={`New version available: ${impact.latest_version.version}`}
              subtitle={`${new Set(impact.current_impact.map((c) => c.agent_id)).size} agent${new Set(impact.current_impact.map((c) => c.agent_id)).size === 1 ? "" : "s"} currently using an older version`}
            >
              <ul className="flex flex-col gap-1.5">
                {impact.current_impact.map((c) => (
                  <li key={c.agent_version_id} className="flex items-center justify-between text-[12.5px]">
                    <Link href={`/agents/${c.agent_id}/versions/${c.agent_version_id}`} className="text-text hover:text-accent">
                      {c.agent_name} <span className="mono text-text-faint">{c.version_label}</span>
                    </Link>
                    <span className="text-text-faint">on {skill.name}@{c.skill_version}</span>
                  </li>
                ))}
              </ul>
              <p className="mt-2 text-[11.5px] text-text-faint">
                Consumers are never automatically upgraded - each agent above needs a new AgentVersion published that pins {skill.name}@{impact.latest_version.version} to adopt it.
              </p>
            </Panel>
          )}

          <Panel title="Versions" subtitle="Immutable once published - a change is always a new version">
            {versions.length === 0 ? (
              <EmptyState title="No versions published" />
            ) : (
              <div className="flex flex-col gap-3">
                {versions.map((v) => {
                  const requests = reviewsByVersion.get(v.id) ?? [];
                  return (
                    <SkillVersionCard
                      key={v.id}
                      skillId={skillId}
                      ownerTeamId={skill.owner_team_id}
                      version={v}
                      consumers={consumersByVersion.get(v.id) ?? []}
                      pendingRequest={requests.find((r) => r.status === "pending")}
                      latestRequest={requests[0]}
                      currentUser={user}
                    />
                  );
                })}
              </div>
            )}
          </Panel>

          {impact && impact.historical_consumers.length > 0 && (
            <Panel title="All consumers / history" subtitle="Every AgentVersion that has ever pinned an older version of this skill">
              <ul className="flex flex-col divide-y divide-border -mx-4 -my-4">
                {impact.historical_consumers.map((c) => (
                  <li key={`${c.skill_version_id}-${c.agent_version_id}`} className="flex items-center justify-between px-4 py-2 text-[12.5px]">
                    <Link href={`/agents/${c.agent_id}/versions/${c.agent_version_id}`} className="text-text-muted hover:text-accent">
                      {c.agent_name} <span className="mono text-text-faint">{c.version_label}</span>
                    </Link>
                    <span className="text-text-faint">
                      {skill.name}@{c.skill_version}
                      {currentImpactByAgent.has(c.agent_version_id) && <span className="ml-2 text-warn">still current</span>}
                    </span>
                  </li>
                ))}
              </ul>
            </Panel>
          )}
        </div>

        <div className="flex flex-col gap-4">
          <Panel title="Identity">
            <dl className="divide-y divide-border">
              <KeyValue label="Owner team">{team?.name ?? "—"}</KeyValue>
              <KeyValue label="Recommended version">
                {recommendedVersion ? (
                  <span className="flex items-center gap-1.5">
                    <span className="mono">{recommendedVersion.version}</span>
                    <SkillStageBadge stage="recommended" />
                  </span>
                ) : (
                  <span className="text-text-faint">none yet</span>
                )}
              </KeyValue>
              <KeyValue label="Versions">{versions.length}</KeyValue>
              <KeyValue label="Skill ID"><span className="mono text-[12px] text-text-faint">{skill.id}</span></KeyValue>
            </dl>
          </Panel>
        </div>
      </div>
    </>
  );
}
