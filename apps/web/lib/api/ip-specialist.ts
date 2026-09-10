import { z } from "zod";

import { apiRequest } from "./client";

const text = (max = 500) => z.string().trim().min(1).max(max).regex(/^[^\0]*$/);
const optional = text().nullable().optional();
const narrative = text(4000);
const optionalNarrative = narrative.nullable().optional();
const optionalDate = z.string().date().nullable().optional();
const domainSchema = z.enum(["design", "copyright", "domain_name", "licensing", "enforcement",
  "geographical_indication", "plant_variety", "semiconductor_layout", "trade_secret", "customs_enforcement"]);
export const specialistDetailsSchema = z.discriminatedUnion("domain", [
  z.object({ domain: z.literal("design"), applicant: text(), article: text(), classification_as_supplied: optional,
    novelty_statement: optionalNarrative, representation_description: optionalNarrative,
    publication_instruction: z.enum(["unknown", "confidential", "published"]).default("unknown") }).strict(),
  z.object({ domain: z.literal("copyright"), work_type_as_supplied: text(), author: text(), claimant: text(),
    ownership_claim: narrative, created_on: optionalDate, published_on: optionalDate, ownership_disputed: z.boolean().default(false) }).strict(),
  z.object({ domain: z.literal("domain_name"), domain_name: text(), registrar: optional, registrant_as_supplied: text(),
    expiry_as_supplied: optionalDate, dispute_channel_as_supplied: optional }).strict(),
  z.object({ domain: z.literal("licensing"), grantor: text(), grantee: text(), affected_rights_as_supplied: narrative,
    territory: text(), field_of_use: optional, exclusivity: z.enum(["not_reviewed", "exclusive", "non_exclusive", "sole"]).default("not_reviewed"),
    term_as_supplied: optional, royalty_terms_confidential: optionalNarrative, interpretation_issue: optionalNarrative }).strict(),
  z.object({ domain: z.literal("enforcement"), represented_party: text(), asserted_right_as_supplied: narrative,
    allegation: narrative, proposed_channel: z.enum(["investigation", "notice", "platform", "customs", "opposition", "cancellation", "litigation"]),
    alleged_party: optional }).strict(),
  z.object({ domain: z.literal("geographical_indication"), applicant_or_association: text(), geographical_area: narrative,
    goods: text(), specification_as_supplied: optionalNarrative, authorised_user_claim: optional }).strict(),
  z.object({ domain: z.literal("plant_variety"), denomination: text(), category_as_supplied: text(), crop_species: text(),
    applicant: text(), breeder_as_supplied: optional, farmer_claim_as_supplied: optional, material_custodian: text(), material_access_instructions: narrative }).strict(),
  z.object({ domain: z.literal("semiconductor_layout"), creator: text(), proprietor_as_supplied: text(), layout_description: narrative,
    first_commercial_exploitation: optionalDate, exploitation_territory: optional }).strict(),
  z.object({ domain: z.literal("trade_secret"), owner_as_supplied: text(), custodian: text(), asset_reference: text(),
    protective_controls: narrative, permitted_access_as_supplied: narrative }).strict(),
  z.object({ domain: z.literal("customs_enforcement"), right_holder: text(), asserted_right_as_supplied: narrative, products: narrative,
    authority_or_channel_as_supplied: text(), authentication_guide_custodian: text(), authorised_importer_policy: narrative, instruction_reference: text() }).strict(),
]);
export const specialistFactsSchema = z.object({ title: text(255), client_id: z.string().uuid(),
  jurisdiction_as_supplied: text(), details: specialistDetailsSchema }).strict();
export const specialistRecordSchema = z.object({ id: z.string().uuid(), docket_id: z.string().uuid(), asset_id: z.string().uuid(),
  contract_version: z.string(), version: z.number().int().positive(), lifecycle_version: z.number().int().nonnegative(),
  lifecycle_status: z.string(), is_active: z.boolean(), created_at: z.string().datetime({ offset: true }), facts: specialistFactsSchema }).strict();
const specialistFieldSchema = z.object({ key: z.string(), label: z.string(), kind: z.enum(["text", "textarea", "date", "boolean", "select"]),
  required: z.boolean(), max_length: z.number().int().positive().nullable(), options: z.array(z.string()) }).strict();
const contractSchema = z.object({ domain: domainSchema, label: z.string(), contract_version: z.string(), contract_path: z.string(),
  child_prd_sha256: z.string().regex(/^[a-f0-9]{64}$/), intake_available: z.boolean(), fields: z.array(specialistFieldSchema),
  observation_kinds: z.array(z.string()), blockers: z.array(z.string()) }).strict();
const sourceSchema = z.object({ document_id: z.string().uuid(), document_version_id: z.string().uuid(),
  content_sha256: z.string().regex(/^[a-f0-9]{64}$/), locator: text() }).strict();
const observationSchema = z.object({ id: z.string().uuid(), sequence: z.number().int().positive(), kind: z.string(), occurred_on: z.string().date(),
  account: narrative, source: sourceSchema, supersedes_id: z.string().uuid().nullable(), recorded_at: z.string().datetime({ offset: true }),
  legal_effect: z.literal("not_determined") }).strict();
const listSchema = z.object({ records: z.array(z.object({ id: z.string().uuid(), domain: domainSchema, title: z.string(),
  lifecycle_status: z.string(), version: z.number().int().positive() }).strict()).max(50), next_cursor: z.string().uuid().nullable() }).strict();
const observationsSchema = z.object({ observations: z.array(observationSchema).max(50), next_cursor: z.number().int().positive().nullable() }).strict();

export type SpecialistFacts = z.infer<typeof specialistFactsSchema>;
export type SpecialistRecord = z.infer<typeof specialistRecordSchema>;
export type SpecialistContract = z.infer<typeof contractSchema>;
export type SpecialistObservation = z.infer<typeof observationSchema>;
const base = "/api/ip/specialist";
export const specialistKey = (id: string) => ["ip", "specialist-record", id];

export async function fetchSpecialistContracts(signal?: AbortSignal) {
  return z.array(contractSchema).max(10).parse(await apiRequest(`${base}/contracts`, { signal }));
}
export async function fetchSpecialistRecords(domain: string, closed: boolean, cursor?: string, signal?: AbortSignal) {
  const query = new URLSearchParams({ domain, include_closed: String(closed), limit: "25" });
  if (cursor) query.set("cursor", cursor);
  return listSchema.parse(await apiRequest(`${base}/records?${query}`, { signal }));
}
export async function fetchSpecialistRecord(id: string, version?: number, signal?: AbortSignal) {
  return specialistRecordSchema.parse(await apiRequest(`${base}/records/${encodeURIComponent(id)}${version ? `/versions/${version}` : ""}`, { signal }));
}
export async function saveSpecialistFacts(facts: SpecialistFacts, key: string, saved?: SpecialistRecord, reason?: string) {
  return specialistRecordSchema.parse(await apiRequest(`${base}/records${saved ? `/${saved.id}/corrections` : ""}`, {
    method: "POST", headers: { "Idempotency-Key": key }, body: saved ? { expected_version: saved.version,
      expected_lifecycle_version: saved.lifecycle_version, reason, facts: specialistFactsSchema.parse(facts) } : specialistFactsSchema.parse(facts),
  }));
}
export async function fetchSpecialistObservations(id: string, cursor?: number, signal?: AbortSignal) {
  const query = new URLSearchParams({ limit: "25" });
  if (cursor) query.set("cursor", String(cursor));
  return observationsSchema.parse(await apiRequest(`${base}/records/${id}/observations?${query}`, { signal }));
}
export async function saveSpecialistObservation(record: SpecialistRecord, input: Pick<SpecialistObservation, "kind" | "occurred_on" | "account" | "source" | "supersedes_id">, key: string) {
  return observationSchema.parse(await apiRequest(`${base}/records/${record.id}/observations`, { method: "POST",
    headers: { "Idempotency-Key": key }, body: { ...input, expected_version: record.version, expected_lifecycle_version: record.lifecycle_version } }));
}

export async function uploadSpecialistSource(record: SpecialistRecord, file: File, taxonomyKey: string) {
  const body = new FormData();
  body.append("upload", file);
  body.append("metadata_json", JSON.stringify({ taxonomy_key: taxonomyKey, title: file.name, confidentiality: "restricted",
    asset_type: record.facts.details.domain, links: [{ target_type: "docket", target_id: record.docket_id }] }));
  return apiRequest<{ outcome: string }>("/api/ip/documents/upload", { method: "POST", body });
}
