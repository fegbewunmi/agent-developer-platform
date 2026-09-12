import Link from "next/link";
import { requireSession } from "@/lib/auth";
import { apiGet } from "@/lib/api";
import type { PromotionRequest, PromotionRequestStatus } from "@/lib/types";
import { PageHeader, Panel, EmptyState, ErrorPanel } from "@/components/Layout";
import { PromotionStatusBadge, Badge } from "@/components/Badge";
import { formatRelative } from "@/lib/format";

const STATUSES: { value: PromotionRequestStatus | "all"; label: string }[] = [
  { value: "pending", label: "Pending" },
  { value: "approved", label: "Approved" },
  { value: "rejected", label: "Rejected" },
  { value: "all", label: "All" },
];

export default async function PromotionsPage({
  searchParams,
}: {
  searchParams: Promise<{ status?: string }>;
}) {
  const user = await requireSession();
  const { status } = await searchParams;
  const activeStatus: PromotionRequestStatus | "all" = (status as PromotionRequestStatus | "all" | undefined) ?? "pending";

  const query = activeStatus === "all" ? "" : `?status=${activeStatus}`;
  const result = await apiGet<PromotionRequest[]>(`/v1/promotion-requests${query}`);

  return (
    <>
      <PageHeader
        title="Reviews"
        subtitle="Every request to recommend an AgentVersion for organizational use - review queue and full history."
      />

      <div className="mb-4 flex flex-wrap gap-1.5">
        {STATUSES.map((s) => (
          <Link
            key={s.value}
            href={s.value === "pending" ? "/promotions" : `/promotions?status=${s.value}`}
            className={`rounded-full border px-2.5 py-1 text-[12px] transition-colors ${
              activeStatus === s.value
                ? "border-accent/40 bg-accent-muted text-accent"
                : "border-border text-text-muted hover:border-border-strong hover:text-text"
            }`}
          >
            {s.label}
          </Link>
        ))}
      </div>

      <Panel>
        {!result.ok ? (
          <ErrorPanel message={`Couldn't load review requests: ${result.message}`} />
        ) : result.data.length === 0 ? (
          <EmptyState title="Nothing here" detail={activeStatus === "pending" ? "No reviews are currently awaiting a decision." : undefined} />
        ) : (
          <ul className="flex flex-col divide-y divide-border -mx-4 -my-4">
            {result.data.map((r) => {
              const isMine = r.requested_by === user.id;
              return (
                <li key={r.id}>
                  <Link href={`/promotions/${r.id}`} className="flex items-center justify-between gap-3 px-4 py-3 hover:bg-white/[0.03]">
                    <div className="min-w-0">
                      <p className="text-[13px] text-text">
                        <span className="font-medium">{r.agent_name}</span>
                        <span className="mono text-text-muted">@{r.version_label}</span>
                        <span className="text-text-faint"> · {r.from_stage} → {r.to_stage}</span>
                      </p>
                      <p className="mt-0.5 text-[11.5px] text-text-faint">
                        requested by {r.requested_by_name ?? r.requested_by} {formatRelative(r.requested_at)}
                        {r.reason && ` · "${r.reason}"`}
                      </p>
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      {isMine && r.status === "pending" && <Badge tone="neutral">Your request</Badge>}
                      <PromotionStatusBadge status={r.status} />
                    </div>
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </Panel>
    </>
  );
}
