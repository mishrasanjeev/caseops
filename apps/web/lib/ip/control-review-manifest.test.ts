import { describe, expect, it } from "vitest";

import type { IpControlReview } from "@/lib/api/endpoints";
import { buildControlReviewManifest } from "@/lib/ip/control-review-manifest";

const REVIEW: IpControlReview = {
  id: "review-1",
  generated_at: "2026-08-15T06:31:00Z",
  filters: { team: "tm-bench" },
  freshness: { stale_sources: ["matter_deadlines"], failed_queries: [] },
  completeness_status: "incomplete",
  incompleteness_reasons: ["matter_deadlines is stale"],
  mandatory_exceptions: [
    { docket_id: "ip-9", kind: "uncovered", critical: true },
    { docket_id: "ip-4", kind: "open_incident", critical: true },
  ],
  query_version: "ip-docket-control-v1",
  manifest_sha256: "b".repeat(64),
  export_status: "not_requested",
  export_error_redacted: null,
  signer_label_snapshot: null,
  signed_off_at: null,
  review_policy: {
    policy_version: "daily-docket-review-v1",
    required_signature_count: 2,
    required_sample_size: 1,
    distinct_preparer_and_reviewer: true,
  },
  predecessor_review_id: null,
  delta: {
    predecessor_review_id: null,
    predecessor_manifest_sha256: null,
    added_docket_ids: [],
    removed_docket_ids: [],
    changed_docket_ids: [],
    added_exception_keys: [],
    removed_exception_keys: [],
  },
  exception_decisions: [],
  reviewer_samples: [],
  signatures: [],
  pending_exception_count: 2,
  annotated_exception_count: 0,
  signoff_status: "draft",
  version: 1,
  report: {
    generated_at: "2026-08-15T06:31:00Z",
    docket_count: 18,
    ready_count: 15,
    uncovered_deadline_count: 1,
    open_incident_count: 1,
    unprojected_calendar_count: 2,
    inactive_coverage_count: 1,
    total_cost_minor_by_currency: {},
  },
  snapshot: {
    schema_version: 1,
    query_version: "ip-docket-control-v1",
    generated_at: "2026-08-15T06:31:00Z",
    timezone: "Asia/Kolkata",
    filters: { team: "tm-bench" },
    freshness: { stale_sources: ["matter_deadlines"], failed_queries: [] },
    hidden_restricted_count_policy: "omit_without_count",
    included_records: [
      { docket_id: "ip-9", current_version: 3, sha256: "c".repeat(64) },
    ],
    report: {
      generated_at: "2026-08-15T06:31:00Z",
      docket_count: 18,
      ready_count: 15,
      uncovered_deadline_count: 1,
      open_incident_count: 1,
      unprojected_calendar_count: 2,
      inactive_coverage_count: 1,
      total_cost_minor_by_currency: {},
    },
    mandatory_exceptions: [
      { docket_id: "ip-9", kind: "uncovered", critical: true },
      { docket_id: "ip-4", kind: "open_incident", critical: true },
    ],
    incompleteness_reasons: ["matter_deadlines is stale"],
    review_policy: null,
    delta: null,
  },
};

describe("buildControlReviewManifest", () => {
  it("shows generation time, filters and freshness, as CAL-OPS-09 requires", () => {
    const html = buildControlReviewManifest(REVIEW);

    expect(html).toContain("2026-08-15T06:31:00Z");
    expect(html).toContain("team=tm-bench");
    expect(html).toContain("Stale sources: matter_deadlines");
    expect(html).toContain("incomplete");
    expect(html).toContain("matter_deadlines is stale");
    // The hash is what lets a filed copy be checked against the stored review.
    expect(html).toContain("b".repeat(64));
    expect(html).toContain("ip-docket-control-v1");
    expect(html).toContain("Asia/Kolkata");
  });

  it("lists every mandatory exception", () => {
    const html = buildControlReviewManifest(REVIEW);

    expect(html).toContain("Exceptions (2)");
    expect(html).toContain("Deadline has no coverage");
    expect(html).toContain("Open incident");
    expect(html).toContain("ip-9");
  });

  it("lists the immutable included-record versions and hashes", () => {
    const html = buildControlReviewManifest(REVIEW);

    expect(html).toContain("Included records (1)");
    expect(html).toContain("record ip-9");
    expect(html).toContain("version 3");
    expect(html).toContain("c".repeat(64));
  });

  it("says so plainly when nothing was excepted", () => {
    const html = buildControlReviewManifest({
      ...REVIEW,
      mandatory_exceptions: [],
    });

    // An absent section reads as an omission; a stated "none" reads as a check.
    expect(html).toContain("None recorded at generation.");
  });

  it("states that sources were current when none were stale", () => {
    const html = buildControlReviewManifest({
      ...REVIEW,
      freshness: { stale_sources: [], failed_queries: [] },
    });

    expect(html).toContain("All sources current at generation");
  });

  it("omits record names and labels the retained evidence confidential", () => {
    const html = buildControlReviewManifest(REVIEW);

    expect(html).not.toMatch(/mark/i);
    expect(html).not.toContain("docket_title");
    // Only ids identify records.
    expect(html).toContain("record ip-9");
    expect(html).toContain("Confidential firm material");
  });

  it("escapes values rather than interpolating them into markup", () => {
    const html = buildControlReviewManifest({
      ...REVIEW,
      incompleteness_reasons: ['<script>alert("x")</script>'],
    });

    expect(html).not.toContain("<script>alert");
    expect(html).toContain("&lt;script&gt;");
  });

  it("records the signature on a signed review", () => {
    const html = buildControlReviewManifest({
      ...REVIEW,
      signed_off_at: "2026-08-15T07:00:00Z",
      signer_label_snapshot: "Priya Raghavan",
      pending_exception_count: 0,
      signoff_status: "signed",
      exception_decisions: [
        {
          docket_id: "ip-9",
          exception_kind: "uncovered",
          disposition: "annotated",
          annotation: "Follow-up assigned and controlled.",
          evidence_reference: "Matter note 42",
          decided_by_membership_id: "member-1",
          decided_at: "2026-08-15T06:40:00Z",
        },
      ],
      reviewer_samples: [
        {
          docket_id: "ip-9",
          reviewer_membership_id: "member-2",
          source_evidence_reference: "Registry snapshot 42",
          calculation_evidence_reference: "Deadline worksheet 42",
          coverage_evidence_reference: "Coverage roster 42",
          notes: null,
          sampled_at: "2026-08-15T06:50:00Z",
        },
      ],
      signatures: [
        {
          signer_membership_id: "member-1",
          signer_role: "preparer",
          signer_label_snapshot: "Anand Rao",
          attestation: "Prepared and checked the daily docket.",
          manifest_sha256: "b".repeat(64),
          sequence: 1,
          signed_at: "2026-08-15T06:45:00Z",
        },
        {
          signer_membership_id: "member-2",
          signer_role: "reviewer",
          signer_label_snapshot: "Priya Raghavan",
          attestation: "Independently reviewed the required sample.",
          manifest_sha256: "b".repeat(64),
          sequence: 2,
          signed_at: "2026-08-15T07:00:00Z",
        },
      ],
    });

    expect(html).toContain("Signed off");
    expect(html).toContain("Priya Raghavan");
    expect(html).toContain("Signatures (2/2)");
    expect(html).toContain("Follow-up assigned and controlled.");
    expect(html).toContain("Registry snapshot 42");
  });
});
