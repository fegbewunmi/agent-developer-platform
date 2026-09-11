"use server";

import { revalidatePath } from "next/cache";
import { apiPost } from "@/lib/api";
import type { EvaluationRunReference, PromotionRequest } from "@/lib/types";

export interface ActionResult {
  ok: boolean;
  message?: string;
}

export async function requestEvaluationAction(
  agentId: string,
  versionId: string,
  _prevState: ActionResult,
  formData: FormData
): Promise<ActionResult> {
  const externalAgentVersionId = String(formData.get("external_agent_version_id") ?? "").trim();
  if (!externalAgentVersionId) {
    return { ok: false, message: "external_agent_version_id is required" };
  }

  const result = await apiPost<EvaluationRunReference>(`/v1/agent-versions/${versionId}/evaluations`, {
    external_agent_version_id: externalAgentVersionId,
  });

  if (!result.ok) {
    return { ok: false, message: result.message };
  }
  revalidatePath(`/agents/${agentId}/versions/${versionId}`);
  return { ok: true };
}

export async function requestPromotionAction(
  agentId: string,
  versionId: string,
  _prevState: ActionResult,
  formData: FormData
): Promise<ActionResult> {
  const reason = String(formData.get("reason") ?? "").trim();

  const result = await apiPost<PromotionRequest>(`/v1/agent-versions/${versionId}/promotion-requests`, {
    reason: reason || null,
  });

  if (!result.ok) {
    return { ok: false, message: result.message };
  }
  revalidatePath(`/agents/${agentId}/versions/${versionId}`);
  revalidatePath("/promotions");
  return { ok: true };
}
