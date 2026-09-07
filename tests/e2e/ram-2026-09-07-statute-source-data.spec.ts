/** BUG-010: every published provision and withheld row, against the real API. */
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import path from "node:path";
import { expect, request, test as baseTest, type APIRequestContext } from "@playwright/test";
import { noPaidProviderHeaders } from "./support/cost-controls";

type Provision = {
  statute_id: string;
  section_number: string;
  section_label: string;
  section_text: string;
  section_text_source: string;
  source_sha256: string;
  source_url: string;
  source_publisher: string;
  issuing_body: string;
  source_category: string;
  source_status: string;
  legal_status: string;
  effective_from: string | null;
  source_locator_type: string;
  source_retrieved_at: string;
  link_health_status: string;
  quarantine_reason: string | null;
  exact_source_version: string;
  verification_status: string;
  editorial_notes: string;
};
const rows: Provision[] = JSON.parse(readFileSync(path.resolve(
  __dirname, "../../apps/api/src/caseops_api/scripts/seed_data/verified_india_code_sources.json",
), "utf8"));
const BASE = process.env.PROD_BASE_URL || process.env.CASEOPS_WEB_BASE_URL || "http://127.0.0.1:3100";
const LOCAL = ["localhost", "127.0.0.1"].includes(new URL(BASE).hostname);
const EXISTING_QA = Boolean(process.env.PROD_API_BASE_URL);
const API = process.env.PROD_API_BASE_URL || (LOCAL
  ? `http://127.0.0.1:${process.env.CASEOPS_E2E_API_PORT || "8000"}` : "https://api.caseops.ai");
const test = baseTest.extend<{}, { sourceApi: APIRequestContext }>({
  sourceApi: [async ({}, use, workerInfo) => {
    const setup = await request.newContext({ extraHTTPHeaders: noPaidProviderHeaders });
    let api: APIRequestContext | undefined;
    try {
      let credentials;
      if (LOCAL && !EXISTING_QA) {
        const identity = `statutes-${Date.now()}-${workerInfo.workerIndex}`;
        const response = await setup.post(`${API}/api/bootstrap/company`, { data: {
          company_name: "Official statute source regression", company_slug: identity,
          company_type: "law_firm", owner_full_name: "Source Regression",
          owner_email: `${identity}@example.com`, owner_password: "LocalStatuteFixture123!",
        } });
        expect(response.status(), await response.text()).toBe(200);
        credentials = await response.json();
      } else {
        const expected = process.env.CASEOPS_EXPECTED_RELEASE_SHA || "";
        expect(expected).toMatch(/^[0-9a-f]{40}$/);
        for (const url of [`${API}/api/build`, `${BASE}/api/release-identity`]) {
          const identity = await setup.get(url);
          expect(identity.status(), await identity.text()).toBe(200);
          expect((await identity.json()).release_sha).toBe(expected);
        }
        if (!process.env.CASEOPS_RAM_PROD_PASSWORD) throw new Error("CASEOPS_RAM_PROD_PASSWORD is required");
        const response = await setup.post(`${API}/api/auth/login`, { data: {
          company_slug: process.env.CASEOPS_RAM_PROD_SLUG || "test-legal",
          email: process.env.CASEOPS_RAM_PROD_EMAIL || "ram@testfirm.com",
          password: process.env.CASEOPS_RAM_PROD_PASSWORD,
        } });
        expect(response.status(), await response.text()).toBe(200);
        credentials = await response.json();
      }
      api = await request.newContext({ extraHTTPHeaders: {
        ...noPaidProviderHeaders, Authorization: `Bearer ${credentials.access_token}`,
      } });
      console.log(`Statute source worker ${workerInfo.workerIndex}: authenticated once`);
      await use(api);
    } finally {
      await api?.dispose();
      await setup.dispose();
    }
  }, { scope: "worker" }],
});

// Bound each independent read-only batch instead of increasing request deadlines.
for (let offset = 0; offset < rows.length; offset += 40) {
  const batch = rows.slice(offset, offset + 40);
  test(`BUG-010 source records ${offset + 1}-${offset + batch.length} of ${rows.length}`, async ({ sourceApi: api }) => {
    for (const expected of batch) {
      const response = await api.get(
        `${API}/api/statutes/${expected.statute_id}/sections/${encodeURIComponent(expected.section_number)}`,
      );
      expect(response.status(), await response.text()).toBe(200);
      const actual = (await response.json()).section;
      for (const field of [
        "statute_id", "section_label", "section_text_source", "source_publisher", "issuing_body",
        "source_category", "source_status", "legal_status", "effective_from", "source_locator_type",
        "link_health_status", "quarantine_reason",
      ] as const) {
        expect(actual[field], `${expected.statute_id} ${expected.section_number}: ${field}`).toBe(expected[field]);
      }
      expect(Date.parse(actual.source_retrieved_at)).toBe(Date.parse(expected.source_retrieved_at));
      expect(actual.section_number).toBe(expected.section_number);
      expect(actual.verification_status).toBe(expected.verification_status);
      expect(actual.source_sha256).toBe(expected.source_sha256);
      expect(actual.section_url).toBe(expected.source_url);
      expect(actual.exact_source_version).toBe(expected.exact_source_version);
      expect(actual.editorial_notes).toBe(expected.editorial_notes);
      if (expected.verification_status === "verified_official") {
        expect(actual.section_text).toBe(expected.section_text);
        expect(createHash("sha256").update(actual.section_text).digest("hex")).toBe(expected.source_sha256);
      } else {
        expect(actual.section_text).toBeNull();
      }
    }
  });
}
