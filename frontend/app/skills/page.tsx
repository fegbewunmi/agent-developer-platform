import Link from "next/link";
import { requireSession } from "@/lib/auth";
import { apiGet } from "@/lib/api";
import type { Skill, Team } from "@/lib/types";
import { PageHeader, Panel, EmptyState, ErrorPanel } from "@/components/Layout";

export default async function SkillsPage() {
  await requireSession();
  const [skillsResult, teamsResult] = await Promise.all([apiGet<Skill[]>("/v1/skills"), apiGet<Team[]>("/v1/teams")]);

  if (!skillsResult.ok) {
    return (
      <>
        <PageHeader title="Skills" />
        <ErrorPanel message={`Couldn't load skills: ${skillsResult.message}`} />
      </>
    );
  }

  const teamNames = new Map((teamsResult.ok ? teamsResult.data : []).map((t) => [t.id, t.name]));

  return (
    <>
      <PageHeader title="Skills" subtitle="Reusable, versioned capabilities agents pin exact versions of - never a loose dependency." />
      <Panel>
        {skillsResult.data.length === 0 ? (
          <EmptyState title="No skills registered" />
        ) : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {skillsResult.data.map((skill) => (
              <Link
                key={skill.id}
                href={`/skills/${skill.id}`}
                className="rounded-md border border-border p-3 transition-colors hover:border-border-strong hover:bg-white/[0.03]"
              >
                <p className="text-[13px] font-medium text-text">{skill.name}</p>
                <p className="mt-1 text-[12px] text-text-faint">{skill.description ?? "No description"}</p>
                <p className="mt-2 text-[11px] text-text-muted">{teamNames.get(skill.owner_team_id) ?? "—"}</p>
              </Link>
            ))}
          </div>
        )}
      </Panel>
    </>
  );
}
