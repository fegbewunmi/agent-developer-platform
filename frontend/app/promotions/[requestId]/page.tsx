import Link from "next/link";
import { notFound } from "next/navigation";
import { requireSession, canDecidePromotion } from "@/lib/auth";
import { apiGet } from "@/lib/api";
import type { PromotionRequest, Candidacy, GateResult, EvaluationPolicy, CapabilityGrant, MCPTool, Agent } from "@/lib/types";
import { PageHeader, Panel, KeyValue, EmptyState, ErrorPanel } from "@/components/Layout";
import { Badge, PromotionStatusBadge, PassFailBadge, ClassificationBadge } from "@/components/Badge";
import { formatDateTime } from "@/lib/format";
import { ReviewActions } from "./ReviewActions";

export default async function PromotionReviewPage({ params }: { params: Promise<{ requestId: string }> }) {
  const user = await requireSession();
  const { requestId } = await params;

  const result = await apiGet<PromotionRequest>(`/v1/promotion-requests/${requestId}`);
  if (!result.ok) {
    if (result.status === 404) notFound();
    return <ErrorPanel message={`Couldn't load this promotion request: ${result.message}`} />;
  }
  const request = result.data;

  const [gatesResult, policyResult, candidacyResult, grantsResult, agentResult] = await Promise.all([
    apiGet<GateResult[]>(`/v1/evaluations/${request.evaluation_run_reference_id}/gates`),
    apiGet<EvaluationPolicy>(`/v1/evaluation-policies/${request.evaluation_policy_id}`),
    request.status === "pending" ? apiGet<Candidacy>(`/v1/agent-versions/${request.agent_version_id}/candidacy`) : Promise.resolve(null),
    apiGet<CapabilityGrant[]>(`/v1/agent-versions/${request.agent_version_id}/capability-grants`),
    request.agent_id ? apiGet<Agent>(`/v1/agents/${request.agent_id}`) : Promise.resolve(null),
  ]);

  const gates = gatesResult.ok ? gatesResult.data : [];
  const policy = policyResult.ok ? policyResult.data : null;
  const liveCandidacy = candidacyResult && candidacyResult.ok ? candidacyResult.data : null;
  const grants = grantsResult.ok ? grantsResult.data : [];
  const agent = agentResult && agentResult.ok ? agentResult.data : null;

  const toolResults = await Promise.all(grants.map((g) => apiGet<MCPTool>(`/v1/mcp-tools/${g.mcp_tool_id}`)));
  const tools = toolResults.filter((r) => r.ok).map((r) => (r as { ok: true; data: MCPTool }).data);

  const canDecide = canDecidePromotion(user, request.requested_by);
  const isRollback = request.from_stage === "retired";

  return (
    <>
      <PageHeader
        breadcrumb={<Link href="/promotions" className="hover:text-text">Promotions</Link>}
        title={
          <span className="flex items-center gap-2">
            {request.agent_name}
            <span className="mono text-text-muted">@{request.version_label}</span>
            {isRollback && <Badge tone="accent">Rollback</Badge>}
            <PromotionStatusBadge status={request.status} />
          </span>
        }
        subtitle={`${request.from_stage} → ${request.to_stage}`}
        actions={
          request.status === "pending" ? (
            canDecide ? (
              <ReviewActions requestId={request.id} />
            ) : (
              <span className="text-[12px] text-text-faint">
                {user.id === request.requested_by ? "You cannot approve your own request." : "You're not authorized to review this."}
              </span>
            )
          ) : undefined
        }
      />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2 flex flex-col gap-4">
          <Panel title="Request">
            <dl className="grid grid-cols-2 divide-y divide-border sm:grid-cols-3">
              <KeyValue label="Requested by">{request.requested_by_name ?? request.requested_by}</KeyValue>
              <KeyValue label="Requested">{formatDateTime(request.requested_at)}</KeyValue>
              <KeyValue label="Version">
                <Link href={`/agents/${request.agent_id}/versions/${request.agent_version_id}`} className="mono text-accent hover:underline">
                  {request.version_label}
                </Link>
              </KeyValue>
              <KeyValue label="Production at request time">
                {request.production_version_id_at_request ? (
                  <span className="mono">{request.production_version_id_at_request.slice(0, 8)}…</span>
                ) : (
                  <span className="text-text-faint">none</span>
                )}
              </KeyValue>
              <KeyValue label="Current production">
                {agent?.production_version_id ? (
                  <Link href={`/agents/${agent.id}/versions/${agent.production_version_id}`} className="mono text-accent hover:underline">
                    {agent.production_version_label}
                  </Link>
                ) : (
                  <span className="text-text-faint">none</span>
                )}
              </KeyValue>
              <KeyValue label="Evaluation policy">{policy ? `${policy.name}@${policy.version}` : "—"}</KeyValue>
            </dl>
            {request.reason && (
              <div className="mt-3 rounded-md border border-border bg-bg-inset px-3 py-2">
                <p className="text-[11px] font-medium uppercase tracking-wide text-text-faint">Reason</p>
                <p className="mt-0.5 text-[12.5px] text-text">{request.reason}</p>
              </div>
            )}
          </Panel>

          <Panel title="Gate results" subtitle="Cited on this request - immutable evidence">
            {gates.length === 0 ? (
              <EmptyState title="No gate results" />
            ) : (
              <div className="flex flex-col gap-2">
                {gates.map((g) => (
                  <div key={g.id} className="flex items-start justify-between gap-3 rounded-md border border-border px-3 py-2">
                    <div>
                      <p className="text-[12.5px] font-medium text-text">{g.criterion}</p>
                      <p className="mt-0.5 text-[11px] text-text-faint">Required: {g.expected} &middot; Observed: {g.actual}</p>
                    </div>
                    <PassFailBadge passed={g.passed} />
                  </div>
                ))}
              </div>
            )}
          </Panel>

          <Panel title="Capabilities" subtitle="Active capability grants on this version">
            {tools.length === 0 ? (
              <EmptyState title="None" />
            ) : (
              <div className="flex flex-wrap gap-1.5">
                {tools.map((t) => (
                  <span key={t.id} className="flex items-center gap-1 rounded border border-border px-2 py-1 text-[12px]">
                    {t.name}
                    <ClassificationBadge classification={t.classification} />
                  </span>
                ))}
              </div>
            )}
          </Panel>
        </div>

        <div className="flex flex-col gap-4">
          <Panel title="Eligible when requested" subtitle="Frozen at request time">
            <FreshnessBlock snapshot={request.freshness_snapshot} />
          </Panel>

          {request.status === "pending" ? (
            <Panel title="Eligible now" subtitle="Live, recomputed - this is what approval will re-check">
              {liveCandidacy ? (
                <FreshnessBlock
                  snapshot={{
                    historically_passed: liveCandidacy.historically_passed,
                    currently_eligible: liveCandidacy.currently_eligible,
                    stale_findings: liveCandidacy.stale_findings,
                  }}
                />
              ) : (
                <EmptyState title="Unavailable" />
              )}
            </Panel>
          ) : (
            request.decision && (
              <Panel title="Eligible when reviewed" subtitle="Frozen at decision time">
                <FreshnessBlock snapshot={request.decision.freshness_snapshot_at_decision} />
                {request.decision.comment && (
                  <div className="mt-3 rounded-md border border-border bg-bg-inset px-3 py-2">
                    <p className="text-[11px] font-medium uppercase tracking-wide text-text-faint">
                      {request.decision.decision === "approve" ? "Approval" : "Rejection"} comment
                    </p>
                    <p className="mt-0.5 text-[12.5px] text-text">{request.decision.comment}</p>
                  </div>
                )}
                <p className="mt-2 text-[11.5px] text-text-faint">
                  Decided by {request.decision.decided_by_name ?? request.decision.decided_by} on {formatDateTime(request.decision.decided_at)}
                </p>
              </Panel>
            )
          )}
        </div>
      </div>
    </>
  );
}

function FreshnessBlock({ snapshot }: { snapshot: { historically_passed: boolean; currently_eligible: boolean; stale_findings: { reason: string; detail: string }[] } | null }) {
  if (!snapshot) return <EmptyState title="Not available" />;
  return (
    <div className="flex flex-col gap-2.5">
      <div className="flex items-center justify-between">
        <span className="text-[12px] text-text-muted">Evaluation</span>
        {snapshot.historically_passed ? <Badge tone="ok">Passed</Badge> : <Badge tone="danger">Not passed</Badge>}
      </div>
      <div className="flex items-center justify-between">
        <span className="text-[12px] text-text-muted">Eligibility</span>
        {snapshot.currently_eligible ? <Badge tone="ok">Eligible</Badge> : <Badge tone="warn">Stale</Badge>}
      </div>
      {snapshot.stale_findings.length > 0 && (
        <ul className="flex flex-col gap-1 border-t border-border pt-2">
          {snapshot.stale_findings.map((f) => (
            <li key={f.reason} className="text-[11.5px] text-text break-words">
              <span className="font-medium capitalize">{f.reason.replace(/_/g, " ")}</span>
              <span className="text-text-faint break-all"> — {f.detail}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
