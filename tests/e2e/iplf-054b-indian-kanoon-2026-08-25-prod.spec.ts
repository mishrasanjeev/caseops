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
  const detail = response.status() === expected ? "" : ` ${await response.text()}`;
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
  await page.evaluate((context) => {
    window.localStorage.setItem("caseops.session.context", JSON.stringify(context));
  }, {
    company: session.company,
    user: session.user,
    membership: session.membership,
    capabilities: session.capabilities,
  });
  return session.access_token;
}

test("IPLF-054B production keeps unconfigured Indian Kanoon calls disabled", async ({
  page,
}) => {
  const token = await signIn(page);
  const headers = { Authorization: `Bearer ${token}` };
  const readiness = await page.request.get(
    `${API_BASE_URL}/api/authorities/providers/indian-kanoon/readiness`,
    { headers },
  );
  await expectStatus(readiness, 200, "licensed-source readiness");
  const body = await readiness.json();
  expect(body.state).toBe("blocked_disabled");
  expect(body.external_calls_enabled).toBe(false);

  const search = await page.request.post(
    `${API_BASE_URL}/api/authorities/providers/indian-kanoon/search`,
    {
      headers,
      data: { query: "production acceptance must not reach the provider" },
    },
  );
  await expectStatus(search, 503, "default-off search boundary");
  expect((await search.json()).code).toBe("provider_disabled");

  await page.goto(`${BASE_URL}/app/research`);
  await page.getByTestId("research-source-indian-kanoon").click();
  await expect(page.getByTestId("research-indian-kanoon-readiness")).toContainText(
    "Licensed access is disabled by the runtime switch",
  );
  await page.getByTestId("research-query-input").fill("constitutional proportionality");
  await expect(page.getByTestId("research-query-submit")).toBeDisabled();
});
