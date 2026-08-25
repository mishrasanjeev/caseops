/** IPLF-056B dated production acceptance for shared IP provider operations. */

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

test("IPLF-056B production exposes one fail-closed IP provider control plane", async ({
  page,
}) => {
  const token = await signIn(page);
  const headers = { Authorization: `Bearer ${token}` };
  const readiness = await page.request.get(
    `${API_BASE_URL}/api/admin/provider-operations/readiness`,
    { headers },
  );
  await expectStatus(readiness, 200, "provider readiness");
  const providers = new Map(
    (await readiness.json()).providers.map((row: { provider: string }) => [
      row.provider,
      row,
    ]),
  );
  expect(providers.get("ipindia-registry")).toEqual(
    expect.objectContaining({
      enabled: false,
      external_calls_enabled: false,
      adapter_contract: expect.objectContaining({
        operations_path: "/api/admin/provider-operations/jobs",
        implemented_capabilities: [],
      }),
    }),
  );
  expect(providers.get("indian-kanoon")).toEqual(
    expect.objectContaining({
      external_calls_enabled: false,
      adapter_contract: expect.objectContaining({
        operations_path: "/api/admin/provider-operations/jobs",
      }),
    }),
  );

  await page.goto(`${BASE_URL}/app/admin/provider-operations`);
  await expect(page.getByTestId("readiness-ipindia-registry")).toContainText(
    "external calls off",
  );
  await expect(page.getByTestId("readiness-indian-kanoon")).toContainText(
    "external calls off",
  );
  const visibleText = await page.locator("body").innerText();
  expect(visibleText).not.toContain(token);
  expect(visibleText).not.toMatch(
    /(?:api[_ -]?token|authorization)\s*[:=]\s*(?:bearer\s+)?[a-z0-9._-]{16,}/i,
  );

  await page.goto(`${BASE_URL}/app/ip`);
  await expect(page.getByText(/manual docketing/i).first()).toBeVisible();
});
