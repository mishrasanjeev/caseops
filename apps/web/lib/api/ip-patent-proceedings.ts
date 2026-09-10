import { z } from "zod";

import { apiRequest } from "./client";
import { patentEvidenceSchema } from "./ip-patent-prosecution";

export const patentProceedingStages = ["notice_recorded", "response_preparation", "response_filed", "hearing_recorded", "decided", "withdrawn"] as const;
const stage = z.enum(patentProceedingStages);
const source = patentEvidenceSchema.shape.source;
export const patentProceedingPreviewSchema = z.object({
  proceeding_id: z.string().uuid(), current_stage: stage, proposed_stage: stage,
  required_acknowledgements: z.array(z.enum(["backdated_source_review", "exceptional_stage_review"])).max(2),
  preview_sha256: z.string().regex(/^[a-f0-9]{64}$/),
  changes_application_phase: z.literal(false), changes_deadlines: z.literal(false),
}).strict();
const event = z.object({
  id: z.string().uuid(), revision: z.number().int().positive().max(100), sequence: z.number().int().positive(),
  anchor_version: z.number().int().positive(), lifecycle_version: z.number().int().nonnegative(),
  before_stage: stage.nullable(), after_stage: stage, source,
  received_on: z.string().date(), effective_on: z.string().date(), proceeding_number: z.string().nullable(),
  evidence_id: z.string().uuid().nullable(), reason: z.string(), outcome: z.string().nullable(),
  exceptional_transition_reason: z.string().nullable(), impact: patentProceedingPreviewSchema.nullable(),
  created_at: z.string().datetime({ offset: true }),
}).strict();
export const patentProceedingSchema = z.object({
  id: z.string().uuid(), application_id: z.string().uuid(), docket_id: z.string().uuid(),
  proceeding_kind: z.literal("patent_pre_grant_opposition"), title: z.string(), counterparty: z.string(),
  side: z.enum(["applicant", "opponent"]), office: z.string(), jurisdiction: z.string(),
  version: z.number().int().positive(), stage, lifecycle_version: z.number().int().nonnegative(),
  operational: z.boolean(), allowed_stages: z.array(stage), latest: event,
}).strict();
const page = z.object({ application_id: z.string().uuid(), work_sequence: z.number().int().nonnegative(),
  records: z.array(patentProceedingSchema).max(100), next_cursor: z.string().uuid().nullable() }).strict();
export const patentProceedingHistorySchema = z.object({ proceeding: patentProceedingSchema, events: z.array(event).min(1).max(100) }).strict();
export type PatentProceeding = z.infer<typeof patentProceedingSchema>;
export type PatentProceedingPreview = z.infer<typeof patentProceedingPreviewSchema>;
type Command = { expected_version: number; expected_lifecycle_version: number; expected_work_sequence: number;
  reason: string; source: z.infer<typeof source>; received_on: string; effective_on: string; proceeding_number: string | null };
export type PatentProceedingCreateInput = Command & { title: string; counterparty: string;
  side: "applicant" | "opponent"; source_pending_identifier_allocation: boolean; proceeding_kind: "patent_pre_grant_opposition" };
export type PatentProceedingTransitionInput = Command & { expected_proceeding_version: number;
  to_stage: PatentProceeding["stage"]; evidence_id: string | null; outcome: string | null;
  exceptional_transition_reason: string | null; preview_sha256?: string;
  acknowledged_exception_codes?: PatentProceedingPreview["required_acknowledgements"] };
const path = (id: string) => `/api/ip/patents/applications/${encodeURIComponent(id)}/proceedings`;
export async function fetchPatentProceedings(id: string, cursor?: string, snapshot?: number, signal?: AbortSignal) {
  const query = new URLSearchParams({ limit: "25" });
  if (cursor) query.set("cursor", cursor);
  if (snapshot !== undefined) query.set("snapshot_sequence", String(snapshot));
  return page.parse(await apiRequest<unknown>(`${path(id)}?${query}`, { signal }));
}
export async function fetchPatentProceedingHistory(id: string, proceeding: string, signal?: AbortSignal) {
  return patentProceedingHistorySchema.parse(await apiRequest<unknown>(`${path(id)}/${encodeURIComponent(proceeding)}`, { signal }));
}
export async function createPatentProceeding(id: string, body: PatentProceedingCreateInput, key: string) {
  return patentProceedingSchema.parse(await apiRequest<unknown>(path(id), { method: "POST", body, headers: { "Idempotency-Key": key } }));
}
export async function previewPatentProceeding(id: string, proceeding: string, body: PatentProceedingTransitionInput) {
  return patentProceedingPreviewSchema.parse(await apiRequest<unknown>(`${path(id)}/${encodeURIComponent(proceeding)}/preview`, { method: "POST", body }));
}
export async function transitionPatentProceeding(id: string, proceeding: string, body: PatentProceedingTransitionInput, key: string) {
  return patentProceedingSchema.parse(await apiRequest<unknown>(`${path(id)}/${encodeURIComponent(proceeding)}/transitions`, { method: "POST", body, headers: { "Idempotency-Key": key } }));
}
