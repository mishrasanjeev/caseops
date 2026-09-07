import { describe, expect, it, vi } from "vitest";
const request = vi.hoisted(() => vi.fn());
vi.mock("./client", () => ({ apiRequest: request }));
import {
  correctPatentApplication, createPatentApplication, fetchPatentApplication,
  fetchPatentApplicationLifecycleHistory, fetchPatentApplications, patentApplicationFactsSchema,
  patentApplicationSchema, patentFamilyFactsSchema, patentFamilySchema, patentSourceSchema,
  type PatentFamily,
  createPatentParty, fetchPatentParties, patentPartyFactSchema, patentPartySchema,
  createPatentPriority, fetchPatentPriorities, fetchPatentFamilyGraph, patentPrioritySchema,
  patentPriorityCommandSchema, patentFamilyGraphSchema,
} from "./ip-patents";
import { previewIpDocumentName, uploadIpDocument, uploadIpDocumentVersion } from "./endpoints";

const id = "10000000-0000-4000-8000-000000000001";
const facts = { title: "Original invention", client_id: id, disclosure_date: "2026-09-05",
  disclosure_narrative: "Source-preserved disclosure", confidentiality: "restricted" };

describe("Patent contract and shared document compatibility", () => {
  it("accepts a complete source identity and rejects missing identity or extra claims", () => {
    const source = { kind: "document_version", document_id: id, document_version_id: id, content_sha256: "a".repeat(64) };
    expect(patentSourceSchema.parse(source)).toEqual(source);
    expect(patentSourceSchema.safeParse({ ...source, document_id: undefined }).success).toBe(false);
    expect(patentSourceSchema.safeParse({ ...source, verified: true }).success).toBe(false);
    expect(patentFamilyFactsSchema.safeParse({ ...facts, source }).success).toBe(true);
  });
  it.each([" ", "\0invalid", "x".repeat(256)])("rejects invalid title %s", (title) => {
    expect(patentFamilyFactsSchema.safeParse({ ...facts, title }).success).toBe(false);
  });
  it("rejects public disclosure, hidden state writes, and coerced response versions", () => {
    expect(patentFamilyFactsSchema.safeParse({ ...facts, confidentiality: "public" }).success).toBe(false);
    expect(patentFamilyFactsSchema.safeParse({ ...facts, status: "closed" }).success).toBe(false);
    expect(patentFamilySchema.safeParse({ id, docket_id: id, asset_id: id, record_kind: "patent_family",
      version: "1", lifecycle_version: 0, lifecycle_status: "draft", is_active: true,
      created_at: "2026-09-06T00:00:00Z", updated_at: "2026-09-06T00:00:00Z", facts }).success).toBe(false);
  });
  it.each([undefined, "Patent"] as const)("preserves document asset type %s on preview, upload and new version", async (assetType) => {
    request.mockClear(); request.mockResolvedValue({});
    const input = { assetType, clientCode: "CLIENT", mark: "SUBSTRATE", jurisdiction: "IN",
      applicationNo: "", proceedingType: "", proceedingNo: "", documentDate: "2026-09-05" };
    await previewIpDocumentName({ ...input, taxonomyKey: "evidence", version: 1, extension: "txt", existingNames: [] });
    expect(request.mock.calls[0][1].body.asset_type).toBe(assetType ?? "Trademark");
    const file = new File(["Original disclosure"], "source.txt", { type: "text/plain" });
    await uploadIpDocument({ ...input, file, title: "Original", taxonomyKey: "evidence", confidentiality: "restricted", isPrivileged: true, docketId: id });
    await uploadIpDocumentVersion({ ...input, file, documentId: id, expectedCurrentVersion: 1 });
    for (const call of request.mock.calls.slice(1)) {
      expect(JSON.parse(call[1].body.get("metadata_json")).asset_type).toBe(assetType ?? "Trademark");
    }
  });
});

const source = { kind: "document_version" as const, document_id: id, document_version_id: id, content_sha256: "a".repeat(64) };
const applicationFacts = {
  title: "Sourced application", application_kind: "complete" as const, jurisdiction: "IN", office: "IP India",
  filing_date: "2026-09-05", publication_date: null, source_pending_identifier_allocation: false, source,
  identifiers: [{ identifier_kind: "application" as const, raw_value: "  IN/2026-001/A  ", source }],
};
const application = {
  id, docket_id: id, family_id: id, record_kind: "patent_application" as const,
  version: 2, lifecycle_version: 3, lifecycle_status: "draft", is_active: true,
  created_at: "2026-09-06T00:00:00Z", updated_at: "2026-09-06T00:00:00Z",
  prosecution_phase: "disclosure" as const, facts: applicationFacts,
};

const parentId = "10000000-0000-4000-8000-000000000002";
const priority = { id, canonical_relationship_id: id, application_id: id, parent_application_id: parentId,
  current_application_title: applicationFacts.title, current_parent_title: "Parent", sequence: 1,
  application_version: 2, parent_version: 1, lifecycle_version: 3, parent_lifecycle_version: 0,
  supersedes_priority_id: null, withdrawn: false, is_current: true, review_flags: [],
  relation_kind: "priority" as const, priority_date: "2026-09-05", source,
  reason: "Exact sourced relationship.", created_at: "2026-09-07T00:00:00Z" };
const priorityCommand = { parent_application_id: parentId, relation_kind: "priority" as const,
  priority_date: priority.priority_date, source, expected_application_version: 2, expected_parent_version: 1,
  expected_lifecycle_version: 3, expected_parent_lifecycle_version: 0, expected_priority_sequence: 0,
  supersedes_priority_id: null, withdrawn: false, reason: priority.reason };

describe("Complete patent priority and graph contracts", () => {
  it("retains every concurrency token and exact source in the submitted command", async () => {
    request.mockReset(); request.mockResolvedValue(priority);
    expect(patentPrioritySchema.parse(priority)).toEqual(priority);
    await createPatentPriority(id, priorityCommand, "priority-key");
    expect(request).toHaveBeenLastCalledWith(`/api/ip/patents/applications/${id}/priorities`, {
      method: "POST", headers: { "Idempotency-Key": "priority-key" }, body: priorityCommand,
    });
  });
  it.each([{ expected_parent_version: "1" }, { expected_priority_sequence: -1 }, { withdrawn: true },
    { source: { ...source, content_sha256: undefined } }, { relation_kind: "automatic_entitlement" },
    { approved: true }])("rejects malformed priority commands without an HTTP request %j", async (changes) => {
    request.mockReset();
    const malformed = { ...priorityCommand, ...changes };
    expect(patentPriorityCommandSchema.safeParse(malformed).success).toBe(false);
    await expect(createPatentPriority(id, malformed as typeof priorityCommand, "key")).rejects.toThrow();
    expect(request).not.toHaveBeenCalled();
  });
  it("pins independent continuation tokens and passes the cancellation signal", async () => {
    request.mockReset();
    const signal = new AbortController().signal;
    request.mockResolvedValue({ application_id: id, collection_sequence: 4, priorities: [priority], next_cursor: null });
    await fetchPatentPriorities(id, true, { cursor: 3, sequence: 4 }, signal);
    expect(request).toHaveBeenLastCalledWith(`/api/ip/patents/applications/${id}/priorities?limit=25&history=true&cursor=3&snapshot_sequence=4`, { signal });
    request.mockResolvedValue({ family_id: id, applications: [application], priorities: [priority],
      applications_next_cursor: null, priorities_next_cursor: null, has_more_applications: false, has_more_relationships: false });
    await fetchPatentFamilyGraph(id, parentId, "4:3", signal);
    expect(request).toHaveBeenLastCalledWith(`/api/ip/patents/families/${id}/graph?application_limit=25&priority_limit=25&applications_cursor=${parentId}&priorities_cursor=4%3A3`, { signal });
  });
  it("rejects self links, unknown review labels and incoherent graph pages", () => {
    expect(patentPrioritySchema.safeParse({ ...priority, parent_application_id: id }).success).toBe(false);
    expect(patentPrioritySchema.safeParse({ ...priority, review_flags: ["legally_validated"] }).success).toBe(false);
    const graph = { family_id: id, applications: [application], priorities: [priority],
      applications_next_cursor: null, priorities_next_cursor: null, has_more_applications: false, has_more_relationships: false };
    expect(patentFamilyGraphSchema.parse(graph)).toEqual(graph);
    for (const changes of [{ has_more_relationships: true }, { applications: [application, application] },
      { priorities: [priority, priority] }, { applications: [{ ...application, family_id: parentId }] },
      { has_more_applications: true, applications_next_cursor: " " }]) {
      expect(patentFamilyGraphSchema.safeParse({ ...graph, ...changes }).success).toBe(false);
    }
  });
});

const partyFact = {
  role: "inventor" as const, name: "Original inventor", client_id: null,
  address: { address_lines: ["Original address"], city: "Delhi", region: null, postal_code: null, country_code: "IN" },
  effective_from: "2026-09-01", effective_until: null, source,
};
const party = { id, docket_id: id, sequence: 1, anchor_version: 2, lifecycle_version: 3,
  supersedes_party_id: null, is_current: true, fact: partyFact,
  reason: "Exact source transcribed.", created_at: "2026-09-07T00:00:00Z" };

describe("Complete sourced patent party contract", () => {
  it("preserves the source, address, three concurrency tokens and immutable replacement identity", async () => {
    request.mockReset(); request.mockResolvedValue(party);
    expect(patentPartySchema.parse(party)).toEqual(party);
    await createPatentParty(application, 0, partyFact, party.reason, null, "party-key");
    expect(request).toHaveBeenLastCalledWith(`/api/ip/patents/dockets/${id}/parties`, {
      method: "POST", headers: { "Idempotency-Key": "party-key" }, body: {
        expected_version: 2, expected_lifecycle_version: 3, expected_party_sequence: 0,
        fact: partyFact, reason: party.reason, supersedes_party_id: null,
      },
    });
  });
  it.each([
    { effective_until: "2026-08-31" }, { role: "owner" }, { name: " " },
    { address: { ...partyFact.address, address_lines: [] } },
    { address: { ...partyFact.address, address_lines: Array(6).fill("line") } },
    { address: { ...partyFact.address, country_code: "india" } },
    { address: { ...partyFact.address, approved: true } },
    { source: { ...source, content_sha256: undefined } },
  ])("rejects incomplete or invented party facts %j without a request", async (changes) => {
    request.mockReset();
    const invalid = { ...partyFact, ...changes };
    expect(patentPartyFactSchema.safeParse(invalid).success).toBe(false);
    await expect(createPatentParty(application, 0, invalid as typeof partyFact, party.reason, null, "key")).rejects.toThrow();
    expect(request).not.toHaveBeenCalled();
  });
  it("propagates snapshot continuation and cancellation without coercing the returned sequence", async () => {
    const signal = new AbortController().signal;
    request.mockReset(); request.mockResolvedValue({ docket_id: id, collection_sequence: 4, parties: [party], next_cursor: null });
    await fetchPatentParties(id, true, { cursor: 3, sequence: 4 }, signal);
    expect(request).toHaveBeenLastCalledWith(`/api/ip/patents/dockets/${id}/parties?limit=25&history=true&cursor=3&snapshot_sequence=4`, { signal });
    expect(patentPartySchema.safeParse({ ...party, sequence: "1" }).success).toBe(false);
    expect(patentPartySchema.safeParse({ ...party, owner_verified: true }).success).toBe(false);
  });
});

describe("Source-complete patent application API contract", () => {
  it("round-trips every nested source and preserves the exact supplied number", () => {
    expect(patentApplicationSchema.parse(application)).toEqual(application);
    for (const field of ["document_id", "document_version_id", "content_sha256"]) {
      const incomplete = { ...source, [field]: undefined };
      expect(patentApplicationFactsSchema.safeParse({ ...applicationFacts, source: incomplete }).success).toBe(false);
      expect(patentApplicationFactsSchema.safeParse({ ...applicationFacts,
        identifiers: [{ ...applicationFacts.identifiers[0], source: incomplete }],
      }).success).toBe(false);
    }
    expect(patentApplicationFactsSchema.safeParse({ ...applicationFacts,
      identifiers: [{ ...applicationFacts.identifiers[0], verified: true }],
    }).success).toBe(false);
  });
  it.each([
    { publication_date: "2026-09-04" }, { source_pending_identifier_allocation: true },
    { identifiers: [applicationFacts.identifiers[0], applicationFacts.identifiers[0]] },
    { identifiers: Array.from({ length: 21 }, (_, index) => ({ ...applicationFacts.identifiers[0], raw_value: String(index) })) },
    { prosecution_phase: "granted" }, { jurisdiction: "invented" }, { office: " " },
  ])("rejects incompatible or hidden facts %j before a mutation", async (changes) => {
    request.mockClear();
    await expect(correctPatentApplication(application, { ...applicationFacts, ...changes }, "Correct the source record.")).rejects.toThrow();
    expect(request).not.toHaveBeenCalled();
  });
  it("pins both concurrency versions and the creation idempotency key", async () => {
    request.mockReset(); request.mockResolvedValue(application);
    const family = { id, version: 4, lifecycle_version: 5 } as PatentFamily;
    await createPatentApplication(family, applicationFacts, "durable-key");
    expect(request).toHaveBeenLastCalledWith("/api/ip/patents/applications", {
      method: "POST", headers: { "Idempotency-Key": "durable-key" }, body: {
        family_id: id, expected_family_version: 4, expected_family_lifecycle_version: 5, facts: applicationFacts,
      },
    });
    await correctPatentApplication(application, applicationFacts, "Correct the source record.");
    expect(request).toHaveBeenLastCalledWith(`/api/ip/patents/applications/${id}/corrections`, {
      method: "POST", body: { expected_version: 2, expected_lifecycle_version: 3,
        reason: "Correct the source record.", facts: applicationFacts },
    });
  });
  it("keeps filters, cancellation and historical reads on their canonical routes", async () => {
    request.mockReset();
    const signal = new AbortController().signal;
    request.mockResolvedValue({ applications: [application], next_cursor: null });
    await fetchPatentApplications(id, id, signal, "terminal", "IN/2026-001/A");
    const url = new URL(request.mock.calls[0][0], "http://localhost");
    expect(Object.fromEntries(url.searchParams)).toEqual({ limit: "50", family_id: id, cursor: id, status_scope: "terminal", q: "IN/2026-001/A" });
    expect(request.mock.calls[0][1].signal).toBe(signal);
    request.mockResolvedValue(application);
    await fetchPatentApplication(id, 1, signal);
    expect(request).toHaveBeenLastCalledWith(`/api/ip/patents/applications/${id}/versions/1`, { signal });
    request.mockResolvedValue({ events: [], next_cursor: null });
    await fetchPatentApplicationLifecycleHistory(id, 7, signal);
    expect(request).toHaveBeenLastCalledWith(`/api/ip/patents/applications/${id}/lifecycle-history?limit=25&cursor=7`, { signal });
  });
});
