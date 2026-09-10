import { describe, expect, it } from "vitest";
import { patentEvidenceSchema, patentProsecutionPreviewSchema, patentProsecutionSchema } from "./ip-patent-prosecution";

const id = "10000000-0000-4000-8000-000000000001";
const source = { kind: "document_version", document_id: id, document_version_id: id, content_sha256: "a".repeat(64) };
const base = { id, application_id: id, sequence: 1, anchor_version: 1, lifecycle_version: 0, reason: "Sourced test fact.", created_at: "2026-09-09T00:00:00Z", source };
const evidence = { ...base, root_id: id, predecessor_id: null, edition: 1, is_current: true, title: "Exact claims", document_kind: "claims", documents: [{ document_kind: "claims", source }], manifest_sha256: "b".repeat(64) };
const preview = { application_id: id, work_sequence: 1, current_phase: "disclosure", proposed_phase: "filed", backdated: false,
  affected_deadline_ids: [], required_acknowledgements: [], preview_sha256: "c".repeat(64), changes_deadlines: false, authoritative_calculation_available: false };

describe("Canonical patent prosecution contracts", () => {
  it("parses exact manifests, source hashes and immutable event impact", () => {
    expect(patentEvidenceSchema.parse(evidence)).toEqual(evidence);
    const event = { ...base, event_kind: "filing", received_on: "2026-09-09", effective_on: "2026-09-09",
      evidence_id: id, before_phase: "disclosure", after_phase: "filed", exceptional_transition_reason: null, impact: preview };
    expect(patentProsecutionSchema.parse(event)).toEqual(event);
  });
  it("rejects nested contract drift, invented document kinds and legal automation claims", () => {
    expect(patentEvidenceSchema.safeParse({ ...evidence, documents: [{ document_kind: "trademark", source }] }).success).toBe(false);
    expect(patentEvidenceSchema.safeParse({ ...evidence, source: { ...source, approved: true } }).success).toBe(false);
    expect(patentEvidenceSchema.safeParse({ ...evidence, documents: evidence.documents.concat(Array(20).fill(evidence.documents[0])) }).success).toBe(false);
    expect(patentProsecutionPreviewSchema.safeParse({ ...preview, authoritative_calculation_available: true }).success).toBe(false);
    expect(patentProsecutionPreviewSchema.safeParse({ ...preview, required_acknowledgements: ["silently_reopen"] }).success).toBe(false);
  });
});
