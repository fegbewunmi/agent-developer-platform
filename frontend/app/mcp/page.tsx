import Link from "next/link";
import { requireSession } from "@/lib/auth";
import { apiGet } from "@/lib/api";
import type { MCPServer, Team } from "@/lib/types";
import { PageHeader, Panel, EmptyState, ErrorPanel } from "@/components/Layout";
import { HealthBadge } from "@/components/Badge";
import { formatRelative } from "@/lib/format";

export default async function MCPPage() {
  await requireSession();
  const [serversResult, teamsResult] = await Promise.all([apiGet<MCPServer[]>("/v1/mcp-servers"), apiGet<Team[]>("/v1/teams")]);

  if (!serversResult.ok) {
    return (
      <>
        <PageHeader title="MCP" />
        <ErrorPanel message={`Couldn't load MCP servers: ${serversResult.message}`} />
      </>
    );
  }

  const teamNames = new Map((teamsResult.ok ? teamsResult.data : []).map((t) => [t.id, t.name]));

  return (
    <>
      <PageHeader title="MCP Registry" subtitle="Model Context Protocol servers and the tools they expose - what an agent could ask for, distinct from execution-time human approval." />
      <Panel>
        {serversResult.data.length === 0 ? (
          <EmptyState title="No MCP servers registered" />
        ) : (
          <div className="overflow-x-auto scrollbar-thin">
            <table className="w-full text-left text-[13px]">
              <thead>
                <tr className="border-b border-border text-[11px] uppercase tracking-wide text-text-faint">
                  <th className="px-2 py-2 font-medium">Server</th>
                  <th className="px-2 py-2 font-medium">Owner</th>
                  <th className="px-2 py-2 font-medium">Environment</th>
                  <th className="px-2 py-2 font-medium">Health</th>
                  <th className="px-2 py-2 font-medium">Last checked</th>
                </tr>
              </thead>
              <tbody>
                {serversResult.data.map((s) => (
                  <tr key={s.id} className="border-b border-border last:border-0 hover:bg-white/[0.03]">
                    <td className="px-2 py-3">
                      <Link href={`/mcp/${s.id}`} className="font-medium text-text hover:text-accent">{s.name}</Link>
                    </td>
                    <td className="px-2 py-3 text-text-muted">{teamNames.get(s.owner_team_id) ?? "—"}</td>
                    <td className="px-2 py-3 text-text-muted">{s.environment}</td>
                    <td className="px-2 py-3"><HealthBadge status={s.health_status} /></td>
                    <td className="px-2 py-3 text-text-faint">{s.last_health_check_at ? formatRelative(s.last_health_check_at) : "never"}</td>
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
