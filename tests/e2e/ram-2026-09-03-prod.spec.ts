/**
 * Bulk Matter Exact Court/alias regression. Runs against the local production
 * build and, after deployment, the supplied tester tenant. Automated requests
 * carry the no-paid-providers header from both Playwright configs.
 */
import {
  expect,
  request,
  test,
  type APIRequestContext,
  type APIResponse,
  type Page,
} from "@playwright/test";

import { buildMinimalXlsx } from "./support/minimal-xlsx";
import { seedVerifiedLocalStatute } from "./support/verified-statute-fixture";

const envOr = (key: string, fallback: string): string =>
  (process.env[key] ?? "").trim() || fallback;
const BASE_URL = envOr(
  "PROD_BASE_URL",
  envOr("CASEOPS_WEB_BASE_URL", "http://127.0.0.1:3100"),
);
const host = new URL(BASE_URL).hostname;
const IS_LOCAL = host === "127.0.0.1" || host === "localhost";
const API_BASE_URL = envOr(
  "PROD_API_BASE_URL",
  IS_LOCAL
    ? `http://127.0.0.1:${envOr("CASEOPS_E2E_API_PORT", "8000")}`
    : "https://api.caseops.ai",
);
const RUN_ID =
  `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`.toUpperCase();
const COMPANY_SLUG = envOr(
  "CASEOPS_RAM_PROD_SLUG",
  IS_LOCAL ? `ram-sep03-${RUN_ID.toLowerCase()}` : "legal",
);
const TESTER_EMAIL = envOr(
  "CASEOPS_RAM_PROD_EMAIL",
  IS_LOCAL
    ? `ram-sep03-${RUN_ID.toLowerCase()}@example.com`
    : "hari.gupta@gmail.com",
);
const LOCAL_PASSWORD = "RamSep03Local!";

type MatterRecord = {
  id: string;
  matter_code: string;
  status: "intake" | "active" | "on_hold" | "disposed";
  updated_at: string;
  forum_level: string;
  court_name: string | null;
  forum_catalog_entry_id: string | null;
  forum_state: string | null;
  forum_consumer_level: string | null;
};

let api: APIRequestContext;
let token = "";
const createdMatterIds = new Set<string>();

function password(): string {
  const value = envOr(
    "CASEOPS_RAM_PROD_PASSWORD",
    envOr("CASEOPS_RAM_LOCAL_PASSWORD", IS_LOCAL ? LOCAL_PASSWORD : ""),
  );
  if (!value)
    throw new Error(
      "CASEOPS_RAM_PROD_PASSWORD is required for production verification.",
    );
  return value;
}

async function expectStatus(
  response: APIResponse,
  expected: number,
  label: string,
): Promise<void> {
  if (response.status() !== expected) {
    throw new Error(
      `${label}: expected ${expected}, got ${response.status()} — ${(await response.text()).slice(0, 500)}`,
    );
  }
}

function code(suffix: string): string {
  return `RAM903-${suffix}-${RUN_ID}`.replace(/[^A-Z0-9-]/g, "").slice(0, 78);
}

async function signIn(page: Page): Promise<string> {
  await page.goto(`${BASE_URL}/sign-in`);
  await page.locator("#company-slug").fill(COMPANY_SLUG);
  await page.locator("#email").fill(TESTER_EMAIL);
  await page.locator("#password").fill(password());
  const [login] = await Promise.all([
    page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === "/api/auth/login" &&
        response.request().method() === "POST",
    ),
    page.locator('button[type="submit"]').click(),
  ]);
  await expectStatus(login, 200, "tester sign-in");
  await page.waitForURL(/\/app(?:[/?]|$)/);
  return ((await login.json()) as { access_token: string }).access_token;
}

test.describe.serial("Ram 2026-09-03 Bulk Matter Exact Court mapping", () => {
  test.setTimeout(240_000);

  test.beforeAll(async () => {
    api = await request.newContext({
      extraHTTPHeaders: { "X-CaseOps-Automated-Test": "no-paid-providers" },
    });
    if (!IS_LOCAL) return;
    const bootstrap = await api.post(`${API_BASE_URL}/api/bootstrap/company`, {
      data: {
        company_name: `Ram Sep03 ${RUN_ID}`,
        company_slug: COMPANY_SLUG,
        company_type: "law_firm",
        owner_full_name: "Ram September Tester",
        owner_email: TESTER_EMAIL,
        owner_password: LOCAL_PASSWORD,
      },
    });
    await expectStatus(bootstrap, 200, "bootstrap local tenant");
    seedVerifiedLocalStatute(IS_LOCAL);
  });

  test.afterAll(async () => {
    if (token) {
      for (const matterId of createdMatterIds) {
        const current = await api.get(
          `${API_BASE_URL}/api/matters/${matterId}`,
          {
            headers: { Authorization: `Bearer ${token}` },
          },
        );
        if (current.status() !== 200) continue;
        const matter = (await current.json()) as MatterRecord;
        if (matter.status === "disposed") continue;
        await api.patch(
          `${API_BASE_URL}/api/matters/${matter.id}/lifecycle/status`,
          {
            headers: { Authorization: `Bearer ${token}` },
            data: {
              to_status: "disposed",
              expected_from_status: matter.status,
              expected_updated_at: matter.updated_at,
              reason: "Close the September 03 exact-court regression fixture.",
            },
          },
        );
      }
    }
    await api?.dispose();
  });

  test("exact production release identifies the deployed revision", async ({
    page,
  }) => {
    test.skip(IS_LOCAL, "Production-only exact release gate.");
    const expectedSha = envOr("CASEOPS_EXPECTED_RELEASE_SHA", "").toLowerCase();
    expect(expectedSha).toMatch(/^[0-9a-f]{40}$/);
    const [apiBuild, webBuild] = await Promise.all([
      page.request.get(`${API_BASE_URL}/api/build`),
      page.request.get(`${BASE_URL}/api/release-identity`),
    ]);
    await expectStatus(apiBuild, 200, "API release identity");
    await expectStatus(webBuild, 200, "web release identity");
    expect((await apiBuild.json()).release_sha).toBe(expectedSha);
    expect((await webBuild.json()).release_sha).toBe(expectedSha);
  });

  test("BUG-004/005/006: providers are truthful and every statute entry is visible but only verified law is attachable", async ({
    page,
  }) => {
    token = await signIn(page);
    const headers = { Authorization: `Bearer ${token}` };

    const readinessResponse = await page.request.get(
      `${API_BASE_URL}/api/admin/provider-operations/readiness`,
      { headers },
    );
    await expectStatus(readinessResponse, 200, "provider readiness");
    const readiness = new Map(
      (
        (await readinessResponse.json()) as {
          providers: Array<{
            provider: string;
            state: string;
            configured: boolean;
            enabled: boolean;
            external_calls_enabled: boolean;
            required_approval_keys: string[];
            missing_approval_keys: string[];
          }>;
        }
      ).providers.map((row) => [row.provider, row]),
    );
    for (const provider of ["ecourtsindia", "indian-kanoon"]) {
      const row = readiness.get(provider);
      expect(row, `${provider} readiness row`).toBeTruthy();
      expect(row?.required_approval_keys).toEqual([]);
      expect(row?.missing_approval_keys).toEqual([]);
      if (!IS_LOCAL) {
        expect(row).toEqual(
          expect.objectContaining({
            state: "ready",
            configured: true,
            enabled: true,
            external_calls_enabled: true,
          }),
        );
      }
    }

    const supportResponse = await page.request.get(
      `${API_BASE_URL}/api/case-tracking/support-matrix`,
      { headers },
    );
    await expectStatus(supportResponse, 200, "case-tracking support matrix");
    const supportRows = (
      (await supportResponse.json()) as {
        rows: Array<{
          provider: string;
          court: string;
          enabled: boolean;
          bench_jurisdiction: string | null;
        }>;
      }
    ).rows;
    expect(supportRows).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          provider: "ecourtsindia",
          court: "*",
          enabled: true,
        }),
      ]),
    );

    const catalogResponse = await page.request.get(
      `${API_BASE_URL}/api/statutes/`,
      { headers },
    );
    await expectStatus(catalogResponse, 200, "statute catalog");
    const catalog = (await catalogResponse.json()) as {
      statutes: Array<{
        id: string;
        section_count: number;
        catalog_section_count: number;
      }>;
      total_section_count: number;
      total_catalog_section_count: number;
    };
    expect(catalog.statutes.length).toBeGreaterThan(1);
    expect(catalog.total_catalog_section_count).toBeGreaterThan(
      catalog.total_section_count,
    );

    const sectionsResponse = await page.request.get(
      `${API_BASE_URL}/api/statutes/constitution-india/sections`,
      { headers },
    );
    await expectStatus(sectionsResponse, 200, "Constitution section catalog");
    const sectionCatalog = (await sectionsResponse.json()) as {
      sections: Array<{
        id: string;
        section_number: string;
        verification_status: string;
      }>;
      catalog_sections: Array<{
        id: string;
        section_number: string;
        selection_state: string;
      }>;
      verified_section_count: number;
      catalog_section_count: number;
    };
    const verified = sectionCatalog.sections.find(
      (row) => row.section_number === "Article 14",
    );
    const pending = sectionCatalog.catalog_sections.find(
      (row) => row.selection_state === "verification_pending",
    );
    expect(verified?.verification_status).toBe("verified_official");
    expect(pending).toBeTruthy();

    const matterResponse = await page.request.post(
      `${API_BASE_URL}/api/matters/`,
      {
        headers,
        data: {
          title: `September 03 statute coverage ${RUN_ID}`,
          matter_code: code("STATUTE"),
          status: "active",
          practice_area: "Commercial Litigation",
          forum_level: "high_court",
          forum_catalog_entry_id: "hc:delhi",
        },
      },
    );
    await expectStatus(matterResponse, 200, "create statute regression matter");
    const matter = (await matterResponse.json()) as MatterRecord;
    createdMatterIds.add(matter.id);

    const bypass = await page.request.post(
      `${API_BASE_URL}/api/matters/${matter.id}/statute-references`,
      {
        headers,
        data: { section_id: pending!.id, relevance: "cited" },
      },
    );
    await expectStatus(bypass, 409, "reject unverified direct API attachment");
    expect((await bypass.json()).type).toBe("statute_section_not_verified");

    await page.goto(`${BASE_URL}/app/matters/${matter.id}/statutes`);
    await page.getByTestId("matter-statute-add-trigger").click();
    const actSelect = page.getByTestId("matter-statute-act-select");
    await expect(actSelect.locator("option")).toHaveCount(
      catalog.statutes.length + 1,
    );
    for (const unavailable of catalog.statutes.filter(
      (row) => row.section_count === 0,
    )) {
      await expect(
        actSelect.locator(`option[value="${unavailable.id}"]`),
      ).toHaveAttribute("disabled", "");
    }
    const sectionRequest = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname ===
          "/api/statutes/constitution-india/sections" &&
        response.request().method() === "GET",
    );
    await actSelect.selectOption("constitution-india");
    await expectStatus(await sectionRequest, 200, "load section picker");
    const sectionSelect = page.getByTestId("matter-statute-section-select");
    await expect(sectionSelect.locator("option")).toHaveCount(
      sectionCatalog.catalog_section_count + 1,
    );
    await expect(
      sectionSelect.locator(`option[value="${pending!.id}"]`),
    ).toHaveAttribute("disabled", "");
    await expect(
      sectionSelect.locator(`option[value="${verified!.id}"]`),
    ).not.toHaveAttribute("disabled", "");
    await sectionSelect.selectOption(verified!.id);
    const attach = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname ===
          `/api/matters/${matter.id}/statute-references` &&
        response.request().method() === "POST",
    );
    await page.getByTestId("matter-statute-add-submit").click();
    await expectStatus(await attach, 201, "attach verified statute section");

    await page.goto(`${BASE_URL}/app/research`);
    await page.getByTestId("research-source-indian-kanoon").click();
    const indianKanoonReadiness = page.getByTestId(
      "research-indian-kanoon-readiness",
    );
    if (IS_LOCAL) {
      await expect(indianKanoonReadiness).toContainText(
        "No provider call will be made",
      );
    } else {
      await expect(indianKanoonReadiness).toContainText(
        "Licensed access is active",
      );
    }
    await page.goto(`${BASE_URL}/app/case-tracking`);
    await expect(
      page.getByTestId("case-tracking-support-matrix"),
    ).toContainText("supported");
  });

  test("XLSX exact courts and configured alias map lineage; unknown row is not guessed", async ({
    page,
  }) => {
    token = await signIn(page);
    await page.goto(`${BASE_URL}/app/matters/imports`);
    await expect(
      page.getByTestId("matter-import-compatibility-guidance"),
    ).toContainText("unique Exact Court/approved alias");

    const clientName = `Ram Sep03 client ${RUN_ID}`.slice(0, 120);
    const rows = [
      [
        "Tis Hazari exact",
        code("TH"),
        "Commercial",
        "active",
        clientName,
        "Tis Hazari",
        "",
      ],
      [
        "ITO normalized",
        code("ITO"),
        "Commercial",
        "active",
        clientName,
        "  iTo  ",
        "",
      ],
      [
        "Dwarka alias",
        code("DW"),
        "Commercial",
        "active",
        clientName,
        "dwarka-swcf",
        "",
      ],
      [
        "Unknown exact court",
        code("BAD"),
        "Commercial",
        "active",
        clientName,
        "Imaginary Court",
        "",
      ],
    ];
    const [preview] = await Promise.all([
      page.waitForResponse(
        (response) =>
          new URL(response.url()).pathname === "/api/matters/imports/preview" &&
          response.request().method() === "POST",
        { timeout: 90_000 },
      ),
      page
        .getByTestId("matter-import-file")
        .setInputFiles({
          name: "ram-sep03-exact-courts.xlsx",
          mimeType:
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
          buffer: buildMinimalXlsx(
            [
              "Matter Title",
              "Matter Code",
              "Practice Area",
              "Matter Status",
              "Client Name",
              "Forum",
              "Court",
            ],
            rows,
          ),
        })
        .then(() => page.getByTestId("matter-import-validate").click()),
    ]);
    await expectStatus(preview, 200, "preview exact-court workbook");
    const previewBody = (await preview.json()) as {
      rows: Array<{
        row_number: number;
        status: string;
        errors: string[];
        normalized: Record<string, unknown>;
      }>;
    };
    expect(previewBody.rows.slice(0, 3).map((row) => row.status)).toEqual([
      "valid",
      "valid",
      "valid",
    ]);
    expect(previewBody.rows[3].status).toBe("invalid");
    expect(previewBody.rows[3].errors.join(" ")).toContain("Row 5");
    expect(previewBody.rows[3].errors.join(" ")).toContain("Imaginary Court");
    await expect(page.getByTestId("matter-import-confirm")).toContainText(
      "Confirm import (3)",
    );
    await expect(
      page.getByText(
        /CaseOps will not guess|did not match an active configured Exact Court/,
      ),
    ).toBeVisible();

    const [commit] = await Promise.all([
      page.waitForResponse((response) =>
        /\/api\/matters\/imports\/[^/]+\/commit$/.test(
          new URL(response.url()).pathname,
        ),
      ),
      page.getByTestId("matter-import-confirm").click(),
    ]);
    await expectStatus(commit, 200, "commit exact-court workbook");
    const committed = (await commit.json()) as { created_matter_ids: string[] };
    expect(committed.created_matter_ids).toHaveLength(3);
    committed.created_matter_ids.forEach((id) => createdMatterIds.add(id));

    const expected = new Map([
      [code("TH"), ["consumer:dcdrc:delhi:tis-hazari", "Tis Hazari"]],
      [code("ITO"), ["consumer:dcdrc:delhi:ito", "ITO"]],
      [code("DW"), ["consumer:dcdrc:delhi:dwarka", "Dwarka"]],
    ]);
    for (const matterId of committed.created_matter_ids) {
      const response = await page.request.get(
        `${API_BASE_URL}/api/matters/${matterId}`,
        {
          headers: { Authorization: `Bearer ${token}` },
        },
      );
      await expectStatus(response, 200, `read imported matter ${matterId}`);
      const matter = (await response.json()) as MatterRecord;
      const mapping = expected.get(matter.matter_code);
      expect(mapping).toBeTruthy();
      expect(matter.forum_catalog_entry_id).toBe(mapping?.[0]);
      expect(matter.court_name).toBe(mapping?.[1]);
      expect(matter.forum_level).toBe("tribunal");
      expect(matter.forum_state).toBe("Delhi");
      expect(matter.forum_consumer_level).toBe("district");
    }
  });
});
