import Link from "next/link";
import type { NeedsAttentionItem } from "@/lib/types";
import { Badge } from "@/components/Badge";
import { formatRelative } from "@/lib/format";

function describe(item: NeedsAttentionItem): { title: string; href: string; tone: "warn" | "danger" } {
  switch (item.type) {
    case "pending_review":
      return {
        title: `${item.agent_name ?? "An agent"}@${item.version_label ?? "?"} is waiting for your review`,
        href: `/promotions/${item.promotion_request_id}`,
        tone: "warn",
      };
    case "blocked_promotion":
      return {
        title: `Promotion of ${item.agent_name}@${item.version_label} is blocked - evidence went stale`,
        href: `/promotions/${item.promotion_request_id}`,
        tone: "danger",
      };
    case "stale_candidate":
      return {
        title: `${item.agent_name}@${item.version_label} (candidate) has stale evaluation evidence`,
        href: `/agents/${item.agent_id}/versions/${item.agent_version_id}`,
        tone: "warn",
      };
    case "stale_production_evidence":
      return {
        title: `${item.agent_name}@${item.version_label} (production) evidence has drifted since it was evaluated`,
        href: `/agents/${item.agent_id}/versions/${item.agent_version_id}`,
        tone: "warn",
      };
    case "unhealthy_mcp":
      return {
        title: `MCP server ${item.name} is ${item.health_status}`,
        href: `/mcp/${item.mcp_server_id}`,
        tone: "danger",
      };
  }
}

export function NeedsAttentionList({ items }: { items: NeedsAttentionItem[] }) {
  return (
    <ul className="flex flex-col divide-y divide-border -mx-4 -my-4">
      {items.map((item, i) => {
        const { title, href, tone } = describe(item);
        return (
          <li key={`${item.type}-${i}`}>
            <Link href={href} className="flex items-start gap-3 px-4 py-3 transition-colors hover:bg-white/[0.03]">
              <span className={`mt-1 h-1.5 w-1.5 shrink-0 rounded-full ${tone === "danger" ? "bg-danger" : "bg-warn"}`} />
              <span className="flex-1">
                <span className="block text-[13px] text-text">{title}</span>
                {item.stale_findings && item.stale_findings.length > 0 && (
                  <span className="mt-1 flex flex-wrap gap-1">
                    {item.stale_findings.map((f) => (
                      <Badge key={f.reason} tone="warn">
                        {f.reason.replace(/_/g, " ")}
                      </Badge>
                    ))}
                  </span>
                )}
                {item.requested_at && (
                  <span className="mt-0.5 block text-[11px] text-text-faint">requested {formatRelative(item.requested_at)}</span>
                )}
              </span>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
