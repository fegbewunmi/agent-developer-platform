import Link from "next/link";
import { notFound } from "next/navigation";
import { requireSession, canRequestEvaluation, canRequestPromotion } from "@/lib/auth";
import { apiGet } from "@/lib/api";
import type {
  Agent,
  AgentVersionDetail,
  AgentVersionManifest,
  CapabilityGrant,
  MCPTool,
  SkillVersion,
  EvaluationRunReference,
  GateResult,
  Candidacy,
  PromotionRequest,
} from "@/lib/types";
import { PageHeader, Panel, KeyValue, EmptyState, ErrorPanel } from "@/components/Layout";
import { StageBadge, ClassificationBadge, Badge } from "@/components/Badge";
import { formatDateTime, shortId } from "@/lib/format";
import { EvaluationSection } from "./EvaluationSection";
import { PromotionSection } from "./PromotionSection";

export default async function VersionDetailPage({
  params,
}: {
  params: Promise<{ agentId: string; versionId: string }>;
}) {
  const user = await requireSession();
  const { agentId, versionId } = await params;

  const versionResult = await apiGet<AgentVersionDetail>(`/v1/agent-versions/${versionId}`);
  if (!versionResult.ok) {
    if (versionResult.status === 404) notFound();
    return <ErrorPanel message={`Couldn't load this version: ${versionResult.message}`} />;
  }
  const version = versionResult.data;

  const [agentResult, manifestResult, grantsResult, skillsSettled, evaluationsResult, candidacyResult, promotionsResult, demoStatusResult] = await Promise.all([
    apiGet<Agent>(`/v1/agents/${agentId}`),
    apiGet<AgentVersionManifest>(`/v1/agent-versions/${versionId}/manifest`),
    apiGet<CapabilityGrant[]>(`/v1/agent-versions/${versionId}/capability-grants?include_revoked=true`),
    Promise.all(version.pinned_skill_version_ids.map((id) => apiGet<SkillVersion>(`/v1/skill-versions/${id}`))),
    apiGet<EvaluationRunReference[]>(`/v1/agent-versions/${versionId}/evaluations`),
    apiGet<Candidacy>(`/v1/agent-versions/${versionId}/candidacy`),
    apiGet<PromotionRequest[]>(`/v1/agent-versions/${versionId}/promotion-requests`),
    apiGet<{ demo_agent_id: string; demo_external_agent_version_id: string | null }>("/v1/demo/status"),
  ]);

  const agent = agentResult.ok ? agentResult.data : null;
  const manifest = manifestResult.ok ? manifestResult.data.manifest : null;
  const grants = grantsResult.ok ? grantsResult.data : [];
  const skillVersions = skillsSettled.filter((r) => r.ok).map((r) => (r as { ok: true; data: SkillVersion }).data);
  const evaluations = evaluationsResult.ok ? evaluationsResult.data : [];
  const latestEvaluation = evaluations[0] ?? null;
  const candidacy = candidacyResult.ok ? candidacyResult.data : null;
  const promotionRequests = promotionsResult.ok ? promotionsResult.data : [];

  const gatesResult = latestEvaluation
    ? await apiGet<GateResult[]>(`/v1/evaluations/${latestEvaluation.id}/gates`)
    : null;
  const gates = gatesResult?.ok ? gatesResult.data : [];

  const demoDefaultExternalAgentVersionId =
    demoStatusResult.ok && demoStatusResult.data.demo_agent_id === agentId
      ? demoStatusResult.data.demo_external_agent_version_id
      : null;

  const toolIds = [...new Set(grants.map((g) => g.mcp_tool_id))];
  const toolResults = await Promise.all(toolIds.map((id) => apiGet<MCPTool>(`/v1/mcp-tools/${id}`)));
  const toolsById = new Map(toolIds.map((id, i) => [id, toolResults[i].ok ? (toolResults[i] as { ok: true; data: MCPTool }).data : null]));

  return (
    <>
      <PageHeader
        breadcrumb={
          <>
            <Link href="/agents" className="hover:text-text">Agents</Link>
            {" / "}
            <Link href={`/agents/${agentId}`} className="hover:text-text">{agent?.name ?? shortId(agentId)}</Link>
          </>
        }
        title={
          <span className="flex items-center gap-2 mono">
            {version.version_label}
            <StageBadge stage={version.stage} />
          </span>
        }
        subtitle={<span className="mono text-[12px]">content hash {version.content_hash.slice(0, 16)}…</span>}
      />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2 flex flex-col gap-4">
          <Panel title="Configuration">
            <dl className="grid grid-cols-2 divide-y divide-border sm:grid-cols-3">
              <KeyValue label="Framework">{String(manifest?.agent?.framework ?? "—")}</KeyValue>
              <KeyValue label="Model provider">{String(manifest?.model?.provider ?? "—")}</KeyValue>
              <KeyValue label="Model">{String(manifest?.model?.name ?? "—")}</KeyValue>
              <KeyValue label="Source ref">{version.source_ref ?? "—"}</KeyValue>
              <KeyValue label="Created">{formatDateTime(version.created_at)}</KeyValue>
              <KeyValue label="Evaluation policy">{String(manifest?.evaluation?.policy ?? "—")}</KeyValue>
            </dl>
            <details className="mt-3">
              <summary className="cursor-pointer text-[12px] text-text-muted hover:text-text">View full immutable manifest</summary>
              <pre className="mt-2 max-h-96 overflow-auto rounded-md border border-border bg-bg-inset p-3 text-[11px] leading-relaxed mono scrollbar-thin">
                {JSON.stringify(manifest, null, 2)}
              </pre>
            </details>
          </Panel>

          <Panel title="Skills" subtitle="Exact SkillVersions pinned to this AgentVersion">
            {skillVersions.length === 0 ? (
              <EmptyState title="No skills pinned" />
            ) : (
              <ul className="flex flex-col divide-y divide-border -mx-4 -my-4">
                {skillVersions.map((sv) => (
                  <li key={sv.id} className="px-4 py-3">
                    <div className="flex items-center justify-between">
                      <Link href={`/skills/${sv.skill_id}`} className="text-[13px] font-medium text-text hover:text-accent">
                        {sv.version}
                      </Link>
                      <div className="flex gap-1">
                        {sv.compatible_frameworks.map((f) => (
                          <Badge key={f} tone="neutral">{f}</Badge>
                        ))}
                      </div>
                    </div>
                    <p className="mt-0.5 text-[12px] text-text-faint">{sv.purpose}</p>
                  </li>
                ))}
              </ul>
            )}
          </Panel>

          <Panel title="MCP access" subtitle="Capabilities granted to this AgentVersion">
            {grants.length === 0 ? (
              <EmptyState title="No capability grants" />
            ) : (
              <div className="overflow-x-auto scrollbar-thin">
                <table className="w-full text-left text-[13px]">
                  <thead>
                    <tr className="border-b border-border text-[11px] uppercase tracking-wide text-text-faint">
                      <th className="px-2 py-2 font-medium">Tool</th>
                      <th className="px-2 py-2 font-medium">Classification</th>
                      <th className="px-2 py-2 font-medium">Approval</th>
                      <th className="px-2 py-2 font-medium">Status</th>
                      <th className="px-2 py-2 font-medium">Granted</th>
                    </tr>
                  </thead>
                  <tbody>
                    {grants.map((g) => {
                      const tool = toolsById.get(g.mcp_tool_id);
                      return (
                        <tr key={g.id} className="border-b border-border last:border-0">
                          <td className="px-2 py-2.5">
                            {tool ? (
                              <Link href={`/mcp/${tool.mcp_server_id}`} className="font-medium text-text hover:text-accent">
                                {tool.name}
                              </Link>
                            ) : (
                              <span className="text-text-faint mono">{shortId(g.mcp_tool_id)}</span>
                            )}
                          </td>
                          <td className="px-2 py-2.5">{tool && <ClassificationBadge classification={tool.classification} />}</td>
                          <td className="px-2 py-2.5">
                            {tool?.requires_approval ? <Badge tone="warn">Human approval required</Badge> : <Badge tone="neutral">No approval gate</Badge>}
                          </td>
                          <td className="px-2 py-2.5">
                            {g.revoked_at ? <Badge tone="danger">Revoked</Badge> : <Badge tone="ok">Active</Badge>}
                          </td>
                          <td className="px-2 py-2.5 text-text-faint">{formatDateTime(g.granted_at)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>

          <EvaluationSection
            agentId={agentId}
            versionId={versionId}
            stage={version.stage}
            evaluations={evaluations}
            latestEvaluation={latestEvaluation}
            gates={gates}
            canRequest={agent ? canRequestEvaluation(user, agent.team_id) : false}
            defaultExternalAgentVersionId={demoDefaultExternalAgentVersionId}
          />
        </div>

        <div className="flex flex-col gap-4">
          <PromotionSection
            agentId={agentId}
            versionId={versionId}
            stage={version.stage}
            candidacy={candidacy}
            promotionRequests={promotionRequests}
            recommendedVersionId={agent?.recommended_version_id ?? null}
            recommendedVersionLabel={agent?.recommended_version_label ?? null}
            canRequest={agent ? canRequestPromotion(user, agent.team_id) : false}
          />
        </div>
      </div>
    </>
  );
}
