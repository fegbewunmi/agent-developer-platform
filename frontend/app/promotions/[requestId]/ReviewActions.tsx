"use client";

import { useActionState, useState } from "react";
import { approvePromotionAction, rejectPromotionAction, type ActionResult } from "./actions";

export function ReviewActions({ requestId }: { requestId: string }) {
  const [mode, setMode] = useState<"idle" | "approve" | "reject">("idle");
  const boundApprove = approvePromotionAction.bind(null, requestId);
  const boundReject = rejectPromotionAction.bind(null, requestId);
  const [approveState, approveAction, approvePending] = useActionState<ActionResult, FormData>(boundApprove, { ok: true });
  const [rejectState, rejectAction, rejectPending] = useActionState<ActionResult, FormData>(boundReject, { ok: true });

  if (mode === "idle") {
    return (
      <div className="flex gap-2">
        <button onClick={() => setMode("approve")} className="rounded-md bg-ok px-3 py-1.5 text-[12.5px] font-medium text-black hover:opacity-90">
          Approve
        </button>
        <button onClick={() => setMode("reject")} className="rounded-md border border-danger/40 px-3 py-1.5 text-[12.5px] font-medium text-danger hover:bg-danger-muted">
          Reject
        </button>
      </div>
    );
  }

  if (mode === "approve") {
    return (
      <form action={approveAction} className="flex flex-col gap-2 rounded-md border border-ok/30 bg-ok-muted/40 p-3">
        <p className="text-[12.5px] font-medium text-text">Approve this promotion</p>
        <textarea name="comment" rows={2} placeholder="Comment (optional)" className="resize-none rounded-md border border-border bg-bg-inset px-2 py-1.5 text-[12.5px] text-text placeholder:text-text-faint focus:border-accent focus:outline-none" />
        <div className="flex gap-2">
          <button type="submit" disabled={approvePending} className="rounded-md bg-ok px-3 py-1.5 text-[12.5px] font-medium text-black hover:opacity-90 disabled:opacity-50">
            {approvePending ? "Approving…" : "Confirm approval"}
          </button>
          <button type="button" onClick={() => setMode("idle")} className="text-[12px] text-text-faint hover:text-text">Cancel</button>
        </div>
        {!approveState.ok && approveState.message && <p className="text-[11.5px] text-danger">{approveState.message}</p>}
      </form>
    );
  }

  return (
    <form action={rejectAction} className="flex flex-col gap-2 rounded-md border border-danger/30 bg-danger-muted/40 p-3">
      <p className="text-[12.5px] font-medium text-text">Reject this promotion</p>
      <textarea name="comment" rows={2} placeholder="Reason (recommended)" className="resize-none rounded-md border border-border bg-bg-inset px-2 py-1.5 text-[12.5px] text-text placeholder:text-text-faint focus:border-accent focus:outline-none" />
      <div className="flex gap-2">
        <button type="submit" disabled={rejectPending} className="rounded-md border border-danger/40 px-3 py-1.5 text-[12.5px] font-medium text-danger hover:bg-danger-muted disabled:opacity-50">
          {rejectPending ? "Rejecting…" : "Confirm rejection"}
        </button>
        <button type="button" onClick={() => setMode("idle")} className="text-[12px] text-text-faint hover:text-text">Cancel</button>
      </div>
      {!rejectState.ok && rejectState.message && <p className="text-[11.5px] text-danger">{rejectState.message}</p>}
    </form>
  );
}
