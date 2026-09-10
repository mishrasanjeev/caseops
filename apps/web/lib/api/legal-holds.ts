import { z } from "zod";
import { apiRequest } from "./client";

export const legalHoldSchema = z.object({
  id: z.string(), title: z.string(), authority_reference: z.string(),
  status: z.enum(["draft", "active", "released", "cancelled"]),
  scope: z.enum(["company", "data_classes"]), data_class_ids: z.array(z.string()),
  created_by_membership_id: z.string().nullable(), approved_by_membership_id: z.string().nullable(),
  updated_at: z.string(), activated_at: z.string().nullable(), released_at: z.string().nullable(),
});
export const holdReleaseSchema = z.object({
  id: z.string(), hold_id: z.string(), request_hash: z.string(), expires_at: z.string(), requester_membership_id: z.string(),
  reason_reference: z.string(), dry_run_id: z.string(),
});
export type LegalHold = z.infer<typeof legalHoldSchema>;
export type HoldRelease = z.infer<typeof holdReleaseSchema>;
const base = "/api/admin/data-governance/holds";
const holdPath = (id: string) => `${base}/${encodeURIComponent(id)}`;

export async function listLegalHolds(signal?: AbortSignal, beforeId?: string | null) {
  const query = new URLSearchParams({ limit: "25" });
  if (beforeId) query.set("before_id", beforeId);
  return z.object({ holds: z.array(legalHoldSchema), has_more: z.boolean(), next_before_id: z.string().nullable() }).parse(
    await apiRequest(`${base}?${query}`, { signal }),
  );
}
export async function createLegalHold(payload: {
  idempotency_key: string; title: string; authority_reference: string;
  scope: "company" | "data_classes"; data_class_ids: string[];
}) {
  return legalHoldSchema.parse(await apiRequest(base, { method: "POST", body: payload }));
}
export async function activateLegalHold(hold: LegalHold) {
  return legalHoldSchema.parse(await apiRequest(`${holdPath(hold.id)}/activate`, {
    method: "POST", body: { expected_updated_at: hold.updated_at },
  }));
}
export async function listHoldReleaseRequests(holdId: string, signal?: AbortSignal, beforeId?: string | null) {
  const query = new URLSearchParams({ limit: "25" });
  if (beforeId) query.set("before_id", beforeId);
  return z.object({ proposals: z.array(holdReleaseSchema), has_more: z.boolean(), next_before_id: z.string().nullable() }).parse(
    await apiRequest(`${holdPath(holdId)}/release-requests?${query}`, { signal }),
  );
}
export async function requestHoldRelease(hold: LegalHold, input: {
  idempotency_key: string; dry_run_id: string; reason_reference: string;
}) {
  return holdReleaseSchema.parse(await apiRequest(`${holdPath(hold.id)}/release-requests`, {
    method: "POST", body: { ...input, expected_updated_at: hold.updated_at },
  }));
}
export async function approveHoldRelease(hold: LegalHold, proposal: HoldRelease) {
  return legalHoldSchema.parse(await apiRequest(`${holdPath(hold.id)}/release-requests/${encodeURIComponent(proposal.id)}/approve`, {
    method: "POST", body: { expected_updated_at: hold.updated_at },
  }));
}
