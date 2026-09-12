import Link from "next/link";
import { requireSession } from "@/lib/auth";
import { apiGet } from "@/lib/api";
import type { Skill, Team } from "@/lib/types";
import { PageHeader, Panel, EmptyState, ErrorPanel } from "@/components/Layout";
import { Badge } from "@/components/Badge";

export default async function SkillsPage({
  searchParams,
}: {
  searchParams: Promise<{ search?: string; owner_team_id?: string; framework?: string }>;
}) {
  await requireSession();
  const { search, owner_team_id, framework } = await searchParams;

  const query = new URLSearchParams();
  if (search) query.set("search", search);
  if (owner_team_id) query.set("owner_team_id", owner_team_id);
  if (framework) query.set("framework", framework);
  const qs = query.toString();

  const [skillsResult, teamsResult] = await Promise.all([
    apiGet<Skill[]>(`/v1/skills${qs ? `?${qs}` : ""}`),
    apiGet<Team[]>("/v1/teams"),
  ]);

  if (!skillsResult.ok) {
    return (
      <>
        <PageHeader title="Skills" />
        <ErrorPanel message={`Couldn't load skills: ${skillsResult.message}`} />
      </>
    );
  }

  const teams = teamsResult.ok ? teamsResult.data : [];
  const teamNames = new Map(teams.map((t) => [t.id, t.name]));

  return (
    <>
      <PageHeader title="Skills" subtitle="A shared registry of reusable, versioned capabilities - discover what already exists before building something new." />

      <form method="get" className="mb-4 flex flex-wrap items-center gap-2">
        <input
          type="text"
          name="search"
          defaultValue={search}
          placeholder="Search name or description…"
          className="w-64 rounded-md border border-border bg-bg-inset px-2.5 py-1.5 text-[13px] text-text placeholder:text-text-faint focus:border-accent focus:outline-none"
        />
        <select
          name="owner_team_id"
          defaultValue={owner_team_id ?? ""}
          className="rounded-md border border-border bg-bg-inset px-2.5 py-1.5 text-[13px] text-text focus:border-accent focus:outline-none"
        >
          <option value="">Any owner</option>
          {teams.map((t) => (
            <option key={t.id} value={t.id}>{t.name}</option>
          ))}
        </select>
        <select
          name="framework"
          defaultValue={framework ?? ""}
          className="rounded-md border border-border bg-bg-inset px-2.5 py-1.5 text-[13px] text-text focus:border-accent focus:outline-none"
        >
          <option value="">Any framework</option>
          <option value="langgraph">langgraph</option>
        </select>
        <button type="submit" className="rounded-md border border-border-strong px-2.5 py-1.5 text-[13px] font-medium text-text hover:bg-white/[0.03]">
          Filter
        </button>
        {(search || owner_team_id || framework) && (
          <Link href="/skills" className="text-[12px] text-text-faint hover:text-text">Clear</Link>
        )}
      </form>

      <Panel>
        {skillsResult.data.length === 0 ? (
          <EmptyState title="No skills match" detail="Try a different search or clear the filters." />
        ) : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {skillsResult.data.map((skill) => (
              <Link
                key={skill.id}
                href={`/skills/${skill.id}`}
                className="flex flex-col rounded-md border border-border p-3 transition-colors hover:border-border-strong hover:bg-white/[0.03]"
              >
                <p className="text-[13px] font-medium text-text">{skill.name}</p>
                <p className="mt-1 line-clamp-2 text-[12px] text-text-faint">{skill.description ?? "No description"}</p>
                <div className="mt-2 flex flex-wrap items-center gap-1.5">
                  {skill.recommended_version_label ? (
                    <Badge tone="ok">Recommended: {skill.recommended_version_label}</Badge>
                  ) : (
                    <Badge tone="neutral">No recommended version</Badge>
                  )}
                  <Badge tone="neutral">{skill.version_count ?? 0} version{(skill.version_count ?? 0) === 1 ? "" : "s"}</Badge>
                </div>
                <div className="mt-2 flex items-center justify-between text-[11px] text-text-muted">
                  <span>{teamNames.get(skill.owner_team_id) ?? "—"}</span>
                  <span>Used by {skill.consuming_agent_version_count ?? 0} agent version{(skill.consuming_agent_version_count ?? 0) === 1 ? "" : "s"}</span>
                </div>
              </Link>
            ))}
          </div>
        )}
      </Panel>
    </>
  );
}
