"use client";

import { useActionState, useState } from "react";
import Link from "next/link";
import type { Me, SkillReviewRequest, SkillVersion, SkillVersionConsumer } from "@/lib/types";
import { Badge, SkillStageBadge, SkillReviewStatusBadge } from "@/components/Badge";
import { formatDateTime, formatRelative } from "@/lib/format";
import { canDecideSkillReview, canRequestSkillReview } from "@/lib/permissions";
import { decideSkillReviewAction, requestSkillReviewAction, type ActionResult } from "./actions";

const REVIEWABLE_STAGES = new Set(["published", "deprecated"]);

export function SkillVersionCard({
  skillId,
  ownerTeamId,
  version,
  consumers,
  pendingRequest,
  latestRequest,
  currentUser,
}: {
  skillId: string;
  ownerTeamId: string;
  version: SkillVersion;
  consumers: SkillVersionConsumer[];
  pendingRequest: SkillReviewRequest | undefined;
  latestRequest: SkillReviewRequest | undefined;
  currentUser: Me;
}) {
  const stage = version.stage ?? "published";

  return (
    <div className="rounded-md border border-border p-3">
      <div className="flex items-center justify-between">
        <span className="text-[13px] font-medium text-text">{version.version}</span>
        <div className="flex items-center gap-1.5">
          {version.compatible_frameworks.map((f) => (
            <Badge key={f} tone="neutral">{f}</Badge>
          ))}
          <SkillStageBadge stage={stage} />
        </div>
      </div>
      <p className="mt-1 text-[12px] text-text-muted">{version.purpose}</p>
      <p className="mt-1 text-[11px] text-text-faint">published {formatDateTime(version.created_at)}</p>

      <div className="mt-2 border-t border-border pt-2">
        <p className="text-[11px] font-medium uppercase tracking-wide text-text-faint">Used by</p>
        {consumers.length === 0 ? (
          <p className="mt-1 text-[12px] text-text-faint">No agent versions use this yet.</p>
        ) : (
          <ul className="mt-1 flex flex-col gap-0.5">
            {consumers.map((c) => (
              <li key={c.agent_version_id}>
                <Link
                  href={`/agents/${c.agent_id}/versions/${c.agent_version_id}`}
                  className="text-[12px] text-text-muted hover:text-accent"
                >
                  {c.agent_name} <span className="mono text-text-faint">{c.version_label}</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>

      {stage !== "recommended" && (
        <div className="mt-2 border-t border-border pt-2">
          {!REVIEWABLE_STAGES.has(stage) ? null : pendingRequest ? (
            <div className="flex items-center justify-between gap-2">
              <span className="text-[12px] text-text-muted">Review requested {formatRelative(pendingRequest.requested_at)}</span>
              {canDecideSkillReview(currentUser, pendingRequest.requested_by) ? (
                <DecisionButtons skillId={skillId} requestId={pendingRequest.id} />
              ) : (
                <SkillReviewStatusBadge status="pending" />
              )}
            </div>
          ) : canRequestSkillReview(currentUser, ownerTeamId) ? (
            <RequestReviewForm skillId={skillId} skillVersionId={version.id} />
          ) : (
            <p className="text-[11.5px] text-text-faint">Not authorized to request review for this skill.</p>
          )}
          {!pendingRequest && latestRequest && latestRequest.status !== "pending" && (
            <p className="mt-1 text-[11px] text-text-faint">
              Last decision: <SkillReviewStatusBadge status={latestRequest.status} />
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function RequestReviewForm({ skillId, skillVersionId }: { skillId: string; skillVersionId: string }) {
  const [open, setOpen] = useState(false);
  const boundAction = requestSkillReviewAction.bind(null, skillId, skillVersionId);
  const [state, formAction, pending] = useActionState<ActionResult, FormData>(boundAction, { ok: true });

  if (!open) {
    return (
      <button onClick={() => setOpen(true)} className="rounded-md border border-accent/40 bg-accent-muted px-2.5 py-1 text-[12px] font-medium text-accent hover:bg-accent-muted/70">
        Request review
      </button>
    );
  }

  return (
    <form action={formAction} className="flex flex-col gap-1.5">
      <textarea
        name="reason"
        rows={2}
        placeholder="Reason (optional)"
        className="w-full resize-none rounded-md border border-border bg-bg-inset px-2 py-1.5 text-[12px] text-text placeholder:text-text-faint focus:border-accent focus:outline-none"
      />
      <div className="flex items-center gap-2">
        <button type="submit" disabled={pending} className="rounded-md bg-accent px-2.5 py-1 text-[12px] font-medium text-white hover:bg-accent/90 disabled:opacity-50">
          {pending ? "Submitting…" : "Submit"}
        </button>
        <button type="button" onClick={() => setOpen(false)} className="text-[12px] text-text-faint hover:text-text">
          Cancel
        </button>
      </div>
      {!state.ok && state.message && <span className="text-[11px] text-danger">{state.message}</span>}
    </form>
  );
}

function DecisionButtons({ skillId, requestId }: { skillId: string; requestId: string }) {
  const approveAction = decideSkillReviewAction.bind(null, skillId, requestId, "approve");
  const rejectAction = decideSkillReviewAction.bind(null, skillId, requestId, "reject");
  const [approveState, approveFormAction, approvePending] = useActionState<ActionResult, FormData>(approveAction, { ok: true });
  const [rejectState, rejectFormAction, rejectPending] = useActionState<ActionResult, FormData>(rejectAction, { ok: true });

  return (
    <div className="flex flex-col items-end gap-1">
      <div className="flex items-center gap-1.5">
        <form action={rejectFormAction}>
          <button type="submit" disabled={rejectPending || approvePending} className="rounded-md border border-danger/40 px-2 py-1 text-[11.5px] font-medium text-danger hover:bg-danger-muted disabled:opacity-50">
            Reject
          </button>
        </form>
        <form action={approveFormAction}>
          <button type="submit" disabled={rejectPending || approvePending} className="rounded-md bg-accent px-2.5 py-1 text-[11.5px] font-medium text-white hover:bg-accent/90 disabled:opacity-50">
            Recommend
          </button>
        </form>
      </div>
      {!approveState.ok && approveState.message && <span className="text-[11px] text-danger">{approveState.message}</span>}
      {!rejectState.ok && rejectState.message && <span className="text-[11px] text-danger">{rejectState.message}</span>}
    </div>
  );
}
