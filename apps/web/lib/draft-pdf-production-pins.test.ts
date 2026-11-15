// @vitest-environment node

import { createHash } from "node:crypto";

import { describe, expect, it, vi } from "vitest";

import type { Draft } from "./api/schemas";
import { assertReportedDraftSource, reportedDraftTarget } from "../../../tests/e2e/support/draft_pdf_production_policy_20261111";

const canonicalDraftCall: (draft: Draft, digest: (body: string) => string) => Draft["versions"][number] = assertReportedDraftSource;

describe("BUG001 immutable reported source pins", () => {
  const retained = (): { id: string; matter_id: string | null; current_version_id: string;
    versions: Array<{ id: string; body: string; citations: string[] }> } => ({ id: reportedDraftTarget.draftId,
    matter_id: reportedDraftTarget.matterId, current_version_id: reportedDraftTarget.versionId,
    versions: [{ id: reportedDraftTarget.versionId, body: "Synthetic unit source \u0915\n", citations: [] }] });
  it("pins the reviewed version and UTF-8 digest without a configurable acceptance override", () => {
    expect(canonicalDraftCall).toBe(assertReportedDraftSource);
    expect(reportedDraftTarget.versionId).toBe("cc114a40-7bb5-422d-9499-988b69c0f4d4");
    expect(reportedDraftTarget.bodySha256).toBe("71cf6b959c63e107c46d84b93e736ed8f98418e95fbbf892dd6614490bf1f074");
    const source = retained(), before = JSON.stringify(source);
    const digest = vi.fn(() => reportedDraftTarget.bodySha256);
    expect(assertReportedDraftSource(source, digest)).toBe(source.versions[0]);
    expect(digest).toHaveBeenCalledExactlyOnceWith(source.versions[0].body);
    expect(JSON.stringify(source)).toBe(before);
  });
  it.each(["current", "row", "missing", "duplicate", "draft", "matter", "null_matter"])("refuses %s identity drift without modifying source", fault => {
    const source = retained();
    if (fault === "current") source.current_version_id = "different";
    if (fault === "row") source.versions[0].id = "different";
    if (fault === "missing") source.versions = [];
    if (fault === "duplicate") source.versions.push({ ...source.versions[0] });
    if (fault === "draft") source.id = "different";
    if (fault === "matter") source.matter_id = "different";
    if (fault === "null_matter") source.matter_id = null;
    const before = JSON.stringify(source), digest = vi.fn(() => reportedDraftTarget.bodySha256);
    expect(() => assertReportedDraftSource(source, digest)).toThrow(/Reported draft/);
    expect(digest).not.toHaveBeenCalled();
    expect(JSON.stringify(source)).toBe(before);
  });
  it.each(["Synthetic unit source \u0915\n", "Synthetic unit source \u0915\r\n", "changed"])("rejects unreviewed UTF-8 bytes without normalization or mutation: %#", body => {
    const source = retained();
    source.versions[0].body = body;
    const before = JSON.stringify(source);
    const digest = vi.fn((value: string) => createHash("sha256").update(value, "utf8").digest("hex"));
    expect(() => assertReportedDraftSource(source, digest)).toThrow(/source digest/);
    expect(digest).toHaveBeenCalledExactlyOnceWith(body);
    expect(JSON.stringify(source)).toBe(before);
  });
});
