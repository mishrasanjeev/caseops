import { expect, request, test, type APIRequestContext, type APIResponse, type Page } from "@playwright/test";

import { apiBaseUrl } from "./support/env";

const WEB_BASE_URL = process.env.CASEOPS_WEB_BASE_URL?.trim() || "http://127.0.0.1:3000";
const COMPANY_SLUG = "platform-admin-e2e";
const OWNER_EMAIL = "platform-admin@caseops-e2e.test";
const OWNER_PASSWORD = "PlatformAdminE2E!";
const RUN_ID = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;

type ForumEntry = {
  id: string;
  name: string;
  state: string | null;
  district: string | null;
  lineage: string;
};

type AliasRecord = {
  id: string;
  record_version: number;
  is_active: boolean;
};

let api: APIRequestContext;
let token = "";
let createdAlias: AliasRecord | null = null;

async function expectStatus(response: APIResponse, expected: number, label: string) {
  if (response.status() !== expected) {
    throw new Error(
      `${label}: expected ${expected}, received ${response.status()} ${(await response.text()).slice(0, 500)}`,
    );
  }
}

async function bootstrapOrLogin(): Promise<string> {
  const bootstrap = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "CaseOps E2E Platform Administration",
      company_slug: COMPANY_SLUG,
      company_type: "law_firm",
      owner_full_name: "Platform Catalog Tester",
      owner_email: OWNER_EMAIL,
      owner_password: OWNER_PASSWORD,
    },
  });
  if (bootstrap.status() === 200) {
    return ((await bootstrap.json()) as { access_token: string }).access_token;
  }
  await expectStatus(bootstrap, 409, "existing platform test workspace");
  const login = await api.post(`${apiBaseUrl}/api/auth/login`, {
    data: {
      company_slug: COMPANY_SLUG,
      email: OWNER_EMAIL,
      password: OWNER_PASSWORD,
    },
  });
  await expectStatus(login, 200, "platform tester login");
  return ((await login.json()) as { access_token: string }).access_token;
}

async function signIn(page: Page): Promise<void> {
  await page.goto(`${WEB_BASE_URL}/sign-in`);
  await page.locator("#company-slug").fill(COMPANY_SLUG);
  await page.locator("#email").fill(OWNER_EMAIL);
  await page.locator("#password").fill(OWNER_PASSWORD);
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  await page.waitForURL(/\/app(?:[/?]|$)/);
}

test.describe.serial("2026-09-04 governed forum alias registry", () => {
  test.setTimeout(180_000);

  test.beforeAll(async () => {
    api = await request.newContext({
      extraHTTPHeaders: { "X-CaseOps-Automated-Test": "no-paid-providers" },
    });
    token = await bootstrapOrLogin();
  });

  test.afterAll(async () => {
    if (createdAlias?.is_active) {
      await api.patch(`${apiBaseUrl}/api/platform-admin/forum-aliases/${createdAlias.id}`, {
        headers: { Authorization: `Bearer ${token}` },
        data: {
          is_active: false,
          expected_record_version: createdAlias.record_version,
          reason: "Clean up the dated Playwright forum alias fixture.",
        },
      });
    }
    await api.dispose();
  });

  test("creates, resolves, audits, and deactivates a source-backed alias", async ({ page }) => {
    const headers = { Authorization: `Bearer ${token}` };
    const catalogResponse = await api.get(`${apiBaseUrl}/api/courts/forum-catalog`, {
      headers,
    });
    await expectStatus(catalogResponse, 200, "forum catalog");
    const catalog = (await catalogResponse.json()) as { entries: ForumEntry[] };
    const entry = catalog.entries.find((row) => row.state && row.state !== "Delhi");
    expect(entry, "an active non-Delhi catalog entry must exist").toBeTruthy();
    const alias = `E2E registry label ${RUN_ID}`;

    await signIn(page);
    await page.goto(`${WEB_BASE_URL}/app/platform-admin/forum-aliases`);
    await expect(page.getByRole("heading", { name: "Forum aliases" })).toBeVisible();
    await page.getByLabel("Find canonical forum").fill(entry!.name);
    await page.getByLabel("Canonical forum").selectOption(entry!.id);
    await page.getByLabel("Alias", { exact: true }).fill(alias);
    await page.getByLabel("Alias type").selectOption("provider_label");
    await page.getByLabel("Verification", { exact: true }).selectOption("verified");
    await page.getByLabel("Source name").fill("Official eCourts services directory");
    await page.getByLabel("Source URL").fill("https://services.ecourts.gov.in/");
    await page
      .getByLabel("Change reason")
      .fill("Add a reviewed all-India alias through the governed registry.");
    const createResponse = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === "/api/platform-admin/forum-aliases" &&
        response.request().method() === "POST",
    );
    await page.getByRole("button", { name: "Add alias" }).click();
    const createdResponse = await createResponse;
    await expectStatus(createdResponse, 200, "create forum alias through UI");
    createdAlias = (await createdResponse.json()) as AliasRecord;
    const row = page.getByTestId(`forum-alias-row-${createdAlias.id}`);
    await expect(row).toContainText(alias);
    await expect(row).toContainText(entry!.name);
    await expect(row.getByRole("link", { name: "Open source" })).toHaveAttribute(
      "href",
      "https://services.ecourts.gov.in/",
    );

    const resolved = await api.get(`${apiBaseUrl}/api/courts/forum-catalog/resolve`, {
      headers,
      params: { query: alias, state: entry!.state! },
    });
    await expectStatus(resolved, 200, "resolve newly curated alias");
    expect((await resolved.json()).resolved_entry.id).toBe(entry!.id);

    await row.getByRole("button", { name: "Edit" }).click();
    await page.getByLabel("Active registry row").uncheck();
    await page
      .getByLabel("Change reason")
      .fill("Deactivate the dated alias after proving immediate resolver convergence.");
    const updateResponse = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname ===
          `/api/platform-admin/forum-aliases/${createdAlias!.id}` &&
        response.request().method() === "PATCH",
    );
    await page.getByRole("button", { name: "Save alias" }).click();
    const updatedResponse = await updateResponse;
    await expectStatus(updatedResponse, 200, "deactivate forum alias through UI");
    createdAlias = (await updatedResponse.json()) as AliasRecord;
    expect(createdAlias.is_active).toBe(false);

    const unresolved = await api.get(`${apiBaseUrl}/api/courts/forum-catalog/resolve`, {
      headers,
      params: { query: alias, state: entry!.state! },
    });
    await expectStatus(unresolved, 200, "deactivated alias resolution");
    expect((await unresolved.json()).status).toBe("not_found");
  });
});
