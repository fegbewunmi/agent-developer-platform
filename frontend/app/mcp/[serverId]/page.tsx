import Link from "next/link";
import { notFound } from "next/navigation";
import { requireSession } from "@/lib/auth";
import { apiGet } from "@/lib/api";
import type { MCPServer, MCPTool, Team, CapabilityGrant } from "@/lib/types";
import { PageHeader, Panel, EmptyState, ErrorPanel, KeyValue } from "@/components/Layout";
import { HealthBadge, ClassificationBadge, Badge } from "@/components/Badge";
import { formatDateTime } from "@/lib/format";
import { HealthCheckButton } from "./HealthCheckButton";

export default async function MCPServerDetailPage({ params }: { params: Promise<{ serverId: string }> }) {
  await requireSession();
  const { serverId } = await params;

  const serverResult = await apiGet<MCPServer>(`/v1/mcp-servers/${serverId}`);
  if (!serverResult.ok) {
    if (serverResult.status === 404) notFound();
    return <ErrorPanel message={`Couldn't load this server: ${serverResult.message}`} />;
  }
  const server = serverResult.data;

  const [toolsResult, teamsResult] = await Promise.all([
    apiGet<MCPTool[]>(`/v1/mcp-servers/${serverId}/tools`),
    apiGet<Team[]>("/v1/teams"),
  ]);
  const tools = toolsResult.ok ? toolsResult.data : [];
  const team = teamsResult.ok ? teamsResult.data.find((t) => t.id === server.owner_team_id) : undefined;

  const grantsResults = await Promise.all(tools.map((t) => apiGet<CapabilityGrant[]>(`/v1/mcp-tools/${t.id}/grants`)));
  const grantsByTool = new Map(tools.map((t, i) => [t.id, grantsResults[i].ok ? grantsResults[i].data : []]));

  return (
    <>
      <PageHeader
        breadcrumb={<Link href="/mcp" className="hover:text-text">MCP</Link>}
        title={<span className="flex items-center gap-2">{server.name}<HealthBadge status={server.health_status} /></span>}
        subtitle={<span className="mono text-[12px]">{server.connection_ref}</span>}
        actions={<HealthCheckButton serverId={server.id} />}
      />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <Panel title="Tools" subtitle="Authorized capability, not execution-time human approval - see the Approval column">
            {tools.length === 0 ? (
              <EmptyState title="No tools registered" />
            ) : (
              <div className="flex flex-col gap-3">
                {tools.map((tool) => {
                  const grants = grantsByTool.get(tool.id) ?? [];
                  const active = grants.filter((g) => !g.revoked_at);
                  const revoked = grants.filter((g) => g.revoked_at);
                  return (
                    <div key={tool.id} className="rounded-md border border-border p-3">
                      <div className="flex items-center justify-between">
                        <span className="text-[13px] font-medium text-text">{tool.name}</span>
                        <div className="flex gap-1.5">
                          <ClassificationBadge classification={tool.classification} />
                          {tool.requires_approval ? <Badge tone="warn">Human approval required</Badge> : <Badge tone="neutral">No approval gate</Badge>}
                        </div>
                      </div>
                      {tool.description && <p className="mt-1 text-[12px] text-text-muted">{tool.description}</p>}

                      <div className="mt-2 border-t border-border pt-2">
                        <p className="text-[11px] font-medium uppercase tracking-wide text-text-faint">Agent versions with grants</p>
                        {active.length === 0 && revoked.length === 0 ? (
                          <p className="mt-1 text-[12px] text-text-faint">None yet.</p>
                        ) : (
                          <div className="mt-1 flex flex-wrap gap-1.5">
                            {active.map((g) => (
                              <Link
                                key={g.id}
                                href={`/agents/${g.agent_id}/versions/${g.agent_version_id}`}
                                className="mono rounded border border-ok/30 bg-ok-muted px-1.5 py-0.5 text-[11px] text-ok hover:underline"
                              >
                                {g.agent_name}@{g.version_label}
                              </Link>
                            ))}
                            {revoked.map((g) => (
                              <Link
                                key={g.id}
                                href={`/agents/${g.agent_id}/versions/${g.agent_version_id}`}
                                className="mono rounded border border-border px-1.5 py-0.5 text-[11px] text-text-faint line-through hover:text-text-muted"
                              >
                                {g.agent_name}@{g.version_label}
                              </Link>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </Panel>
        </div>

        <Panel title="Server">
          <dl className="divide-y divide-border">
            <KeyValue label="Owner team">{team?.name ?? "—"}</KeyValue>
            <KeyValue label="Environment">{server.environment}</KeyValue>
            <KeyValue label="Last health check">{server.last_health_check_at ? formatDateTime(server.last_health_check_at) : "never"}</KeyValue>
            <KeyValue label="Server ID"><span className="mono text-[12px] text-text-faint">{server.id}</span></KeyValue>
          </dl>
        </Panel>
      </div>
    </>
  );
}
