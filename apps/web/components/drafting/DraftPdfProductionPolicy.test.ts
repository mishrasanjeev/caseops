import { Blob as NodeBlob } from "node:buffer";
import { createHash, webcrypto } from "node:crypto";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { allowedProductionDraftRead, capturePdfDownloadsInMemory, citationReviewExportGuard, productionDraftRequestPolicy, productionDraftSettings, reportedDraftTarget } from "../../../../tests/e2e/support/draft_pdf_production_policy_20261111";

const env = {
  PROD_API_BASE_URL: "https://api.caseops.ai", CASEOPS_EXPECTED_RELEASE_SHA: "a".repeat(40),
  CASEOPS_RAM_PROD_SLUG: "test-legal", CASEOPS_RAM_PROD_EMAIL: "ram@testfirm.com", CASEOPS_RAM_PROD_PASSWORD: "Synthetic-unit-secret-only",
};
const settings = { web: "https://caseops.ai", api: "https://api.caseops.ai" };
const draftPath = `/api/matters/${reportedDraftTarget.matterId}/drafts/${reportedDraftTarget.draftId}`;
const guard = { detail: "This draft version has zero verified citations. PDF export is refused until review." };

afterEach(() => vi.unstubAllGlobals());

describe("BUG001 production-only read boundary", () => {
  it("binds the actual reporter, exact serving SHA, and owner-reported target", () => {
    expect(productionDraftSettings(settings.web, env)).toMatchObject({ ...settings, sha: env.CASEOPS_EXPECTED_RELEASE_SHA, ...reportedDraftTarget });
  });
  it.each(Object.keys(env))("requires %s without a skipped acceptance", key => {
    expect(() => productionDraftSettings(settings.web, { ...env, [key]: undefined })).toThrow();
  });
  it.each(["http://caseops.ai", "https://other.example", "https://caseops.ai/private", "https://actor:secret@caseops.ai", "not a URL"])("rejects an unsafe production origin", origin => {
    expect(() => productionDraftSettings(origin, env)).toThrow();
  });
  it.each([
    { CASEOPS_EXPECTED_RELEASE_SHA: "861aea48e" }, { CASEOPS_RAM_PROD_SLUG: "other-tenant" },
    { CASEOPS_RAM_PROD_EMAIL: "other@example.com" }, { CASEOPS_B5_DRAFT_ID: "another-record" },
    { CASEOPS_B5_DRAFT_MATTER_ID: "another-record" },
  ])("refuses replacement actor, target or abbreviated release identity", override => {
    expect(() => productionDraftSettings(settings.web, { ...env, ...override })).toThrow();
  });
  it.each(["/generate", "/approve", "/submit", "/finalize", "/export.docx", "/filing-bundle.zip"])("does not allow %s on the reported target", suffix => {
    expect(allowedProductionDraftRead(`${draftPath}${suffix}`)).toBe(false);
    expect(productionDraftRequestPolicy(`${settings.api}${draftPath}${suffix}`, "POST", "no-paid-providers", settings)).toBe("blocked");
  });
  it("permits marked PDF reads and login preflight but never unmarked or mutation requests", () => {
    const pdf = `${settings.api}${draftPath}/export.pdf?version_id=retained`;
    expect(productionDraftRequestPolicy(pdf, "GET", "no-paid-providers", settings)).toBe("read");
    expect(productionDraftRequestPolicy(pdf, "GET", undefined, settings)).toBe("blocked");
    expect(productionDraftRequestPolicy(pdf, "PATCH", "no-paid-providers", settings)).toBe("blocked");
    expect(productionDraftRequestPolicy(`${settings.api}/api/auth/login`, "OPTIONS", undefined, settings)).toBe("read");
    expect(productionDraftRequestPolicy(`${settings.api}/api/auth/login`, "POST", "no-paid-providers", settings)).toBe("login");
    expect(productionDraftRequestPolicy(`${settings.api}/api/bootstrap/company`, "POST", "no-paid-providers", settings)).toBe("blocked");
    expect(productionDraftRequestPolicy(`${settings.api}/api/authorities/providers/search`, "GET", "no-paid-providers", settings)).toBe("blocked");
    expect(productionDraftRequestPolicy("https://external.example/credit", "GET", "no-paid-providers", settings)).toBe("external");
  });
  it("recognizes only a persisted-state-consistent citation/review guard", () => {
    expect(citationReviewExportGuard(422, guard, "draft", 0)).toBe(true);
    expect(citationReviewExportGuard(422, guard, "approved", 0)).toBe(false);
    expect(citationReviewExportGuard(422, guard, "draft", 1)).toBe(false);
    expect(citationReviewExportGuard(503, guard, "draft", 0)).toBe(false);
    expect(citationReviewExportGuard(422, { detail: "Unsupported characters" }, "draft", 0)).toBe(false);
  });
  it("admits only the exact reported Matter workspace GET, never other records or writes", () => {
    const workspace = `/api/matters/${reportedDraftTarget.matterId}/workspace`;
    expect(allowedProductionDraftRead(workspace)).toBe(true);
    expect(productionDraftRequestPolicy(`${settings.api}${workspace}`, "GET", "no-paid-providers", settings)).toBe("read");
    expect(allowedProductionDraftRead("/api/matters/another-matter/workspace")).toBe(false);
    expect(productionDraftRequestPolicy(`${settings.api}${workspace}`, "PATCH", "no-paid-providers", settings)).toBe("blocked");
    expect(productionDraftRequestPolicy(`${settings.api}${workspace}`, "POST", "no-paid-providers", settings)).toBe("blocked");
  });
});

describe("BUG001 memory-only download proof", () => {
  beforeEach(() => {
    vi.stubGlobal("Blob", NodeBlob);
    vi.stubGlobal("URL", class extends URL {
      static createObjectURL = vi.fn(() => "blob:https://caseops.ai/synthetic");
      static revokeObjectURL = vi.fn();
    });
  });
  it("observes the real anchor handoff, prevents native saving, and retains only digest metadata", async () => {
    const bytes = new Blob(["%PDF-synthetic-unit-bytes"], { type: "application/pdf" });
    vi.stubGlobal("crypto", webcrypto);
    const fetch = vi.fn().mockRejectedValue(new Error("CSP forbids blob URL fetches"));
    vi.stubGlobal("fetch", fetch);
    const cleanup = capturePdfDownloadsInMemory();
    try {
      const anchor = document.createElement("a");
      anchor.href = URL.createObjectURL(bytes);
      anchor.download = "synthetic.pdf";
      document.body.append(anchor);
      const event = new MouseEvent("click", { bubbles: true, cancelable: true });
      expect(anchor.dispatchEvent(event)).toBe(false);
      expect(event.defaultPrevented).toBe(true);
      const expected = createHash("sha256").update(Buffer.from(await bytes.arrayBuffer())).digest("hex");
      await vi.waitFor(() => expect((window as unknown as { __bug001Download: object }).__bug001Download).toEqual({ count: 1, bytes: bytes.size, hash: expected, invalid: false }));
      expect(fetch).not.toHaveBeenCalled();
      anchor.remove();
    } finally { cleanup(); }
  });
  it("blocks a non-blob download without fetching or retaining document bytes", () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    const cleanup = capturePdfDownloadsInMemory();
    try {
      const anchor = document.createElement("a");
      anchor.href = "https://api.caseops.ai/export.pdf";
      anchor.download = "synthetic.pdf";
      document.body.append(anchor);
      expect(anchor.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }))).toBe(false);
      expect(fetch).not.toHaveBeenCalled();
      expect((window as unknown as { __bug001Download: { invalid: boolean } }).__bug001Download.invalid).toBe(true);
      anchor.remove();
    } finally { cleanup(); }
  });
  it("rejects a revoked Blob identity without attempting a CSP-blocked fetch fallback", () => {
    const fetch = vi.fn().mockRejectedValue(new Error("CSP forbids blob URL fetches"));
    vi.stubGlobal("fetch", fetch);
    const cleanup = capturePdfDownloadsInMemory();
    try {
      const anchor = document.createElement("a");
      anchor.href = URL.createObjectURL(new Blob(["%PDF-synthetic"], { type: "application/pdf" }));
      URL.revokeObjectURL(anchor.href);
      anchor.download = "synthetic.pdf";
      document.body.append(anchor);
      expect(anchor.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }))).toBe(false);
      expect((window as unknown as { __bug001Download: { invalid: boolean } }).__bug001Download.invalid).toBe(true);
      expect(fetch).not.toHaveBeenCalled();
      anchor.remove();
    } finally { cleanup(); }
  });
});
