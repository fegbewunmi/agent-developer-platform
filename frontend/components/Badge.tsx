import { ReactNode } from "react";
import type { Stage, MCPHealthStatus, MCPClassification, EvaluationRunStatus, PromotionRequestStatus } from "@/lib/types";

type Tone = "neutral" | "accent" | "ok" | "warn" | "danger";

const toneClasses: Record<Tone, string> = {
  neutral: "bg-white/5 text-text-muted border-border-strong",
  accent: "bg-accent-muted text-accent border-accent/30",
  ok: "bg-ok-muted text-ok border-ok/30",
  warn: "bg-warn-muted text-warn border-warn/30",
  danger: "bg-danger-muted text-danger border-danger/30",
};

export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium leading-tight whitespace-nowrap ${toneClasses[tone]}`}
    >
      {children}
    </span>
  );
}

const STAGE_TONE: Record<Stage, Tone> = {
  draft: "neutral",
  evaluating: "accent",
  evaluated: "warn",
  recommended: "ok",
  deprecated: "neutral",
};

const STAGE_LABEL: Record<Stage, string> = {
  draft: "Draft",
  evaluating: "Evaluating",
  evaluated: "Evaluated",
  recommended: "Recommended",
  deprecated: "Deprecated",
};

export function StageBadge({ stage }: { stage: Stage }) {
  return <Badge tone={STAGE_TONE[stage]}>{STAGE_LABEL[stage]}</Badge>;
}

const HEALTH_TONE: Record<MCPHealthStatus, Tone> = {
  healthy: "ok",
  degraded: "warn",
  unavailable: "danger",
  unknown: "neutral",
};

export function HealthBadge({ status }: { status: MCPHealthStatus }) {
  return <Badge tone={HEALTH_TONE[status]}>{status[0].toUpperCase() + status.slice(1)}</Badge>;
}

export function ClassificationBadge({ classification }: { classification: MCPClassification }) {
  return <Badge tone={classification === "write" ? "warn" : "neutral"}>{classification === "write" ? "Write" : "Read"}</Badge>;
}

const RUN_STATUS_TONE: Record<EvaluationRunStatus, Tone> = {
  requested: "neutral",
  dispatched: "accent",
  completed: "ok",
  failed: "danger",
};

const RUN_STATUS_LABEL: Record<EvaluationRunStatus, string> = {
  requested: "Queued",
  dispatched: "Running",
  completed: "Completed",
  failed: "Failed",
};

export function RunStatusBadge({ status }: { status: EvaluationRunStatus }) {
  return <Badge tone={RUN_STATUS_TONE[status]}>{RUN_STATUS_LABEL[status]}</Badge>;
}

const PROMO_STATUS_TONE: Record<PromotionRequestStatus, Tone> = {
  pending: "warn",
  approved: "ok",
  rejected: "danger",
  withdrawn: "neutral",
};

export function PromotionStatusBadge({ status }: { status: PromotionRequestStatus }) {
  return <Badge tone={PROMO_STATUS_TONE[status]}>{status[0].toUpperCase() + status.slice(1)}</Badge>;
}

export function PassFailBadge({ passed }: { passed: boolean }) {
  return passed ? <Badge tone="ok">Passed</Badge> : <Badge tone="danger">Failed</Badge>;
}

export function EligibilityBadge({ eligible }: { eligible: boolean }) {
  return eligible ? <Badge tone="ok">Eligible</Badge> : <Badge tone="warn">Stale</Badge>;
}

export function RoleBadge({ role }: { role: string }) {
  const tone: Tone = role === "admin" ? "accent" : role === "reviewer" ? "warn" : "neutral";
  return <Badge tone={tone}>{role[0].toUpperCase() + role.slice(1)}</Badge>;
}
