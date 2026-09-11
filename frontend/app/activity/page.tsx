import { requireSession } from "@/lib/auth";
import { apiGet } from "@/lib/api";
import type { AuditEvent } from "@/lib/types";
import { PageHeader, Panel, ErrorPanel } from "@/components/Layout";
import { ActivityFeed } from "@/components/ActivityFeed";

export default async function ActivityPage({
  searchParams,
}: {
  searchParams: Promise<{ entity_type?: string }>;
}) {
  await requireSession();
  const { entity_type } = await searchParams;
  const query = entity_type ? `?entity_type=${encodeURIComponent(entity_type)}&limit=100` : "?limit=100";
  const result = await apiGet<AuditEvent[]>(`/v1/audit-events${query}`);

  const entityTypes = ["agent", "agent_version", "promotion_request", "agent_capability_grant", "mcp_server", "mcp_tool"];

  return (
    <>
      <PageHeader title="Activity" subtitle="The real AuditEvent trail - every state change this platform makes is recorded here, in the same transaction as the change itself." />
      <div className="mb-4 flex flex-wrap gap-1.5">
        <FilterLink label="All" active={!entity_type} href="/activity" />
        {entityTypes.map((t) => (
          <FilterLink key={t} label={t.replace(/_/g, " ")} active={entity_type === t} href={`/activity?entity_type=${t}`} />
        ))}
      </div>
      <Panel>
        {!result.ok ? <ErrorPanel message={`Couldn't load activity: ${result.message}`} /> : <ActivityFeed events={result.data} />}
      </Panel>
    </>
  );
}

function FilterLink({ label, active, href }: { label: string; active: boolean; href: string }) {
  return (
    <a
      href={href}
      className={`rounded-full border px-2.5 py-1 text-[12px] capitalize transition-colors ${
        active ? "border-accent/40 bg-accent-muted text-accent" : "border-border text-text-muted hover:border-border-strong hover:text-text"
      }`}
    >
      {label}
    </a>
  );
}
