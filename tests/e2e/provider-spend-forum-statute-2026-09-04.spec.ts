/**
 * Ram 2026-09-04 provider-budget, Bare Act, and court-alias acceptance.
 * Every request inherits the no-paid-provider marker from the Playwright
 * config. The journey inspects CaseOps state only and never spends credits.
 */
import {
  expect,
  request,
  test,
  type APIRequestContext,
  type APIResponse,
  type Page,
} from "@playwright/test";

import { apiBaseUrl } from "./support/env";
import { seedVerifiedLocalStatute } from "./support/verified-statute-fixture";

const WEB_BASE_URL =
  process.env.CASEOPS_WEB_BASE_URL?.trim() || "http://127.0.0.1:3100";
const RUN_ID = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
const COMPANY_SLUG = `ram-sep04-${RUN_ID}`.toLowerCase();
const OWNER_EMAIL = `ram-sep04-${RUN_ID}@caseops.ai`.toLowerCase();
const OWNER_PASSWORD = "RamSep04Local!";

type ProviderSpendRow = {
  provider_key: string;
  spent_minor: number;
  monthly_limit_minor: number | null;
  remaining_minor: number | null;
  unlimited: boolean;
  currency: string;
};

type MatterRecord = {
  id: string;
  status: "intake" | "active" | "on_hold" | "disposed";
  updated_at: string;
  court_name: string | null;
  forum_catalog_entry_id: string | null;
  forum_state: string | null;
  forum_district: string | null;
};

let api: APIRequestContext;
let token = "";
const createdMatterIds = new Set<string>();

async function expectStatus(
  response: APIResponse,
  expected: number,
  label: string,
): Promise<void> {
  if (response.status() !== expected) {
    throw new Error(
      `${label}: expected ${expected}, got ${response.status()} ${(await response.text()).slice(0, 500)}`,
    );
  }
}

async function signIn(page: Page): Promise<void> {
  await page.goto(`${WEB_BASE_URL}/sign-in`);
  await page.locator("#company-slug").fill(COMPANY_SLUG);
  await page.locator("#email").fill(OWNER_EMAIL);
  await page.locator("#password").fill(OWNER_PASSWORD);
  const response = page.waitForResponse(
    (candidate) =>
      new URL(candidate.url()).pathname === "/api/auth/login" &&
      candidate.request().method() === "POST",
  );
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  await expectStatus(await response, 200, "local tester sign-in");
  await page.waitForURL(/\/app(?:[/?]|$)/);
}

async function usageRows(): Promise<Map<string, ProviderSpendRow>> {
  const response = await api.get(`${apiBaseUrl}/api/billing/usage`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  await expectStatus(response, 200, "workspace usage report");
  const body = (await response.json()) as { by_provider: ProviderSpendRow[] };
  return new Map(body.by_provider.map((row) => [row.provider_key, row]));
}

test.describe.serial("Ram 2026-09-04 provider, statute, and forum acceptance", () => {
  test.setTimeout(180_000);

  test.beforeAll(async () => {
    api = await request.newContext({
      extraHTTPHeaders: { "X-CaseOps-Automated-Test": "no-paid-providers" },
    });
    const bootstrap = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
      data: {
        company_name: `Ram Sep04 ${RUN_ID}`,
        company_slug: COMPANY_SLUG,
        company_type: "law_firm",
        owner_full_name: "Ram September Tester",
        owner_email: OWNER_EMAIL,
        owner_password: OWNER_PASSWORD,
      },
    });
    await expectStatus(bootstrap, 200, "bootstrap local provider-policy tenant");
    token = ((await bootstrap.json()) as { access_token: string }).access_token;
    seedVerifiedLocalStatute(true);
  });

  test.afterAll(async () => {
    for (const matterId of createdMatterIds) {
      const current = await api.get(`${apiBaseUrl}/api/matters/${matterId}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (current.status() !== 200) continue;
      const matter = (await current.json()) as MatterRecord;
      if (matter.status === "disposed") continue;
      await api.patch(`${apiBaseUrl}/api/matters/${matter.id}/lifecycle/status`, {
        headers: { Authorization: `Bearer ${token}` },
        data: {
          to_status: "disposed",
          expected_from_status: matter.status,
          expected_updated_at: matter.updated_at,
          reason: "Close the September 04 acceptance fixture.",
        },
      });
    }
    await api.dispose();
  });

  test("provider endpoints publish INR 1,000 limits and spend without external probes", async ({
    page,
  }) => {
    const before = await usageRows();
    for (const provider of ["ecourtsindia", "indian-kanoon"]) {
      expect(before.get(provider)).toEqual({
        provider_key: provider,
        spent_minor: 0,
        monthly_limit_minor: 100_000,
        remaining_minor: 100_000,
        unlimited: false,
        currency: "INR",
        label: provider === "ecourtsindia" ? "eCourtsIndia" : "Indian Kanoon",
        policy_source: "caseops_default_provider_budget_2026_09_04",
      });
    }

    const eCourts = await api.get(`${apiBaseUrl}/api/case-tracking/status`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    await expectStatus(eCourts, 200, "eCourts read-only status");
    expect(await eCourts.json()).toEqual(
      expect.objectContaining({
        performs_external_probe: false,
        provider_prepaid_balance_checked: false,
        workspace_monthly_spend_minor: 0,
        workspace_monthly_limit_minor: 100_000,
        workspace_monthly_remaining_minor: 100_000,
        workspace_monthly_limit_unlimited: false,
        workspace_monthly_limit_currency: "INR",
      }),
    );

    const indianKanoon = await api.get(
      `${apiBaseUrl}/api/authorities/providers/indian-kanoon/health`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
    await expectStatus(indianKanoon, 200, "Indian Kanoon read-only balance");
    expect(await indianKanoon.json()).toEqual(
      expect.objectContaining({
        performs_external_probe: false,
        provider_prepaid_balance_checked: false,
        balance_source: "caseops_recorded_workspace_usage",
        monthly_spend_minor: 0,
        monthly_limit_minor: 100_000,
        monthly_remaining_minor: 100_000,
        monthly_limit_unlimited: false,
      }),
    );

    await signIn(page);
    await page.goto(`${WEB_BASE_URL}/app/admin/billing/usage`);
    const table = page.getByTestId("provider-spend-by-account");
    await expect(table).toContainText("eCourtsIndia");
    await expect(table).toContainText("Indian Kanoon");
    await expect(table).toContainText("1,000");
    expect(await usageRows()).toEqual(before);
  });

  test("all catalogued Bare Act sections open a truthful detail and source surface", async ({
    page,
  }) => {
    const catalogResponse = await api.get(`${apiBaseUrl}/api/statutes/`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    await expectStatus(catalogResponse, 200, "statute catalog");
    const catalog = (await catalogResponse.json()) as {
      statutes: Array<{
        id: string;
        catalog_section_count: number;
        section_count: number;
        source_url: string | null;
      }>;
    };
    const statute = catalog.statutes.find(
      (row) =>
        row.source_url && row.catalog_section_count > row.section_count,
    );
    expect(statute, "a pending section with an Act source must exist").toBeTruthy();
    const sectionsResponse = await api.get(
      `${apiBaseUrl}/api/statutes/${encodeURIComponent(statute!.id)}/sections`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
    await expectStatus(sectionsResponse, 200, "catalogued statute sections");
    const sections = (await sectionsResponse.json()) as {
      catalog_sections: Array<{
        id: string;
        section_number: string;
        selection_state: string;
      }>;
    };
    const pending = sections.catalog_sections.find(
      (row) => row.selection_state === "verification_pending",
    );
    expect(pending).toBeTruthy();

    await signIn(page);
    await page.goto(`${WEB_BASE_URL}/app/statutes/${encodeURIComponent(statute!.id)}`);
    const row = page.getByTestId(`statute-section-${pending!.id}`);
    await expect(row).toContainText("Verification pending");
    await row.getByRole("link").click();
    await expect(
      page.getByRole("heading", { name: pending!.section_number }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Verified statutory text unavailable" }),
    ).toBeVisible();
    await expect(page.getByTestId("statute-act-landing-page")).toBeVisible();
    await expect(page.getByTestId("statute-source-metadata")).toContainText(
      "Link health",
    );
  });

  test("court-complex aliases resolve with context and never guess ambiguity", async ({
    page,
  }) => {
    const headers = { Authorization: `Bearer ${token}` };
    const ambiguous = await api.get(`${apiBaseUrl}/api/courts/forum-catalog/resolve`, {
      headers,
      params: { query: "Tis Hazari Court" },
    });
    await expectStatus(ambiguous, 200, "ambiguous court-complex alias");
    const ambiguousBody = await ambiguous.json();
    expect(ambiguousBody.status).toBe("ambiguous");
    expect(ambiguousBody.candidates).toHaveLength(2);

    const resolved = await api.get(`${apiBaseUrl}/api/courts/forum-catalog/resolve`, {
      headers,
      params: { query: "Saket Court", district: "South Delhi" },
    });
    await expectStatus(resolved, 200, "contextual court-complex alias");
    expect((await resolved.json()).resolved_entry.id).toBe(
      "district:india-gov:delhi:southdelhi",
    );

    const create = await api.post(`${apiBaseUrl}/api/matters/`, {
      headers,
      data: {
        title: `September 04 alias matter ${RUN_ID}`,
        matter_code: `RAM904-ALIAS-${RUN_ID}`.toUpperCase().slice(0, 78),
        practice_area: "Commercial Litigation",
        status: "intake",
        forum_level: "lower_court",
        court_name: "saket-court",
        forum_district: "South Delhi",
      },
    });
    await expectStatus(create, 200, "manual alias-backed matter create");
    const matter = (await create.json()) as MatterRecord;
    createdMatterIds.add(matter.id);
    expect(matter).toEqual(
      expect.objectContaining({
        court_name: "South District Court, New Delhi",
        forum_catalog_entry_id: "district:india-gov:delhi:southdelhi",
        forum_state: "Delhi",
        forum_district: "South Delhi",
      }),
    );

    await signIn(page);
    await page.goto(`${WEB_BASE_URL}/app/matters/${matter.id}`);
    await expect(page.getByText("South District Court, New Delhi").first()).toBeVisible();
  });
});
