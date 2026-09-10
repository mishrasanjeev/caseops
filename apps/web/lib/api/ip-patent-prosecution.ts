import { z } from "zod";

import { apiRequest } from "./client";
import { patentApplicationSchema } from "./ip-patents";

const hash = z.string().regex(/^[a-f0-9]{64}$/);
const source = z.object({
  kind: z.literal("document_version"), document_id: z.string().uuid(),
  document_version_id: z.string().uuid(), content_sha256: hash,
}).strict();
export const patentDocumentKinds = ["claims", "specification", "drawings", "abstract", "sequence_listing", "translation", "amendment", "response", "filing_package"] as const;
export const patentEventKinds = ["filing_preparation", "filing", "publication", "examination_request", "office_action", "response", "hearing", "amendment", "grant", "restoration"] as const;
const manifestItem = z.object({ document_kind: z.enum(patentDocumentKinds), source }).strict();
const record = {
  id: z.string().uuid(), application_id: z.string().uuid(), sequence: z.number().int().positive(),
  anchor_version: z.number().int().positive(), lifecycle_version: z.number().int().nonnegative(),
  reason: z.string(), created_at: z.string().datetime({ offset: true }), source,
};
export const patentEvidenceSchema = z.object({
  ...record, root_id: z.string().uuid(), predecessor_id: z.string().uuid().nullable(),
  edition: z.number().int().positive(), is_current: z.boolean(), title: z.string(), document_kind: z.enum(patentDocumentKinds),
  documents: z.array(manifestItem).min(1).max(20), manifest_sha256: hash,
}).strict();
export const patentProsecutionPreviewSchema = z.object({
  application_id: z.string().uuid(), work_sequence: z.number().int().nonnegative(),
  current_phase: patentApplicationSchema.shape.prosecution_phase,
  proposed_phase: patentApplicationSchema.shape.prosecution_phase,
  backdated: z.boolean(), affected_deadline_ids: z.array(z.string().uuid()).max(100),
  required_acknowledgements: z.array(z.enum(["backdated_recalculation_review_required", "exceptional_transition_review_required"])).max(2),
  preview_sha256: hash, changes_deadlines: z.literal(false), authoritative_calculation_available: z.literal(false),
}).strict();
export const patentProsecutionSchema = z.object({
  ...record, event_kind: z.enum(patentEventKinds), received_on: z.string().date(), effective_on: z.string().date(),
  evidence_id: z.string().uuid().nullable(), before_phase: patentApplicationSchema.shape.prosecution_phase,
  after_phase: patentApplicationSchema.shape.prosecution_phase, exceptional_transition_reason: z.string().nullable(),
  impact: patentProsecutionPreviewSchema,
}).strict();
const evidencePage = z.object({ application_id: z.string().uuid(), work_sequence: z.number().int().nonnegative(),
  records: z.array(patentEvidenceSchema).max(100), next_cursor: z.number().int().positive().nullable() }).strict();
const eventPage = z.object({ application_id: z.string().uuid(), work_sequence: z.number().int().nonnegative(),
  records: z.array(patentProsecutionSchema).max(100), next_cursor: z.number().int().positive().nullable() }).strict();

export type PatentEvidence = z.infer<typeof patentEvidenceSchema>;
export type PatentProsecution = z.infer<typeof patentProsecutionSchema>;
export type PatentProsecutionPreview = z.infer<typeof patentProsecutionPreviewSchema>;
type Preconditions = { expected_version: number; expected_lifecycle_version: number; expected_work_sequence: number; reason: string };
export type PatentEvidenceInput = Preconditions & {
  title: string; document_kind: typeof patentDocumentKinds[number]; predecessor_id?: string | null;
  source: z.infer<typeof source>; documents: z.infer<typeof manifestItem>[];
};
export type PatentEventInput = Preconditions & {
  event_kind: typeof patentEventKinds[number]; received_on: string; effective_on: string;
  source: z.infer<typeof source>; evidence_id: string | null;
  expected_phase: z.infer<typeof patentApplicationSchema>["prosecution_phase"];
  exceptional_transition_reason: string | null; preview_sha256?: string;
  acknowledged_exception_codes?: PatentProsecutionPreview["required_acknowledgements"];
};
const path = (applicationId: string) => `/api/ip/patents/applications/${encodeURIComponent(applicationId)}`;
const pageQuery = (cursor?: number, snapshot?: number) => {
  const query = new URLSearchParams({ limit: "25" });
  if (cursor !== undefined) query.set("cursor", String(cursor));
  if (snapshot !== undefined) query.set("snapshot_sequence", String(snapshot));
  return query;
};
export async function fetchPatentEvidence(id: string, cursor?: number, snapshot?: number, signal?: AbortSignal) {
  return evidencePage.parse(await apiRequest<unknown>(`${path(id)}/evidence?${pageQuery(cursor, snapshot)}`, { signal }));
}
export async function fetchPatentProsecution(id: string, cursor?: number, snapshot?: number, signal?: AbortSignal) {
  return eventPage.parse(await apiRequest<unknown>(`${path(id)}/prosecution?${pageQuery(cursor, snapshot)}`, { signal }));
}
export async function createPatentEvidence(id: string, body: PatentEvidenceInput, key: string) {
  return patentEvidenceSchema.parse(await apiRequest<unknown>(`${path(id)}/evidence`, { method: "POST", body, headers: { "Idempotency-Key": key } }));
}
export async function previewPatentProsecution(id: string, body: PatentEventInput) {
  return patentProsecutionPreviewSchema.parse(await apiRequest<unknown>(`${path(id)}/prosecution/preview`, { method: "POST", body }));
}
export async function createPatentProsecution(id: string, body: PatentEventInput, key: string) {
  return patentProsecutionSchema.parse(await apiRequest<unknown>(`${path(id)}/prosecution`, { method: "POST", body, headers: { "Idempotency-Key": key } }));
}
