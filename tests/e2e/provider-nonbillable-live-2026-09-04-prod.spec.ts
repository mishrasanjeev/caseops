/**
 * Non-billable production provider verification. This spec may inspect only
 * CaseOps readiness and budget-balance endpoints. Its negative calls prove
 * billable provider operations stop before external transport.
 */
import { expect, test, type APIResponse, type Page } from "@playwright/test";

const envOr = (key: string, fallback: string): string =>
  (process.env[key] ?? "").trim() || fallback;

const BASE_URL = envOr("PROD_BASE_URL", "https://caseops.ai");
const API_BASE_URL = envOr("PROD_API_BASE_URL", "https://api.caseops.ai");
const COMPANY_SLUG = envOr("CASEOPS_RAM_PROD_SLUG", "legal");
const TESTER_EMAIL = envOr("CASEOPS_RAM_PROD_EMAIL", "hari.gupta@gmail.com");

function required(key: string): string {
  const value = process.env[key]?.trim();
  if (!value) throw new Error(`${key} is required.`);
  return value;
}

function password(): string {
  const value = process.env.CASEOPS_RAM_PROD_PASSWORD?.trim();
  if (!value) throw new Error("CASEOPS_RAM_PROD_PASSWORD is required.");
  return value;
}

async function expectStatus(
  response: Pick<APIResponse, "status" | "text">,
  expected: number,
  label: string,
): Promise<void> {
  const detail =
    response.status() === expected ? "" : ` ${await response.text()}`;
  expect(response.status(), `${label}.${detail}`).toBe(expected);
}

async function signIn(page: Page): Promise<string> {
  const login = await page.request.post(`${API_BASE_URL}/api/auth/login`, {
    data: {
      company_slug: COMPANY_SLUG,
      email: TESTER_EMAIL,
      password: password(),
    },
  });
  await expectStatus(login, 200, "production tester sign-in");
  const session = await login.json();
  await page.goto(`${BASE_URL}/`);
  await page.evaluate(
    (context) => {
      window.localStorage.setItem(
        "caseops.session.context",
        JSON.stringify(context),
      );
    },
    {
      company: session.company,
      user: session.user,
      membership: session.membership,
      capabilities: session.capabilities,
    },
  );
  return session.access_token;
}

type ProviderSpendRow = {
  provider_key: string;
  spent_minor: number;
  monthly_limit_minor: number | null;
  remaining_minor: number | null;
  unlimited: boolean;
  currency: string;
};

async function providerSpend(page: Page, token: string): Promise<Map<string, ProviderSpendRow>> {
  const response = await page.request.get(`${API_BASE_URL}/api/billing/usage`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  await expectStatus(response, 200, "workspace provider-spend report");
  const payload = (await response.json()) as { by_provider: ProviderSpendRow[] };
  return new Map(payload.by_provider.map((row) => [row.provider_key, row]));
}

test("automation checks readiness and budget balance without provider spend", async ({
  page,
}) => {
  const expectedSha = required("CASEOPS_EXPECTED_RELEASE_SHA").toLowerCase();
  expect(expectedSha).toMatch(/^[0-9a-f]{40}$/);
  const [apiIdentity, webIdentity] = await Promise.all([
    page.request.get(`${API_BASE_URL}/api/build`),
    page.request.get(`${BASE_URL}/api/release-identity`),
  ]);
  await expectStatus(apiIdentity, 200, "API release identity");
  await expectStatus(webIdentity, 200, "web release identity");
  expect((await apiIdentity.json()).release_sha).toBe(expectedSha);
  expect((await webIdentity.json()).release_sha).toBe(expectedSha);

  const token = await signIn(page);
  const headers = { Authorization: `Bearer ${token}` };
  const beforeSpend = await providerSpend(page, token);
  expect([...beforeSpend.keys()].sort()).toEqual([
    "ecourtsindia",
    "indian-kanoon",
  ]);
  for (const row of beforeSpend.values()) {
    expect(row.currency).toBe("INR");
    expect(row.spent_minor).toBeGreaterThanOrEqual(0);
    expect(row.monthly_limit_minor).toBe(100_000);
    expect(row.unlimited).toBe(false);
    expect(row.remaining_minor).toBeGreaterThanOrEqual(0);
  }

  const providerReadiness = await page.request.get(
    `${API_BASE_URL}/api/admin/provider-operations/readiness`,
    { headers },
  );
  await expectStatus(providerReadiness, 200, "provider readiness endpoint");
  const providers = new Map(
    (
      (await providerReadiness.json()).providers as Array<{
        provider: string;
        state: string;
        external_calls_enabled: boolean;
      }>
    ).map((record) => [record.provider, record]),
  );
  for (const providerName of ["ecourtsindia", "indian-kanoon"]) {
    expect(providers.get(providerName)).toEqual(
      expect.objectContaining({
        state: "ready",
        external_calls_enabled: true,
      }),
    );
  }

  const caseTrackingStatus = await page.request.get(
    `${API_BASE_URL}/api/case-tracking/status`,
    { headers },
  );
  await expectStatus(caseTrackingStatus, 200, "eCourts endpoint configuration");
  expect(await caseTrackingStatus.json()).toEqual(
    expect.objectContaining({
      enabled: true,
      provider: "ecourtsindia",
      configured: true,
      performs_external_probe: false,
      provider_prepaid_balance_checked: false,
      workspace_monthly_spend_minor:
        beforeSpend.get("ecourtsindia")!.spent_minor,
      workspace_monthly_limit_minor: 100_000,
      workspace_monthly_limit_unlimited: false,
      workspace_monthly_limit_currency: "INR",
    }),
  );

  const health = await page.request.get(
    `${API_BASE_URL}/api/authorities/providers/indian-kanoon/health`,
    { headers },
  );
  await expectStatus(health, 200, "Indian Kanoon budget balance");
  const healthBody = await health.json();
  expect(healthBody).toEqual(
    expect.objectContaining({
      health: "ready",
      performs_external_probe: false,
      provider_prepaid_balance_checked: false,
      balance_source: "caseops_recorded_workspace_usage",
      currency: "INR",
      monthly_spend_minor: beforeSpend.get("indian-kanoon")!.spent_minor,
      monthly_limit_minor: 100_000,
      monthly_limit_unlimited: false,
    }),
  );
  expect(healthBody.daily_spend_minor).toBeGreaterThanOrEqual(0);
  expect(healthBody.daily_remaining_minor).toBeGreaterThanOrEqual(0);
  expect(healthBody.monthly_spend_minor).toBeGreaterThanOrEqual(0);
  expect(healthBody.monthly_remaining_minor).toBeGreaterThanOrEqual(0);

  const blockedIndianKanoon = await page.request.post(
    `${API_BASE_URL}/api/authorities/providers/indian-kanoon/search`,
    {
      headers,
      data: { query: "automation must stop before provider transport" },
    },
  );
  await expectStatus(
    blockedIndianKanoon,
    409,
    "Indian Kanoon no-spend boundary",
  );
  expect(await blockedIndianKanoon.json()).toEqual(
    expect.objectContaining({
      code: "paid_provider_blocked_for_test",
      reason: "automated_test_request",
    }),
  );

  const blockedEcourts = await page.request.post(
    `${API_BASE_URL}/api/case-tracking/search`,
    { headers, data: { cnr_number: "DLND020047882015" } },
  );
  await expectStatus(blockedEcourts, 409, "eCourts no-spend boundary");
  expect(await blockedEcourts.json()).toEqual(
    expect.objectContaining({
      code: "paid_provider_blocked_for_test",
      reason: "automated_test_request",
    }),
  );

  const afterSpend = await providerSpend(page, token);
  for (const providerName of ["ecourtsindia", "indian-kanoon"]) {
    expect(afterSpend.get(providerName)?.spent_minor).toBe(
      beforeSpend.get(providerName)?.spent_minor,
    );
  }

  await page.goto(`${BASE_URL}/app/admin/billing/usage`);
  const spendTable = page.getByTestId("provider-spend-by-account");
  await expect(spendTable).toContainText("eCourtsIndia");
  await expect(spendTable).toContainText("Indian Kanoon");
  await expect(spendTable).toContainText("1,000");

  await page.goto(`${BASE_URL}/app/research`);
  await page.getByTestId("research-source-indian-kanoon").click();
  await expect(
    page.getByTestId("research-indian-kanoon-readiness"),
  ).toContainText("Licensed access is active");
});
