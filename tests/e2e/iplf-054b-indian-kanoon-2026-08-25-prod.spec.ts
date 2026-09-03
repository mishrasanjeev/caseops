/** IPLF-054B dated production acceptance for the fail-closed licensed source. */

import { expect, test, type APIResponse, type Page } from "@playwright/test";

const envOr = (key: string, fallback: string): string =>
  (process.env[key] ?? "").trim() || fallback;

const BASE_URL = envOr("PROD_BASE_URL", "https://caseops.ai");
const API_BASE_URL = envOr("PROD_API_BASE_URL", "https://api.caseops.ai");
const COMPANY_SLUG = envOr("CASEOPS_RAM_PROD_SLUG", "legal");
const TESTER_EMAIL = envOr("CASEOPS_RAM_PROD_EMAIL", "hari.gupta@gmail.com");

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
  await expectStatus(login, 200, "production tester API sign-in");
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

test("IPLF-054B production activates Indian Kanoon while blocking QA spend", async ({
  page,
}) => {
  const token = await signIn(page);
  const headers = { Authorization: `Bearer ${token}` };
  const readiness = await page.request.get(
    `${API_BASE_URL}/api/authorities/providers/indian-kanoon/readiness`,
    { headers },
  );
  await expectStatus(readiness, 200, "licensed-source readiness");
  const body = (await readiness.json()) as {
    state: string;
    external_calls_enabled: boolean;
    missing_approval_keys: string[];
    missing_config_names: string[];
    missing_cost_categories: string[];
    permitted_uses: string[];
  };
  expect(body.state).toBe("ready");
  expect(body.external_calls_enabled).toBe(true);
  expect(body.missing_approval_keys).toEqual([]);
  expect(body.missing_config_names).toEqual([]);
  expect(body.missing_cost_categories).toEqual([]);
  expect(body.permitted_uses).toEqual([
    "document_display",
    "research_storage",
    "search",
  ]);

  const search = await page.request.post(
    `${API_BASE_URL}/api/authorities/providers/indian-kanoon/search`,
    {
      headers,
      data: { query: "production acceptance must not reach the provider" },
    },
  );
  await expectStatus(search, 409, "no-paid-provider QA boundary");
  expect((await search.json()).code).toBe("paid_provider_blocked_for_test");

  await page.goto(`${BASE_URL}/app/research`);
  await page.getByTestId("research-source-indian-kanoon").click();
  const readinessMessage = page.getByTestId("research-indian-kanoon-readiness");
  await expect(readinessMessage).not.toContainText(
    "Checking licensed-source readiness",
  );
  const readinessCopy = await readinessMessage.innerText();
  expect(readinessCopy.toLowerCase()).not.toContain("approval");
  expect(readinessCopy).toContain("Licensed access is active");
  await page
    .getByTestId("research-query-input")
    .fill("constitutional proportionality");
  await expect(page.getByTestId("research-query-submit")).toBeEnabled();
});
