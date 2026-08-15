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
  manifest_sha256: "b".repeat(64),
  export_status: "not_requested",
  export_error_redacted: null,
  signer_label_snapshot: null,
  signed_off_at: null,
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
  });

  it("lists every mandatory exception", () => {
    const html = buildControlReviewManifest(REVIEW);

    expect(html).toContain("Exceptions (2)");
    expect(html).toContain("Deadline has no coverage");
    expect(html).toContain("Open incident");
    expect(html).toContain("ip-9");
  });

  it("says so plainly when nothing was excepted", () => {
    const html = buildControlReviewManifest({ ...REVIEW, mandatory_exceptions: [] });

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

  it("carries identifiers and counts but no privileged content", () => {
    // A printout left on a desk must not disclose what the firm is working on.
    const html = buildControlReviewManifest(REVIEW);

    expect(html).not.toMatch(/mark/i);
    expect(html).not.toContain("docket_title");
    // Only ids identify records.
    expect(html).toContain("record ip-9");
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
    });

    expect(html).toContain("Signed off");
    expect(html).toContain("Priya Raghavan");
  });
});
