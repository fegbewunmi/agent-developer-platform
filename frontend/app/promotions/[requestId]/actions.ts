"use server";

import { revalidatePath } from "next/cache";
import { apiPost } from "@/lib/api";
import type { PromotionDecision } from "@/lib/types";

export interface ActionResult {
  ok: boolean;
  message?: string;
}

export async function approvePromotionAction(requestId: string, _prevState: ActionResult, formData: FormData): Promise<ActionResult> {
  const comment = String(formData.get("comment") ?? "").trim();
  const result = await apiPost<PromotionDecision>(`/v1/promotion-requests/${requestId}/approve`, { comment: comment || null });
  if (!result.ok) return { ok: false, message: result.message };
  revalidatePath(`/promotions/${requestId}`);
  revalidatePath("/promotions");
  revalidatePath("/overview");
  return { ok: true };
}

export async function rejectPromotionAction(requestId: string, _prevState: ActionResult, formData: FormData): Promise<ActionResult> {
  const comment = String(formData.get("comment") ?? "").trim();
  const result = await apiPost<PromotionDecision>(`/v1/promotion-requests/${requestId}/reject`, { comment: comment || null });
  if (!result.ok) return { ok: false, message: result.message };
  revalidatePath(`/promotions/${requestId}`);
  revalidatePath("/promotions");
  revalidatePath("/overview");
  return { ok: true };
}
