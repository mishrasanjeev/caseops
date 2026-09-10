import { z } from "zod";

import { apiRequest } from "@/lib/api/client";
import type { SpecialistRecord } from "@/lib/api/ip-specialist";

const label = z.string().trim().min(1).max(255);
const note = z.string().trim().min(1).max(4000);
const day = z.string().date();
const optionalLabel = label.nullable().default(null);
const optionalDay = day.nullable().default(null);
const optionalNote = note.nullable().default(null);
const optionalId = z.string().uuid().nullable().default(null);
export const workflowSourceSchema = z.object({ document_id: z.string().uuid(), document_version_id: z.string().uuid(),
  content_sha256: z.string().regex(/^[a-f0-9]{64}$/), locator: z.string().trim().min(1).max(500) }).strict();
const sourceRef = z.object({ id: z.string().uuid(), version: z.number().int().positive() }).strict();
const sourced = { title: label, source_set: sourceRef, occurred_on: day, account: note };
export const sourceSetSchema = z.object({ kind: z.literal("source_set"), purpose: z.enum(["representations", "deposit", "instrument", "proceeding_evidence", "layout_deposit"]),
  title: label, members: z.array(z.object({ role: label, source: workflowSourceSchema }).strict()).min(1).max(25),
  confidentiality: z.enum(["restricted", "publication_authorized"]).default("restricted"),
  publication_instruction: optionalNote, publication_on_as_supplied: optionalDay }).strict();
const designSchema = z.object({ ...sourced, kind: z.literal("design_application"), registry: label, jurisdiction: z.string().trim().min(1).max(40),
  identifier_as_supplied: optionalLabel, stage: z.enum(["prepared", "filed", "examination", "objection", "response", "hearing", "accepted", "registered", "refused", "withdrawn"]).default("prepared"),
  publication: z.enum(["not_recorded", "deferred", "published"]).default("not_recorded"), publication_on: optionalDay,
  registration_identifier: optionalLabel, registration_on: optionalDay, protection_from: optionalDay, protection_until: optionalDay,
  period_action: z.enum(["none", "renewal", "extension"]).default("none"), variant_of: optionalId, variant_basis: workflowSourceSchema.nullable().default(null) }).strict();
const copyrightSchema = z.object({ ...sourced, kind: z.literal("copyright_registration"), registry: label, jurisdiction: z.string().trim().min(1).max(40),
  identifier_as_supplied: optionalLabel, stage: z.enum(["prepared", "filed", "deficiency", "objection", "response", "hearing", "registered", "correction", "expunged", "refused", "withdrawn"]).default("prepared"),
  registration_identifier: optionalLabel, registration_on: optionalDay, rights_effect: z.literal("not_determined_by_registration").default("not_determined_by_registration") }).strict();
const claimSchema = z.object({ ...sourced, kind: z.literal("rights_claim"), claimant: label, interest: z.enum(["authorship", "ownership", "assignment", "licence", "permission"]),
  rights: note, territory: label, effective_from: day, effective_until: optionalDay, predecessor: optionalId,
  competing_claims: z.array(z.string().uuid()).max(25).default([]), review: z.enum(["unreviewed", "unresolved", "supported", "rejected"]).default("unreviewed"), review_reason: optionalNote }).strict();
const layoutSchema = z.object({ ...sourced, kind: z.literal("layout_application"), registry: label, jurisdiction: z.string().trim().min(1).max(40),
  identifier_as_supplied: optionalLabel, stage: z.enum(["prepared", "filed", "examination", "objection", "response", "hearing", "registered", "refused", "withdrawn"]).default("prepared"),
  registration_identifier: optionalLabel, registration_on: optionalDay, first_exploitation_on_as_supplied: optionalDay, exploitation_territory_as_supplied: optionalLabel,
  publication: z.enum(["not_recorded", "reported_published"]).default("not_recorded"), publication_on: optionalDay,
  registry_source: workflowSourceSchema.nullable().default(null), cost_item_id: optionalId,
  legal_eligibility: z.literal("not_determined").default("not_determined"), rights_effect: z.literal("not_determined_by_registration").default("not_determined_by_registration") }).strict();
export const reviewIssueSchema = z.object({ clause: label, question: note, resolution: optionalNote, source: workflowSourceSchema }).strict();
const financeSchema = z.object({ currency: z.string().regex(/^[A-Z]{3}$/), royalty: optionalNote,
  fee_minor: z.number().int().nonnegative().nullable().default(null), minimum_minor: z.number().int().nonnegative().nullable().default(null), reporting: optionalNote, audit: optionalNote }).strict();
const licenceSchema = z.object({ ...sourced, kind: z.literal("licence"), grantor: label, grantee: label,
  transaction: z.enum(["licence", "assignment", "permission", "security_interest"]), exclusivity: z.enum(["exclusive", "nonexclusive", "sole", "not_stated"]),
  rights: note, territory: label, field_of_use: note, sublicensing: note, quality_control: note, prosecution_control: note, enforcement_control: note,
  renewal_terms: note, termination_terms: note, notice_terms: note, effective_from: day, effective_until: optionalDay,
  extracted_by: z.enum(["manual", "document_extraction"]).default("manual"), interpretation: z.enum(["unreviewed", "issues_open", "reviewed"]).default("unreviewed"),
  review_reason: optionalNote, issues: z.array(reviewIssueSchema).max(25).default([]), financial_terms: financeSchema.nullable().default(null),
  financial_terms_withheld: z.boolean().default(false), status: z.enum(["draft", "active", "terminated"]).default("draft"),
  recordal: z.enum(["not_determined", "not_required_as_reviewed", "required", "filed", "deficiency", "accepted", "rejected", "withdrawn"]).default("not_determined"),
  recordal_identifier: optionalLabel, recordal_on: optionalDay, termination_on: optionalDay }).strict();
const proceedingSchema = z.object({ ...sourced, kind: z.literal("proceeding"), channel: z.enum(["design_cancellation", "copyright_registry", "platform_takedown", "court", "settlement", "layout_opposition", "layout_cancellation", "layout_infringement"]),
  authority: z.string().trim().min(1).max(80), jurisdiction: z.string().trim().min(1).max(40), identifier_as_supplied: label, related_workflow: optionalId,
  stage: z.enum(["opened", "notice", "response", "hearing", "decision", "appeal", "closed"]).default("opened"),
  disposition: z.enum(["pending", "platform_removed", "platform_declined", "allowed", "dismissed", "settled", "withdrawn"]).default("pending") }).strict();
export const workflowFactsSchema = z.discriminatedUnion("kind", [sourceSetSchema, designSchema, copyrightSchema, layoutSchema, claimSchema, licenceSchema, proceedingSchema]).superRefine((facts, context) => {
  const fail = (message: string) => context.addIssue({ code: z.ZodIssueCode.custom, message });
  if (facts.kind === "source_set") {
    const keys = facts.members.map((m) => JSON.stringify([m.source.document_version_id, m.source.locator, m.role]));
    if (new Set(keys).size !== keys.length) fail("A source member may appear only once in a set.");
    if (facts.confidentiality === "publication_authorized" && !facts.publication_instruction) fail("Retain explicit publication instructions.");
  }
  if (facts.kind === "design_application" || facts.kind === "copyright_registration" || facts.kind === "layout_application") {
    if (facts.stage !== "prepared" && !facts.identifier_as_supplied) fail("Supply the application identifier from the source.");
    if (facts.stage === "registered" && !(facts.registration_identifier && facts.registration_on)) fail("Registration requires its own identifier and date.");
  }
  if (facts.kind === "layout_application") {
    if (!!facts.first_exploitation_on_as_supplied !== !!facts.exploitation_territory_as_supplied) fail("Retain the supplied exploitation date and territory together.");
    if (facts.publication === "reported_published" && !(facts.publication_on && facts.registry_source)) fail("Registry publication requires a date and separate exact source.");
    if (facts.publication === "not_recorded" && (facts.publication_on || facts.registry_source)) fail("Unrecorded publication cannot retain publication evidence.");
  }
  if (facts.kind === "design_application") {
    if (facts.publication === "published" && !facts.publication_on) fail("Supply the source publication date.");
    if (facts.period_action !== "none" && !(facts.protection_from && facts.protection_until)) fail("Supply the complete protection period.");
    if (facts.protection_from && facts.protection_until && facts.protection_until < facts.protection_from) fail("The protection period is reversed.");
    if (!!facts.variant_of !== !!facts.variant_basis) fail("A variant requires its parent and source basis.");
  }
  if (facts.kind === "rights_claim" || facts.kind === "licence") {
    if (facts.effective_until && facts.effective_until < facts.effective_from) fail("The effective period is reversed.");
  }
  if (facts.kind === "rights_claim") {
    if (["supported", "rejected"].includes(facts.review) && !facts.review_reason) fail("Retain the review rationale.");
    if (new Set(facts.competing_claims).size !== facts.competing_claims.length) fail("Competing claims must be distinct.");
  }
  if (facts.kind === "licence") {
    if (facts.interpretation === "reviewed" && (!facts.review_reason || facts.issues.some((i) => !i.resolution))) fail("Resolve every issue and retain the review rationale.");
    if (facts.status !== "draft" && facts.interpretation !== "reviewed") fail("Review the terms before activating the grant.");
    if (facts.status === "terminated" && !facts.termination_on) fail("Supply the termination date from the source.");
    if (facts.termination_on && facts.termination_on < facts.effective_from) fail("Termination precedes the grant period.");
    if (["filed", "deficiency", "accepted", "rejected", "withdrawn"].includes(facts.recordal) && !facts.recordal_identifier) fail("Supply the recordal identifier.");
    if (facts.recordal === "accepted" && !facts.recordal_on) fail("Supply the accepted recordal date.");
  }
  if (facts.kind === "proceeding") {
    if (["platform_removed", "platform_declined"].includes(facts.disposition) && facts.channel !== "platform_takedown") fail("A platform response is not a court or registry disposition.");
    if (facts.channel === "platform_takedown" && ["allowed", "dismissed"].includes(facts.disposition)) fail("Select a platform response.");
    if (["design_cancellation", "layout_opposition", "layout_cancellation", "layout_infringement"].includes(facts.channel) && !facts.related_workflow) fail("Select the separate application under challenge.");
  }
});
export const workflowRecordSchema = z.object({ id: z.string().uuid(), record_id: z.string().uuid(), version: z.number().int().positive(), lifecycle_version: z.number().int().nonnegative(),
  canonical_proceeding_id: z.string().uuid().nullable(), canonical_title_interest_id: z.string().uuid().nullable(), recorded_at: z.string().datetime({ offset: true }), facts: workflowFactsSchema }).strict();
const pageSchema = z.object({ records: z.array(workflowRecordSchema).max(10), next_cursor: z.string().uuid().nullable() }).strict();
export type WorkflowFacts = z.infer<typeof workflowFactsSchema>;
export type WorkflowRecord = z.infer<typeof workflowRecordSchema>;
export type WorkflowSource = z.infer<typeof workflowSourceSchema>;
export type WorkflowIssue = z.infer<typeof reviewIssueSchema>;
const base = (recordId: string) => `/api/ip/specialist/records/${recordId}/workflows`;
export const workflowKey = (id: string) => ["ip", "specialist-workflows", id];
export async function fetchWorkflows(recordId: string, cursor?: string, signal?: AbortSignal) {
  return pageSchema.parse(await apiRequest(`${base(recordId)}?limit=10${cursor ? `&cursor=${cursor}` : ""}`, { signal }));
}
export async function fetchWorkflow(recordId: string, id: string, version?: number, signal?: AbortSignal) {
  return workflowRecordSchema.parse(await apiRequest(`${base(recordId)}/${id}${version ? `/versions/${version}` : ""}`, { signal }));
}
export async function saveWorkflow(record: SpecialistRecord, facts: WorkflowFacts, reason: string, key: string, prior?: WorkflowRecord) {
  return workflowRecordSchema.parse(await apiRequest(`${base(record.id)}${prior ? `/${prior.id}/revisions` : ""}`, { method: "POST",
    headers: { "Idempotency-Key": key }, body: { expected_version: prior?.version ?? 0, expected_lifecycle_version: record.lifecycle_version, reason, facts: workflowFactsSchema.parse(facts) } }));
}
export const obligationSchema = z.object({ id: z.string().uuid(), task_id: z.string().uuid(), deadline_id: z.string().uuid(), due_on: day,
  kind: z.string(), title: label, status: z.string(), source: workflowSourceSchema, cost_item_id: z.string().uuid().nullable() }).strict();
const obligationPageSchema = z.object({ records: z.array(obligationSchema).max(10), next_cursor: z.string().uuid().nullable() }).strict();
export const performanceSchema = z.object({ id: z.string().uuid(), obligation_id: z.string().uuid(),
  action: z.enum(["complete", "cancel", "notice_recorded"]), occurred_on: day, account: note, source: workflowSourceSchema,
  cost_item_id: z.string().uuid().nullable(), recorded_at: z.string().datetime({ offset: true }) }).strict();
const performancePageSchema = z.object({ records: z.array(performanceSchema).max(10), next_cursor: z.string().uuid().nullable() }).strict();
export type ContractObligation = z.infer<typeof obligationSchema>;
export type ContractPerformance = z.infer<typeof performanceSchema>;
export const obligationKey = (recordId: string, workflowId: string) => [...workflowKey(recordId), workflowId, "obligations"];
const costOptionsSchema = z.object({ records: z.array(z.object({ id: z.string().uuid(), description: z.string().max(500) }).strict()).max(10), next_cursor: z.string().uuid().nullable() }).strict();
export async function fetchContractCostOptions(recordId: string, workflowId: string, cursor?: string, signal?: AbortSignal) {
  return costOptionsSchema.parse(await apiRequest(`${base(recordId)}/${workflowId}/cost-options${cursor ? `?cursor=${cursor}` : ""}`, { signal }));
}
const costOptionSchema = z.object({ id: z.string().uuid(), description: z.string().max(500) }).strict();
export async function recordContractCost(record: SpecialistRecord, workflowId: string, input: {
  description: string; amount_minor: number; currency: string; cost_nature: "actual" | "estimate"; source: WorkflowSource;
}, key: string) {
  return costOptionSchema.parse(await apiRequest(`${base(record.id)}/${workflowId}/cost-evidence`, { method: "POST", headers: { "Idempotency-Key": key },
    body: { ...input, expected_lifecycle_version: record.lifecycle_version } }));
}
export async function voidContractCost(record: SpecialistRecord, workflowId: string, costId: string, reason: string, source: WorkflowSource, key: string) {
  return costOptionSchema.parse(await apiRequest(`${base(record.id)}/${workflowId}/cost-evidence/${costId}/void`, { method: "POST", headers: { "Idempotency-Key": key },
    body: { expected_lifecycle_version: record.lifecycle_version, reason, source } }));
}
export async function fetchContractObligations(recordId: string, workflowId: string, cursor?: string, signal?: AbortSignal) {
  return obligationPageSchema.parse(await apiRequest(`${base(recordId)}/${workflowId}/obligations${cursor ? `?cursor=${cursor}` : ""}`, { signal }));
}
export async function fetchContractPerformance(recordId: string, workflowId: string, obligationId: string, cursor?: string, signal?: AbortSignal) {
  return performancePageSchema.parse(await apiRequest(`${base(recordId)}/${workflowId}/obligations/${obligationId}/performance${cursor ? `?cursor=${cursor}` : ""}`, { signal }));
}
export async function saveContractPerformance(record: SpecialistRecord, workflowId: string, obligationId: string, input: {
  action: ContractPerformance["action"]; occurred_on: string; account: string; source: WorkflowSource; replacement_cost_item_id: string | null;
}, key: string) {
  return performanceSchema.parse(await apiRequest(`${base(record.id)}/${workflowId}/obligations/${obligationId}/performance`, {
    method: "POST", headers: { "Idempotency-Key": key }, body: { ...input, expected_lifecycle_version: record.lifecycle_version, expected_status: "open" },
  }));
}
export async function saveContractObligation(record: SpecialistRecord, workflow: WorkflowRecord, input: {
  kind: string; title: string; due_on_as_supplied: string; source: WorkflowSource; cost_item_id: string | null;
}, key: string) {
  return obligationSchema.parse(await apiRequest(`${base(record.id)}/${workflow.id}/obligations`, { method: "POST", headers: { "Idempotency-Key": key },
    body: { ...input, expected_version: workflow.version, expected_lifecycle_version: record.lifecycle_version } }));
}
