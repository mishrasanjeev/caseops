import { expect, test, type Page } from "@playwright/test";

const PROD_BASE_URL = process.env.PROD_BASE_URL ?? "https://caseops.ai";
const PROD_API_BASE_URL =
  process.env.PROD_API_BASE_URL ?? "https://api.caseops.ai";
const COMPANY_SLUG = process.env.CASEOPS_RAM_PROD_SLUG ?? "legal";
const TESTER_EMAIL = process.env.CASEOPS_RAM_PROD_EMAIL ?? "hari.gupta@gmail.com";

function requiredPassword(): string {
  const password = process.env.CASEOPS_RAM_PROD_PASSWORD?.trim() ?? "";
  if (!password) throw new Error("CASEOPS_RAM_PROD_PASSWORD is required for production proof.");
  return password;
}

async function signIn(page: Page): Promise<void> {
  await page.goto(`${PROD_BASE_URL}/sign-in`);
  await page.locator("#company-slug").fill(COMPANY_SLUG);
  await page.locator("#email").fill(TESTER_EMAIL);
  await page.locator("#password").fill(requiredPassword());
  const login = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/api/auth/login" &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  expect((await login).status()).toBe(200);
  await page.waitForURL(new RegExp(`${PROD_BASE_URL}/app(?:[/?]|$)`));
}

test("IPLF-025A production serves the exact shared-work contract and a ready tenant reconciliation", async ({
  page,
}) => {
  test.setTimeout(120_000);
  const unauthenticated = await fetch(
    `${PROD_API_BASE_URL}/api/ip/shared-work/foundation-contract`,
  );
  expect(unauthenticated.status).toBe(401);

  await signIn(page);
  const contract = await page.request.get(
    `${PROD_API_BASE_URL}/api/ip/shared-work/foundation-contract`,
  );
  expect(contract.status(), await contract.text()).toBe(200);
  expect(await contract.json()).toMatchObject({
    contract_version: "IPLF-025A/2026-08-10",
    migration_heads: ["20260810_0001", "20260810_0002", "20260810_0003"],
    target_rule: "Exactly one of matter_id or ip_docket_id on target-owned rows.",
    forbidden_duplicates: [
      "ip_tasks",
      "ip_hearings",
      "ip_operational_deadlines",
      "ip_calendar_events",
      "ip_notification_intents",
    ],
  });

  const reconciliation = await page.request.get(
    `${PROD_API_BASE_URL}/api/ip/shared-work/reconciliation`,
  );
  expect(reconciliation.status(), await reconciliation.text()).toBe(200);
  const report = await reconciliation.json();
  expect(report).toMatchObject({
    contract_version: "IPLF-025A/2026-08-10",
    release_blocking: true,
    ready: true,
    notification_tenant_mismatch_rows: 0,
  });
  expect(report.owners).toHaveLength(6);
  for (const owner of report.owners as Array<{
    ready: boolean;
    invalid_target_rows: number;
    tenant_mismatch_rows: number;
  }>) {
    expect(owner.ready).toBe(true);
    expect(owner.invalid_target_rows).toBe(0);
    expect(owner.tenant_mismatch_rows).toBe(0);
  }
});
