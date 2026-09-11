"use client";

import { useActionState, useState } from "react";
import Link from "next/link";
import type { Candidacy, PromotionRequest, Stage } from "@/lib/types";
import { Panel, EmptyState } from "@/components/Layout";
import { Badge, PromotionStatusBadge } from "@/components/Badge";
import { formatRelative } from "@/lib/format";
import { requestPromotionAction, type ActionResult } from "./actions";

const PROMOTABLE_STAGES: Stage[] = ["candidate", "retired"];

export function PromotionSection({
  agentId,
  versionId,
  stage,
  candidacy,
  promotionRequests,
  productionVersionId,
  productionVersionLabel,
  canRequest,
}: {
  agentId: string;
  versionId: string;
  stage: Stage;
  candidacy: Candidacy | null;
  promotionRequests: PromotionRequest[];
  productionVersionId: string | null;
  productionVersionLabel: string | null;
  canRequest: boolean;
}) {
  const pending = promotionRequests.find((r) => r.status === "pending");
  const isPromotable = PROMOTABLE_STAGES.includes(stage);
  const isRollback = stage === "retired";

  return (
    <>
      <Panel title="Freshness & eligibility">
        {!candidacy ? (
          <EmptyState title="Not computed" />
        ) : (
          <FreshnessDisplay candidacy={candidacy} />
        )}
      </Panel>

      <Panel title={isRollback ? "Rollback" : "Promotion"} subtitle={isRollback ? "Promote this retired version back to production" : "Request production promotion"}>
        {stage === "production" ? (
          <p className="text-[12.5px] text-text-muted">This version is currently in production.</p>
        ) : !isPromotable ? (
          <p className="text-[12.5px] text-text-faint">Only candidate or retired versions can be promoted.</p>
        ) : pending ? (
          <div className="rounded-md border border-warn/30 bg-warn-muted px-3 py-2.5">
            <p className="text-[12.5px] text-text">
              A promotion request is <Link href={`/promotions/${pending.id}`} className="font-medium text-accent hover:underline">pending review</Link>.
            </p>
          </div>
        ) : (
          <>
            {productionVersionId && (
              <p className="mb-3 text-[12px] text-text-faint">
                Current production version: <Link href={`/agents/${agentId}/versions/${productionVersionId}`} className="mono text-text hover:text-accent">{productionVersionLabel}</Link>
              </p>
            )}
            {!candidacy?.currently_eligible ? (
              <div className="rounded-md border border-danger/30 bg-danger-muted px-3 py-2.5 text-[12.5px] text-danger">
                Not currently eligible - a promotion request would be rejected. See stale reasons above.
              </div>
            ) : canRequest ? (
              <RequestPromotionForm agentId={agentId} versionId={versionId} isRollback={isRollback} />
            ) : (
              <p className="text-[12.5px] text-text-faint">You&apos;re not authorized to request a promotion for this agent.</p>
            )}
          </>
        )}
      </Panel>

      <Panel title="Promotion requests" subtitle="For this version">
        {promotionRequests.length === 0 ? (
          <EmptyState title="None yet" />
        ) : (
          <ul className="flex flex-col divide-y divide-border -mx-4 -my-4">
            {promotionRequests.map((r) => (
              <li key={r.id}>
                <Link href={`/promotions/${r.id}`} className="flex items-center justify-between gap-2 px-4 py-2.5 hover:bg-white/[0.03]">
                  <span className="text-[12.5px] text-text-muted">{formatRelative(r.requested_at)}</span>
                  <PromotionStatusBadge status={r.status} />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </>
  );
}

export function FreshnessDisplay({ candidacy }: { candidacy: Candidacy }) {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <span className="text-[12.5px] text-text-muted">Evaluation</span>
        {candidacy.historically_passed ? <Badge tone="ok">Passed</Badge> : <Badge tone="danger">Not passed</Badge>}
      </div>
      <div className="flex items-center justify-between">
        <span className="text-[12.5px] text-text-muted">Current eligibility</span>
        {candidacy.currently_eligible ? <Badge tone="ok">Eligible</Badge> : <Badge tone="warn">Stale</Badge>}
      </div>
      {candidacy.historically_passed && !candidacy.currently_eligible && (
        <p className="rounded-md border border-warn/20 bg-warn-muted/50 px-2.5 py-2 text-[11.5px] text-text-muted">
          This evaluation genuinely passed. It is not being marked as failed - the evidence has simply drifted
          since then, so it can no longer support a new promotion without re-verification.
        </p>
      )}
      {candidacy.stale_findings.length > 0 && (
        <div>
          <p className="mb-1 text-[11px] font-medium uppercase tracking-wide text-text-faint">Reason</p>
          <ul className="flex flex-col gap-1">
            {candidacy.stale_findings.map((f) => (
              <li key={f.reason} className="text-[12px] text-text break-words">
                <span className="font-medium capitalize">{f.reason.replace(/_/g, " ")}</span>
                <span className="text-text-faint break-all"> — {f.detail}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function RequestPromotionForm({ agentId, versionId, isRollback }: { agentId: string; versionId: string; isRollback: boolean }) {
  const [open, setOpen] = useState(false);
  const boundAction = requestPromotionAction.bind(null, agentId, versionId);
  const [state, formAction, pending] = useActionState<ActionResult, FormData>(boundAction, { ok: true });

  if (!open) {
    return (
      <button onClick={() => setOpen(true)} className="w-full rounded-md bg-accent px-3 py-2 text-[13px] font-medium text-white hover:bg-accent/90">
        {isRollback ? "Request rollback" : "Request promotion"}
      </button>
    );
  }

  return (
    <form action={formAction} className="flex flex-col gap-2">
      <textarea
        name="reason"
        rows={3}
        placeholder="Reason for this request (optional)"
        className="w-full resize-none rounded-md border border-border bg-bg-inset px-2.5 py-2 text-[12.5px] text-text placeholder:text-text-faint focus:border-accent focus:outline-none"
      />
      <div className="flex items-center gap-2">
        <button type="submit" disabled={pending} className="rounded-md bg-accent px-3 py-1.5 text-[12.5px] font-medium text-white hover:bg-accent/90 disabled:opacity-50">
          {pending ? "Submitting…" : "Submit request"}
        </button>
        <button type="button" onClick={() => setOpen(false)} className="text-[12px] text-text-faint hover:text-text">
          Cancel
        </button>
      </div>
      {!state.ok && state.message && <p className="text-[11.5px] text-danger">{state.message}</p>}
    </form>
  );
}
