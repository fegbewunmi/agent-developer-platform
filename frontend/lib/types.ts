// Mirrors backend/app/api/*.py's actual dict serializers - not a separate
// domain model. If a field is added/renamed on the backend, this is the one
// place the frontend needs to follow. Never invent a field that doesn't come
// from a real endpoint.

export type Role = "viewer" | "builder" | "reviewer" | "admin";

export type Stage = "draft" | "evaluating" | "candidate" | "production" | "retired";

export type MCPClassification = "read" | "write";

export type MCPHealthStatus = "healthy" | "degraded" | "unavailable" | "unknown";

export type EvaluationRunStatus = "requested" | "dispatched" | "completed" | "failed";

export type PromotionRequestStatus = "pending" | "approved" | "rejected" | "withdrawn";

export type PromotionDecisionType = "approve" | "reject";

export interface Me {
  id: string;
  name: string;
  email: string;
  team_id: string;
  role: Role;
}

export interface Team {
  id: string;
  name: string;
  slack_channel: string | null;
}

export interface Agent {
  id: string;
  name: string;
  team_id: string;
  description: string | null;
  is_representative_data: boolean;
  production_version_id?: string | null;
  production_version_label?: string | null;
  stage_counts?: Record<string, number>;
}

export interface AgentVersion {
  id: string;
  agent_id: string;
  version_label: string;
  content_hash: string;
  source_ref: string | null;
  created_by: string;
  created_at: string;
}

export interface AgentVersionDetail extends AgentVersion {
  stage: Stage;
  pinned_skill_version_ids: string[];
}

export interface AgentVersionManifest {
  agent_version_id: string;
  content_hash: string;
  manifest: {
    agent?: { name?: string; version?: string; framework?: string };
    model?: { provider?: string; name?: string; [key: string]: unknown };
    skills?: unknown[];
    mcp?: { servers?: unknown[]; tools?: unknown[] };
    evaluation?: { policy?: string };
    [key: string]: unknown;
  };
}

export interface Skill {
  id: string;
  name: string;
  owner_team_id: string;
  description: string | null;
}

export interface SkillVersion {
  id: string;
  skill_id: string;
  version: string;
  owner_user_id: string;
  purpose: string;
  input_contract: string | null;
  output_contract: string | null;
  implementation_ref: string | null;
  compatible_frameworks: string[];
  created_at: string;
}

export interface MCPServer {
  id: string;
  name: string;
  environment: string;
  owner_team_id: string;
  connection_ref: string;
  health_status: MCPHealthStatus;
  last_health_check_at: string | null;
}

export interface MCPTool {
  id: string;
  mcp_server_id: string;
  name: string;
  description: string | null;
  io_schema: unknown;
  classification: MCPClassification;
  requires_approval: boolean;
}

export interface CapabilityGrant {
  id: string;
  agent_version_id: string;
  mcp_tool_id: string;
  granted_by: string;
  granted_at: string;
  revoked_by: string | null;
  revoked_at: string | null;
  // present only on the reverse-lookup (GET /v1/mcp-tools/{id}/grants)
  agent_id?: string;
  agent_name?: string;
  version_label?: string;
}

export interface EvaluationPolicy {
  id: string;
  name: string;
  version: string;
  thresholds: Record<string, { min_mean?: number }>;
  required_evaluator_keys: Record<string, string>;
  max_new_regressions: number;
  zero_failure_tags: string[];
  min_completion_rate: string;
  dataset_key: string;
  created_by: string;
  created_at: string;
}

export interface DimensionStat {
  dimension: string;
  mean_score: number | null;
  n: number;
  n_not_applicable: number;
}

export interface EvaluationRunReference {
  id: string;
  agent_version_id: string;
  evaluation_policy_id: string;
  external_run_id: string | null;
  external_agent_version_id: string;
  external_dataset_id: string | null;
  requested_by: string;
  requested_at: string;
  status: EvaluationRunStatus;
  dataset_snapshot_hash: string | null;
  dimension_stats: DimensionStat[] | null;
  n_cases_total: number | null;
  n_cases_success: number | null;
  n_cases_error: number | null;
  error_message: string | null;
  capability_grant_snapshot_hash: string | null;
  completed_at: string | null;
}

export interface GateResult {
  id: string;
  evaluation_run_reference_id: string;
  gate_type: string;
  criterion: string;
  expected: string;
  actual: string;
  passed: boolean;
  reason: string | null;
  evidence_ref: Record<string, unknown> | null;
  evaluated_at: string;
}

export interface StaleFinding {
  reason: string;
  detail: string;
}

export interface Candidacy {
  agent_version_id: string;
  current_stage: string;
  evaluation_run_reference_id: string | null;
  historically_passed: boolean;
  currently_eligible: boolean;
  stale_findings: StaleFinding[];
}

export interface FreshnessSnapshot {
  historically_passed: boolean;
  currently_eligible: boolean;
  current_stage: string;
  evaluation_run_reference_id: string | null;
  stale_findings: StaleFinding[];
  checked_at: string;
}

export interface PromotionDecision {
  id: string;
  promotion_request_id: string;
  decision: PromotionDecisionType;
  decided_by: string;
  decided_by_name?: string;
  decided_at: string;
  comment: string | null;
  freshness_snapshot_at_decision: FreshnessSnapshot | null;
}

export interface PromotionRequest {
  id: string;
  agent_version_id: string;
  from_stage: Stage;
  to_stage: Stage;
  requested_by: string;
  requested_by_name?: string;
  requested_at: string;
  evaluation_run_reference_id: string;
  evaluation_policy_id: string;
  capability_grant_snapshot_hash: string | null;
  production_version_id_at_request: string | null;
  freshness_snapshot: FreshnessSnapshot | null;
  status: PromotionRequestStatus;
  reason: string | null;
  decision: PromotionDecision | null;
  // context enrichment (list/history/queue endpoints only)
  agent_id?: string;
  agent_name?: string;
  version_label?: string;
}

export interface AuditEvent {
  id: string;
  event_type: string;
  entity_type: string;
  entity_id: string;
  actor: string;
  occurred_at: string;
  payload: Record<string, unknown>;
}

export interface NeedsAttentionItem {
  type: "stale_candidate" | "blocked_promotion" | "pending_review" | "stale_production_evidence" | "unhealthy_mcp";
  agent_id?: string;
  agent_name?: string;
  agent_version_id?: string;
  version_label?: string;
  promotion_request_id?: string;
  from_stage?: string;
  requested_at?: string;
  stale_findings?: StaleFinding[];
  mcp_server_id?: string;
  name?: string;
  health_status?: string;
}

export interface DashboardSummary {
  counts: {
    production_agents: number;
    candidate_versions: number;
    pending_promotion_reviews: number;
    blocked_promotions: number;
    stale_candidate_evidence: number;
    unhealthy_mcp_servers: number;
  };
  needs_attention: NeedsAttentionItem[];
  recent_activity: AuditEvent[];
}

export interface DevLoginUser {
  email: string;
  name: string;
  role: Role;
  team_id: string;
}

export interface ApiErrorBody {
  detail: string;
}
