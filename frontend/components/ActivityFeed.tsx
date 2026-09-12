import type { AuditEvent } from "@/lib/types";
import { formatRelative, formatDateTime, shortId } from "@/lib/format";
import { EmptyState } from "./Layout";

const EVENT_LABELS: Record<string, string> = {
  "agent.created": "Agent created",
  "agent_version.created": "Version created",
  "agent_version.became_candidate": "Became evaluated - gates passed",
  "skill.created": "Skill created",
  "skill_version.published": "Skill version published",
  "capability.granted": "Capability granted",
  "capability.revoked": "Capability revoked",
  "evaluation.requested": "Evaluation requested",
  "evaluation.completed": "Evaluation completed",
  "evaluation.failed": "Evaluation failed",
  "evaluation_policy.created": "Evaluation policy created",
  "promotion.requested": "Promotion requested",
  "promotion.approved": "Promotion approved",
  "promotion.rejected": "Promotion rejected",
  "promotion.approval_blocked_stale": "Approval blocked - stale evidence",
  "promotion.rollback": "Rollback promotion",
  "agent_version.promoted": "Became recommended",
  "agent_version.retired": "Deprecated (superseded)",
  "mcp_server.registered": "MCP server registered",
  "mcp_tool.registered": "MCP tool registered",
};

function eventTone(eventType: string): "ok" | "warn" | "danger" | "neutral" {
  if (eventType.includes("failed") || eventType.includes("rejected") || eventType.includes("blocked")) return "danger";
  if (eventType.includes("revoked") || eventType.includes("retired")) return "warn";
  if (eventType.includes("promoted") || eventType.includes("approved") || eventType.includes("completed")) return "ok";
  return "neutral";
}

const DOT_TONE: Record<string, string> = {
  ok: "bg-ok",
  warn: "bg-warn",
  danger: "bg-danger",
  neutral: "bg-text-faint",
};

export function ActivityFeed({ events, compact = false }: { events: AuditEvent[]; compact?: boolean }) {
  if (events.length === 0) {
    return <EmptyState title="No activity yet" />;
  }

  return (
    <ul className={`flex flex-col divide-y divide-border ${compact ? "-mx-4 -my-4" : ""}`}>
      {events.map((e) => {
        const tone = eventTone(e.event_type);
        return (
          <li key={e.id} className={`flex items-start gap-3 ${compact ? "px-4 py-2.5" : "py-3"}`}>
            <span className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${DOT_TONE[tone]}`} />
            <div className="flex-1 min-w-0">
              <div className="flex items-baseline justify-between gap-2">
                <p className="text-[13px] text-text">{EVENT_LABELS[e.event_type] ?? e.event_type}</p>
                <span title={formatDateTime(e.occurred_at)} className="shrink-0 text-[11px] text-text-faint">
                  {formatRelative(e.occurred_at)}
                </span>
              </div>
              <p className="mt-0.5 truncate text-[11px] text-text-faint">
                {e.entity_type} <span className="mono">{shortId(e.entity_id)}</span>
                {typeof e.payload?.reason === "string" && ` · ${e.payload.reason}`}
                {typeof e.payload?.comment === "string" && e.payload.comment && ` · "${e.payload.comment}"`}
              </p>
            </div>
          </li>
        );
      })}
    </ul>
  );
}
