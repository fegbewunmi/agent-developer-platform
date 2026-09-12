"use client";

import { useActionState, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import type { EvaluationRunReference, GateResult, Stage } from "@/lib/types";
import { Panel, EmptyState } from "@/components/Layout";
import { RunStatusBadge, PassFailBadge } from "@/components/Badge";
import { formatDateTime, formatRelative } from "@/lib/format";
import { requestEvaluationAction, type ActionResult } from "./actions";

const REQUESTABLE_STAGES: Stage[] = ["draft", "evaluating"];

export function EvaluationSection({
  agentId,
  versionId,
  stage,
  evaluations,
  latestEvaluation,
  gates,
  canRequest,
  defaultExternalAgentVersionId,
}: {
  agentId: string;
  versionId: string;
  stage: Stage;
  evaluations: EvaluationRunReference[];
  latestEvaluation: EvaluationRunReference | null;
  gates: GateResult[];
  canRequest: boolean;
  /** Pre-fills the evaluation target so a human never has to know or type an
   * agent-eval AgentVersion UUID themselves. Two sources, resolved by the
   * caller: the public demo's fixed safe target (Phase 7), or - for a
   * real, CI-published version - the live target its own publish already
   * registered in agent-eval (Phase 8, stored in AgentVersion.provenance).
   * null when neither is known, which only happens for a manually-created
   * version with no CI provenance - there the field stays free text. */
  defaultExternalAgentVersionId?: string | null;
}) {
  const router = useRouter();
  const isInFlight = latestEvaluation && (latestEvaluation.status === "requested" || latestEvaluation.status === "dispatched");

  // Evaluation runs asynchronously on the real backend (agent-eval's own
  // POST /runs can take minutes) - poll for status while one is in flight,
  // never fake a progress percentage, just reflect real state transitions.
  useEffect(() => {
    if (!isInFlight) return;
    const interval = setInterval(() => router.refresh(), 4000);
    return () => clearInterval(interval);
  }, [isInFlight, router]);

  return (
    <Panel
      title="Evaluation"
      subtitle="Automated gates, computed once per run - never a single blended score"
      actions={
        canRequest && REQUESTABLE_STAGES.includes(stage) ? (
          <RequestEvaluationForm agentId={agentId} versionId={versionId} defaultExternalAgentVersionId={defaultExternalAgentVersionId} />
        ) : undefined
      }
    >
      {evaluations.length === 0 ? (
        <EmptyState title="No evaluation runs yet" detail={canRequest ? "Request one above." : undefined} />
      ) : (
        <>
          {latestEvaluation && (
            <div className="mb-4 rounded-md border border-border bg-bg-inset p-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <RunStatusBadge status={latestEvaluation.status} />
                  <span className="text-[12px] text-text-faint">requested {formatRelative(latestEvaluation.requested_at)}</span>
                </div>
                {latestEvaluation.external_run_id && (
                  <span className="text-[11px] text-text-faint mono">agent-eval run {latestEvaluation.external_run_id.slice(0, 8)}</span>
                )}
              </div>

              {latestEvaluation.status === "failed" && (
                <p className="mt-2 text-[12px] text-danger">{latestEvaluation.error_message ?? "Evaluation failed"}</p>
              )}

              {latestEvaluation.status === "completed" && (
                <>
                  <div className="mt-3 flex flex-wrap gap-3 text-[12px] text-text-muted">
                    <span>{latestEvaluation.n_cases_success}/{latestEvaluation.n_cases_total} cases succeeded</span>
                    {latestEvaluation.dimension_stats?.map((d) => (
                      <span key={d.dimension}>
                        {d.dimension}: {d.mean_score !== null ? d.mean_score.toFixed(2) : "n/a"}
                      </span>
                    ))}
                  </div>

                  <div className="mt-3 flex flex-col gap-2">
                    {gates.length === 0 ? (
                      <p className="text-[12px] text-text-faint">No gate results recorded.</p>
                    ) : (
                      gates.map((g) => <GateRow key={g.id} gate={g} />)
                    )}
                  </div>
                </>
              )}
            </div>
          )}

          {evaluations.length > 1 && (
            <details>
              <summary className="cursor-pointer text-[12px] text-text-muted hover:text-text">
                {evaluations.length - 1} earlier run{evaluations.length - 1 > 1 ? "s" : ""}
              </summary>
              <ul className="mt-2 flex flex-col gap-1.5">
                {evaluations.slice(1).map((e) => (
                  <li key={e.id} className="flex items-center justify-between text-[12px] text-text-muted">
                    <span>{formatDateTime(e.requested_at)}</span>
                    <RunStatusBadge status={e.status} />
                  </li>
                ))}
              </ul>
            </details>
          )}
        </>
      )}
    </Panel>
  );
}

export function GateRow({ gate }: { gate: GateResult }) {
  return (
    <div className="flex items-start justify-between gap-3 rounded-md border border-border px-3 py-2">
      <div className="min-w-0">
        <p className="text-[12.5px] font-medium text-text">{gate.criterion}</p>
        <p className="mt-0.5 text-[11px] text-text-faint">
          Required: {gate.expected} &middot; Observed: {gate.actual}
        </p>
        {!gate.passed && gate.reason && <p className="mt-1 text-[11px] text-danger">{gate.reason}</p>}
      </div>
      <PassFailBadge passed={gate.passed} />
    </div>
  );
}

function RequestEvaluationForm({
  agentId,
  versionId,
  defaultExternalAgentVersionId,
}: {
  agentId: string;
  versionId: string;
  defaultExternalAgentVersionId?: string | null;
}) {
  const [showAdvanced, setShowAdvanced] = useState(false);
  const boundAction = requestEvaluationAction.bind(null, agentId, versionId);
  const [state, formAction, pending] = useActionState<ActionResult, FormData>(boundAction, { ok: true });

  return (
    <form action={formAction} className="flex flex-col items-end gap-1.5">
      <div className="flex items-center gap-2">
        {/* Phase 9: the real evaluation target - the demo's fixed safe one,
            or nothing (the backend resolves it from this version's own
            provenance) - is never shown as a raw foreign ID in the normal
            flow. See app/services/evaluations.py::_resolve_external_agent_version_id. */}
        {defaultExternalAgentVersionId && (
          <input type="hidden" name="external_agent_version_id" value={defaultExternalAgentVersionId} />
        )}
        <button type="submit" disabled={pending} className="rounded-md bg-accent px-2.5 py-1 text-[12px] font-medium text-white hover:bg-accent/90 disabled:opacity-50">
          {pending ? "Running…" : "Run evaluation"}
        </button>
      </div>
      {!state.ok && state.message && <span className="max-w-[280px] text-right text-[11px] text-danger">{state.message}</span>}
      {!defaultExternalAgentVersionId && (
        <details className="text-[11px] text-text-faint" open={showAdvanced} onToggle={(e) => setShowAdvanced(e.currentTarget.open)}>
          <summary className="cursor-pointer hover:text-text-muted">Advanced: specify a target manually</summary>
          {showAdvanced && (
            <input
              name="external_agent_version_id"
              placeholder="agent-eval AgentVersion ID"
              title="Only needed if this version has no known evaluation target - overrides the (nonexistent) automatic resolution."
              className="mt-1 w-56 rounded-md border border-border bg-bg-inset px-2 py-1 text-[12px] text-text placeholder:text-text-faint focus:border-accent focus:outline-none"
            />
          )}
        </details>
      )}
    </form>
  );
}
