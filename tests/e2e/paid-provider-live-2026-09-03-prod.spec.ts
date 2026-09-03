/**
 * One deliberately small paid-path verification for eCourtsIndia and Indian
 * Kanoon. Never include this file in routine, bulk, Docker, or CI suites.
 */
import { expect, test, type APIResponse, type Page } from "@playwright/test";

const envOr = (key: string, fallback: string): string =>
  (process.env[key] ?? "").trim() || fallback;

const BASE_URL = envOr("PROD_BASE_URL", "https://caseops.ai");
const API_BASE_URL = envOr("PROD_API_BASE_URL", "https://api.caseops.ai");
const COMPANY_SLUG = envOr("CASEOPS_RAM_PROD_SLUG", "legal");
const TESTER_EMAIL = envOr("CASEOPS_RAM_PROD_EMAIL", "hari.gupta@gmail.com");
const LIVE_CNR = envOr("CASEOPS_LIVE_ECOURTS_CNR", "DLND020047882015");

function password(): string {
  const value = process.env.CASEOPS_RAM_PROD_PASSWORD?.trim();
  if (!value) throw new Error("CASEOPS_RAM_PROD_PASSWORD is required.");
  return value;
}

async function expectStatus(
  response: Pick<APIResponse, "status">,
  expected: number,
  label: string,
): Promise<void> {
  expect(response.status(), label).toBe(expected);
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

test("funded eCourtsIndia and Indian Kanoon paths work end to end", async ({
  page,
}) => {
  const token = await signIn(page);
  const headers = { Authorization: `Bearer ${token}` };

  await test.step("both providers report ready without manual approval gates", async () => {
    const operations = await page.request.get(
      `${API_BASE_URL}/api/admin/provider-operations/readiness`,
      { headers },
    );
    await expectStatus(operations, 200, "provider readiness");
    const providers = new Map(
      (
        (await operations.json()).providers as Array<{
          provider: string;
          state: string;
          external_calls_enabled: boolean;
          missing_approval_keys: string[];
        }>
      ).map((record) => [record.provider, record]),
    );
    for (const providerName of ["ecourtsindia", "indian-kanoon"]) {
      const provider = providers.get(providerName);
      expect(provider, `${providerName} readiness record`).toBeDefined();
      expect(provider?.state, `${providerName} state`).toBe("ready");
      expect(provider?.external_calls_enabled).toBe(true);
      expect(provider?.missing_approval_keys).toEqual([]);
    }
  });

  await test.step("one Indian Kanoon search returns attributed licensed results", async () => {
    const search = await page.request.post(
      `${API_BASE_URL}/api/authorities/providers/indian-kanoon/search`,
      {
        headers,
        data: {
          query: "Kesavananda Bharati v State of Kerala AIR 1973 SC 1461",
          page_number: 0,
          max_results: 1,
        },
      },
    );
    await expectStatus(search, 200, "Indian Kanoon live search");
    const body = await search.json();
    expect(body.returned_count).toBeGreaterThan(0);
    expect(body.results).toHaveLength(1);
    expect(body.attribution.label).toBe("Powered by Indian Kanoon");
    expect(body.results[0].canonical_url).toMatch(
      /^https:\/\/indiankanoon\.org\/doc\//,
    );
  });

  let caseNumber = "";
  let courtCode = "";
  await test.step("one eCourts CNR lookup returns normalized case data", async () => {
    const search = await page.request.post(
      `${API_BASE_URL}/api/case-tracking/search`,
      { headers, data: { cnr_number: LIVE_CNR } },
    );
    await expectStatus(search, 200, "eCourts live CNR lookup");
    const body = await search.json();
    expect(body.provider).toBe("ecourtsindia");
    expect(body.results).toHaveLength(1);
    expect(body.results[0].cnr_number.replace(/[^A-Za-z0-9]/g, "")).toBe(
      LIVE_CNR.replace(/[^A-Za-z0-9]/g, "").toUpperCase(),
    );
    expect(body.results[0].case_title.trim().length).toBeGreaterThan(0);
    caseNumber = body.results[0].case_number ?? "";
    courtCode = body.results[0].court_code ?? "";
    expect(caseNumber, "provider case number").not.toBe("");
  });

  await test.step("the returned case number is searchable through CaseOps", async () => {
    const search = await page.request.post(
      `${API_BASE_URL}/api/case-tracking/search`,
      {
        headers,
        data: {
          case_number: caseNumber,
          court_code: courtCode || null,
        },
      },
    );
    await expectStatus(search, 200, "eCourts live case-number search");
    const body = await search.json();
    expect(body.results.length).toBeGreaterThan(0);
  });

  await test.step("provider-backed user surfaces render ready", async () => {
    await page.goto(`${BASE_URL}/app/research`);
    await page.getByTestId("research-source-indian-kanoon").click();
    await expect(
      page.getByTestId("research-indian-kanoon-readiness"),
    ).toContainText("Licensed access is active");

    await page.goto(`${BASE_URL}/app/case-tracking`);
    await expect(page.getByTestId("case-tracking-search")).toBeVisible();
    await expect(
      page.getByTestId("case-tracking-support-matrix"),
    ).toContainText("supported");
  });
});
