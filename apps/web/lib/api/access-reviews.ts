import { z } from "zod";
import { apiRequest } from "./client";

export const reviewScopeSchema = z.object({
  target_type: z.enum(["matter", "ip_docket"]), target_id: z.string(), target_title: z.string(), access_policy_version: z.number().int(),
  grants: z.array(z.object({ id: z.string(), record_version: z.number().int(), subject_type: z.enum(["membership", "team"]), subject_id: z.string(), subject_label: z.string(), effective_from: z.string().nullable(), expires_at: z.string().nullable(), reason: z.string().nullable() })),
});
export const campaignSchema = z.object({
  id: z.string(), title: z.string(), reason: z.string(), trigger: z.string(), status: z.enum(["open", "finalized"]), version: z.number().int(), creator_user_id: z.string(), created_at: z.string(), finalized_at: z.string().nullable(), snapshot: reviewScopeSchema,
  decisions: z.array(z.object({ grant_id: z.string(), decision: z.enum(["keep", "revoke"]), reason: z.string(), reviewer_user_id: z.string(), reviewer_membership_id: z.string(), created_at: z.string() })),
});
export type Campaign = z.infer<typeof campaignSchema>;
export type ReviewScope = z.infer<typeof reviewScopeSchema>;
export type ReviewTarget = ReviewScope["target_type"];
export type ReviewTrigger = "periodic" | "client_team_change" | "ethical_wall_change" | "portal_inactivity" | "employee_change" | "counsel_completion" | "incident";
const base = "/api/access-reviews";
const path = (id: string) => `${base}/${encodeURIComponent(id)}`;

export async function listReviewTargets(kind: ReviewTarget, q: string, afterId: string | null, signal?: AbortSignal) {
  const query = new URLSearchParams({ kind, q });
  if (afterId) query.set("after_id", afterId);
  return z.object({ targets: z.array(z.object({ id: z.string(), title: z.string() })), next_after_id: z.string().nullable() }).parse(await apiRequest(`${base}/targets?${query}`, { signal }));
}
export async function fetchReviewScope(kind: ReviewTarget, targetId: string, signal?: AbortSignal) {
  return reviewScopeSchema.parse(await apiRequest(`${base}/scope?${new URLSearchParams({ kind, target_id: targetId })}`, { signal }));
}
export async function listAccessReviews(beforeId: string | null, signal?: AbortSignal) {
  const query = new URLSearchParams();
  if (beforeId) query.set("before_id", beforeId);
  return z.object({ campaigns: z.array(campaignSchema), next_before_id: z.string().nullable() }).parse(await apiRequest(`${base}?${query}`, { signal }));
}
export async function fetchAccessReview(id: string, signal?: AbortSignal) {
  return campaignSchema.parse(await apiRequest(path(id), { signal }));
}
export async function createAccessReview(scope: ReviewScope, title: string, reason: string, trigger: ReviewTrigger) {
  return campaignSchema.parse(await apiRequest(base, { method: "POST", body: { target_type: scope.target_type, target_id: scope.target_id, expected_access_policy_version: scope.access_policy_version, title, reason, trigger } }));
}
export async function decideAccessReview(campaign: Campaign, grantId: string, decision: "keep" | "revoke", reason: string) {
  return campaignSchema.parse(await apiRequest(`${path(campaign.id)}/decisions`, { method: "POST", body: { expected_version: campaign.version, grant_id: grantId, decision, reason } }));
}
export async function finalizeAccessReview(campaign: Campaign) {
  return campaignSchema.parse(await apiRequest(`${path(campaign.id)}/finalize`, { method: "POST", body: { expected_version: campaign.version } }));
}
