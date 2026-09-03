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
