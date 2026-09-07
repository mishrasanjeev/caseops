import { z } from "zod";

import { apiRequest } from "./client";

const hash = z.string().regex(/^[a-f0-9]{64}$/);
const text = (max: number) => z.string().min(1).max(max).regex(/\S/)
  .refine((value) => !value.includes("\0"), "Text cannot contain a null character.");
const documentSource = z.object({
  kind: z.literal("document_version"), document_id: z.string().uuid(),
  document_version_id: z.string().uuid(), content_sha256: hash,
}).strict();
const registrySource = z.object({
  kind: z.literal("registry_snapshot"), snapshot_id: z.string().uuid(),
  raw_sha256: hash, normalized_sha256: hash,
}).strict();
export const patentSourceSchema = z.discriminatedUnion("kind", [documentSource, registrySource]);
export const patentFamilyFactsSchema = z.object({
  title: text(255), client_id: z.string().uuid(),
  disclosure_date: z.string().date(), disclosure_narrative: text(30_000),
  confidentiality: z.literal("restricted"), source: patentSourceSchema.nullable().optional(),
}).strict();
export const patentFamilySchema = z.object({
  id: z.string().uuid(), docket_id: z.string().uuid(), asset_id: z.string().uuid(),
  record_kind: z.literal("patent_family"), version: z.number().int().positive(),
  lifecycle_version: z.number().int().nonnegative(), lifecycle_status: z.string().max(32),
  is_active: z.boolean(), created_at: z.string().datetime({ offset: true }),
  updated_at: z.string().datetime({ offset: true }), facts: patentFamilyFactsSchema,
}).strict();
const familyListSchema = z.object({
  families: z.array(patentFamilySchema).max(100), next_cursor: z.string().max(512).nullable(),
}).strict();

export type PatentFamily = z.infer<typeof patentFamilySchema>;
export type PatentFamilyFacts = z.infer<typeof patentFamilyFactsSchema>;
export type PatentFamilyStatusScope = "active" | "terminal" | "all";

export async function fetchPatentFamilies(q: string, cursor?: string, signal?: AbortSignal, statusScope: PatentFamilyStatusScope = "active") {
  const query = new URLSearchParams({ limit: "50" });
  query.set("status_scope", statusScope);
  if (q) query.set("q", q);
  if (cursor) query.set("cursor", cursor);
  return familyListSchema.parse(await apiRequest<unknown>(`/api/ip/patents/families?${query}`, { signal }));
}

const lifecycleHistorySchema = z.object({
  events: z.array(z.object({
    id: z.string().uuid(), sequence: z.number().int().positive(),
    from_status: z.string().nullable(), to_status: z.string().nullable(),
    effective_at: z.string().datetime({ offset: true }), entered_at: z.string().datetime({ offset: true }),
    reason: z.string().nullable(), evidence_refs: z.array(z.string()).max(100),
  }).strict()).max(100),
  next_cursor: z.number().int().positive().nullable(),
}).strict();

export async function fetchPatentFamilyLifecycleHistory(id: string, cursor?: number, signal?: AbortSignal) {
  const query = new URLSearchParams({ limit: "25" });
  if (cursor !== undefined) query.set("cursor", String(cursor));
  return lifecycleHistorySchema.parse(await apiRequest<unknown>(
    `/api/ip/patents/families/${encodeURIComponent(id)}/lifecycle-history?${query}`, { signal },
  ));
}

export async function fetchPatentFamily(id: string, version?: number, signal?: AbortSignal) {
  const path = `/api/ip/patents/families/${encodeURIComponent(id)}`;
  return patentFamilySchema.parse(await apiRequest<unknown>(
    version ? `${path}/versions/${version}` : path, { signal },
  ));
}

export async function createPatentFamily(facts: PatentFamilyFacts, idempotencyKey: string) {
  return patentFamilySchema.parse(await apiRequest<unknown>("/api/ip/patents/families", {
    method: "POST", body: patentFamilyFactsSchema.parse(facts),
    headers: { "Idempotency-Key": idempotencyKey },
  }));
}

export async function correctPatentFamily(family: PatentFamily, facts: PatentFamilyFacts, reason: string) {
  return patentFamilySchema.parse(await apiRequest<unknown>(
    `/api/ip/patents/families/${encodeURIComponent(family.id)}/corrections`, {
      method: "POST", body: {
        expected_version: family.version, expected_lifecycle_version: family.lifecycle_version,
        reason, facts: patentFamilyFactsSchema.parse(facts),
      },
    },
  ));
}

export const patentApplicationKinds = [
  "provisional", "complete", "convention", "pct_international", "national_phase",
  "divisional", "patent_of_addition",
] as const;
export const patentIdentifierSchema = z.object({
  identifier_kind: z.enum(["application", "publication", "grant"]),
  raw_value: text(120), source: patentSourceSchema,
}).strict();
export const patentApplicationFactsSchema = z.object({
  title: text(255), application_kind: z.enum(patentApplicationKinds),
  jurisdiction: z.string().regex(/^[A-Z]{2}$/), office: text(80),
  filing_date: z.string().date().nullable(), publication_date: z.string().date().nullable(),
  identifiers: z.array(patentIdentifierSchema).max(20),
  source_pending_identifier_allocation: z.boolean(), source: patentSourceSchema,
}).strict().superRefine((facts, context) => {
  if (facts.filing_date && facts.publication_date && facts.publication_date < facts.filing_date) {
    context.addIssue({ code: "custom", path: ["publication_date"], message: "Publication cannot precede filing." });
  }
  if (facts.source_pending_identifier_allocation && facts.identifiers.some((row) => row.identifier_kind === "application")) {
    context.addIssue({ code: "custom", path: ["identifiers"], message: "An allocated application number cannot also be pending allocation." });
  }
  if (new Set(facts.identifiers.map((row) => JSON.stringify([row.identifier_kind, row.raw_value]))).size !== facts.identifiers.length) {
    context.addIssue({ code: "custom", path: ["identifiers"], message: "An identifier fact may appear only once." });
  }
});
export const patentApplicationSchema = z.object({
  id: z.string().uuid(), docket_id: z.string().uuid(), family_id: z.string().uuid(),
  record_kind: z.literal("patent_application"), version: z.number().int().positive(),
  lifecycle_version: z.number().int().nonnegative(), lifecycle_status: text(32), is_active: z.boolean(),
  created_at: z.string().datetime({ offset: true }), updated_at: z.string().datetime({ offset: true }),
  prosecution_phase: z.enum(["disclosure", "filing_preparation", "filed", "published", "examination_requested",
    "examination", "response_filed", "hearing", "granted", "refused", "withdrawn", "abandoned", "closed"]),
  facts: patentApplicationFactsSchema,
}).strict();
const applicationListSchema = z.object({
  applications: z.array(patentApplicationSchema).max(100), next_cursor: z.string().max(512).nullable(),
}).strict();
export type PatentApplication = z.infer<typeof patentApplicationSchema>;
export type PatentApplicationFacts = z.infer<typeof patentApplicationFactsSchema>;
export type PatentSource = z.infer<typeof patentSourceSchema>;

export async function fetchPatentApplications(familyId: string, cursor?: string, signal?: AbortSignal,
  statusScope: PatentFamilyStatusScope = "active", queryText = "") {
  const query = new URLSearchParams({ limit: "50", status_scope: statusScope });
  if (familyId) query.set("family_id", familyId);
  if (cursor) query.set("cursor", cursor);
  if (queryText) query.set("q", queryText);
  return applicationListSchema.parse(await apiRequest<unknown>(`/api/ip/patents/applications?${query}`, { signal }));
}

export async function fetchPatentApplication(id: string, version?: number, signal?: AbortSignal) {
  const path = `/api/ip/patents/applications/${encodeURIComponent(id)}`;
  return patentApplicationSchema.parse(await apiRequest<unknown>(version ? `${path}/versions/${version}` : path, { signal }));
}

export async function createPatentApplication(family: PatentFamily, facts: PatentApplicationFacts, idempotencyKey: string) {
  return patentApplicationSchema.parse(await apiRequest<unknown>("/api/ip/patents/applications", {
    method: "POST", headers: { "Idempotency-Key": idempotencyKey }, body: {
      family_id: family.id, expected_family_version: family.version,
      expected_family_lifecycle_version: family.lifecycle_version, facts: patentApplicationFactsSchema.parse(facts),
    },
  }));
}

export async function correctPatentApplication(application: PatentApplication, facts: PatentApplicationFacts, reason: string) {
  return patentApplicationSchema.parse(await apiRequest<unknown>(
    `/api/ip/patents/applications/${encodeURIComponent(application.id)}/corrections`, {
      method: "POST", body: { expected_version: application.version,
        expected_lifecycle_version: application.lifecycle_version, reason, facts: patentApplicationFactsSchema.parse(facts) },
    },
  ));
}

export async function fetchPatentApplicationLifecycleHistory(id: string, cursor?: number, signal?: AbortSignal) {
  const query = new URLSearchParams({ limit: "25" });
  if (cursor !== undefined) query.set("cursor", String(cursor));
  return lifecycleHistorySchema.parse(await apiRequest<unknown>(
    `/api/ip/patents/applications/${encodeURIComponent(id)}/lifecycle-history?${query}`, { signal },
  ));
}

export const patentPartyRoles = ["inventor", "applicant", "proprietor", "agent", "licensee"] as const;
export const patentPartyFactSchema = z.object({
  role: z.enum(patentPartyRoles), name: text(255), client_id: z.string().uuid().nullable(),
  address: z.object({
    address_lines: z.array(text(255)).min(1).max(5), city: text(120),
    region: text(120).nullable(), postal_code: text(40).nullable(),
    country_code: z.string().regex(/^[A-Z]{2}$/),
  }).strict(),
  effective_from: z.string().date(), effective_until: z.string().date().nullable(),
  source: patentSourceSchema,
}).strict().refine((fact) => !fact.effective_until || fact.effective_until >= fact.effective_from, {
  path: ["effective_until"], message: "The effective end cannot precede the start.",
});
export const patentPartySchema = z.object({
  id: z.string().uuid(), docket_id: z.string().uuid(), sequence: z.number().int().positive(),
  anchor_version: z.number().int().positive(), lifecycle_version: z.number().int().nonnegative(),
  supersedes_party_id: z.string().uuid().nullable(), is_current: z.boolean(),
  fact: patentPartyFactSchema, reason: text(1000).refine((value) => value.length >= 8),
  created_at: z.string().datetime({ offset: true }),
}).strict();
export const patentPartyPageSchema = z.object({
  docket_id: z.string().uuid(), collection_sequence: z.number().int().nonnegative(),
  parties: z.array(patentPartySchema).max(100), next_cursor: z.number().int().positive().nullable(),
}).strict();
export type PatentPartyFact = z.infer<typeof patentPartyFactSchema>;
export type PatentParty = z.infer<typeof patentPartySchema>;
export type PatentPartyPage = z.infer<typeof patentPartyPageSchema>;

export async function fetchPatentParties(docketId: string, history = false,
  continuation?: { cursor: number; sequence: number }, signal?: AbortSignal) {
  const id = z.string().uuid().parse(docketId);
  const query = new URLSearchParams({ limit: "25", history: String(history) });
  if (continuation) {
    query.set("cursor", String(z.number().int().positive().parse(continuation.cursor)));
    query.set("snapshot_sequence", String(z.number().int().nonnegative().parse(continuation.sequence)));
  }
  return patentPartyPageSchema.parse(await apiRequest<unknown>(
    `/api/ip/patents/dockets/${id}/parties?${query}`, { signal },
  ));
}

export async function createPatentParty(record: PatentFamily | PatentApplication, sequence: number,
  fact: PatentPartyFact, reason: string, supersedesId: string | null, idempotencyKey: string) {
  const request = z.object({
    expected_version: z.number().int().positive(), expected_lifecycle_version: z.number().int().nonnegative(),
    expected_party_sequence: z.number().int().nonnegative(),
    fact: patentPartyFactSchema, reason: text(1000).refine((value) => value.length >= 8),
    supersedes_party_id: z.string().uuid().nullable(),
  }).strict().parse({
    expected_version: record.version, expected_lifecycle_version: record.lifecycle_version,
    expected_party_sequence: sequence, fact, reason, supersedes_party_id: supersedesId,
  });
  return patentPartySchema.parse(await apiRequest<unknown>(
    `/api/ip/patents/dockets/${z.string().uuid().parse(record.docket_id)}/parties`, {
      method: "POST", headers: { "Idempotency-Key": idempotencyKey }, body: request,
    },
  ));
}

export const patentPriorityKinds = ["priority", "divisional_parent", "addition_parent", "national_phase_parent"] as const;
export const patentPrioritySchema = z.object({
  id: z.string().uuid(), canonical_relationship_id: z.string().uuid(),
  application_id: z.string().uuid(), parent_application_id: z.string().uuid(),
  current_application_title: text(255), current_parent_title: text(255),
  sequence: z.number().int().positive(), application_version: z.number().int().positive(),
  parent_version: z.number().int().positive(), lifecycle_version: z.number().int().nonnegative(),
  parent_lifecycle_version: z.number().int().nonnegative(), supersedes_priority_id: z.string().uuid().nullable(),
  withdrawn: z.boolean(), is_current: z.boolean(),
  review_flags: z.array(z.enum(["office_names_differ", "jurisdictions_differ", "filing_dates_incomplete",
    "priority_date_precedes_parent_filing"])).max(4),
  relation_kind: z.enum(patentPriorityKinds), priority_date: z.string().date(), source: patentSourceSchema,
  reason: text(1000).refine((value) => value.length >= 8), created_at: z.string().datetime({ offset: true }),
}).strict().refine((row) => row.application_id !== row.parent_application_id, "An application cannot link to itself.");
export const patentPriorityPageSchema = z.object({
  application_id: z.string().uuid(), collection_sequence: z.number().int().nonnegative(),
  priorities: z.array(patentPrioritySchema).max(100), next_cursor: z.number().int().positive().nullable(),
}).strict();
export const patentFamilyGraphSchema = z.object({
  family_id: z.string().uuid(), applications: z.array(patentApplicationSchema).max(100),
  priorities: z.array(patentPrioritySchema).max(500),
  applications_next_cursor: text(512).nullable(), priorities_next_cursor: text(512).nullable(),
  has_more_applications: z.boolean(), has_more_relationships: z.boolean(),
}).strict().refine((page) => page.has_more_applications === (page.applications_next_cursor !== null)
  && page.has_more_relationships === (page.priorities_next_cursor !== null), "Graph cursors must match continuation flags.")
  .refine((page) => page.applications.every((application) => application.family_id === page.family_id), "Graph applications must belong to this family.")
  .refine((page) => new Set(page.applications.map((application) => application.id)).size === page.applications.length
    && new Set(page.priorities.map((priority) => priority.id)).size === page.priorities.length, "Graph records cannot repeat identities.");
export type PatentPriority = z.infer<typeof patentPrioritySchema>;
export type PatentPriorityPage = z.infer<typeof patentPriorityPageSchema>;
export const patentPriorityCommandSchema = z.object({
  parent_application_id: z.string().uuid(), relation_kind: z.enum(patentPriorityKinds),
  priority_date: z.string().date(), source: patentSourceSchema,
  expected_application_version: z.number().int().positive(), expected_parent_version: z.number().int().positive(),
  expected_lifecycle_version: z.number().int().nonnegative(), expected_parent_lifecycle_version: z.number().int().nonnegative(),
  expected_priority_sequence: z.number().int().nonnegative(), supersedes_priority_id: z.string().uuid().nullable(),
  withdrawn: z.boolean(), reason: text(1000).refine((value) => value.length >= 8),
}).strict().refine((command) => !command.withdrawn || command.supersedes_priority_id !== null,
  "A withdrawal must identify the recorded relationship.");
export type PatentPriorityCommand = z.infer<typeof patentPriorityCommandSchema>;

export async function fetchPatentPriorities(applicationId: string, history = false,
  continuation?: { cursor: number; sequence: number }, signal?: AbortSignal) {
  const query = new URLSearchParams({ limit: "25", history: String(history) });
  if (continuation) {
    query.set("cursor", String(z.number().int().positive().parse(continuation.cursor)));
    query.set("snapshot_sequence", String(z.number().int().nonnegative().parse(continuation.sequence)));
  }
  return patentPriorityPageSchema.parse(await apiRequest<unknown>(
    `/api/ip/patents/applications/${z.string().uuid().parse(applicationId)}/priorities?${query}`, { signal },
  ));
}

export async function createPatentPriority(applicationId: string, command: PatentPriorityCommand, idempotencyKey: string) {
  return patentPrioritySchema.parse(await apiRequest<unknown>(
    `/api/ip/patents/applications/${z.string().uuid().parse(applicationId)}/priorities`, {
      method: "POST", headers: { "Idempotency-Key": idempotencyKey }, body: patentPriorityCommandSchema.parse(command),
    },
  ));
}

export async function fetchPatentFamilyGraph(familyId: string, applicationsCursor?: string, prioritiesCursor?: string,
  signal?: AbortSignal) {
  const query = new URLSearchParams({ application_limit: "25", priority_limit: "25" });
  if (applicationsCursor) query.set("applications_cursor", applicationsCursor);
  if (prioritiesCursor) query.set("priorities_cursor", prioritiesCursor);
  return patentFamilyGraphSchema.parse(await apiRequest<unknown>(
    `/api/ip/patents/families/${z.string().uuid().parse(familyId)}/graph?${query}`, { signal },
  ));
}
