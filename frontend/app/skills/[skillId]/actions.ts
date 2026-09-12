"use server";

import { revalidatePath } from "next/cache";
import { apiPost } from "@/lib/api";
import type { SkillReviewDecision, SkillReviewRequest } from "@/lib/types";

export interface ActionResult {
  ok: boolean;
  message?: string;
}

export async function requestSkillReviewAction(
  skillId: string,
  skillVersionId: string,
  _prevState: ActionResult,
  formData: FormData
): Promise<ActionResult> {
  const reason = String(formData.get("reason") ?? "").trim();

  const result = await apiPost<SkillReviewRequest>(`/v1/skill-versions/${skillVersionId}/review-requests`, {
    reason: reason || null,
  });

  if (!result.ok) {
    return { ok: false, message: result.message };
  }
  revalidatePath(`/skills/${skillId}`);
  return { ok: true };
}

export async function decideSkillReviewAction(
  skillId: string,
  requestId: string,
  decision: "approve" | "reject",
  _prevState: ActionResult,
  formData: FormData
): Promise<ActionResult> {
  const comment = String(formData.get("comment") ?? "").trim();

  const result = await apiPost<SkillReviewDecision>(`/v1/skill-review-requests/${requestId}/${decision}`, {
    comment: comment || null,
  });

  if (!result.ok) {
    return { ok: false, message: result.message };
  }
  revalidatePath(`/skills/${skillId}`);
  return { ok: true };
}
