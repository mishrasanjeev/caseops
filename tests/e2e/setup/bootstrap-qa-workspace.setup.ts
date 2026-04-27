/**
 * One-off bootstrap script for the dedicated CaseOps QA test workspace.
 *
 * Why a script (not a long-lived setup project): we want to create the
 * workspace ONCE on prod and then never touch this code again. The
 * normal ram-auth.setup.ts handles per-test sign-in for the QA bot.
 *
 * Run:
 *   npx playwright test tests/e2e/setup/bootstrap-qa-workspace.ts \
 *     --config=playwright.prod-ram.config.ts --project=setup
 *
 * On the FIRST run: posts the bootstrap form via the web sign-in page's
 * "New workspace" tab (gives Playwright the CSRF cookie + Origin
 * header naturally).
 *
 * On subsequent runs: the workspace already exists → bootstrap returns
 * 409 → script exits cleanly with a "already exists" message.
 *
 * Credentials are read from env so they never live in committed code.
 */
import { test, expect } from "@playwright/test";

const PROD_BASE_URL = process.env.PROD_BASE_URL ?? "https://caseops.ai";
const QA_COMPANY_NAME = process.env.QA_COMPANY_NAME ?? "CaseOps QA Bot";
const QA_COMPANY_SLUG = process.env.QA_COMPANY_SLUG ?? "caseops-qa";
const QA_OWNER_NAME = process.env.QA_OWNER_NAME ?? "QA Bot";
// Use a real TLD — EmailStr rejects reserved TLDs (.test, .example, etc.).
// caseops.ai is the production domain so the email routes to us if any
// verification flow ever needs to deliver mail.
const QA_OWNER_EMAIL = process.env.QA_OWNER_EMAIL ?? "qa-bot@caseops.ai";
const QA_OWNER_PASSWORD = process.env.QA_OWNER_PASSWORD ?? "";

test("bootstrap QA workspace on prod (idempotent)", async ({ page }) => {
  if (!QA_OWNER_PASSWORD) {
    throw new Error(
      "QA_OWNER_PASSWORD env var is required. Generate a strong password " +
      "and set it before running this script.",
    );
  }
  test.setTimeout(60_000);

  // Visit the sign-in page first to seed cookies (notably caseops_csrf
  // which the API requires for state-changing POSTs).
  await page.goto(`${PROD_BASE_URL}/sign-in`);

  // Call bootstrap directly via fetch from the browser context. The
  // form-submit path is fragile here; the same-origin fetch auto-sends
  // CSRF cookie + correct Origin header.
  const result = await page.evaluate(
    async (args: { apiBase: string; payload: Record<string, string> }) => {
      const csrfMatch = document.cookie.match(
        /(?:^|;\s*)caseops_csrf=([^;]+)/,
      );
      const csrf = csrfMatch ? decodeURIComponent(csrfMatch[1]) : "";
      const resp = await fetch(`${args.apiBase}/api/bootstrap/company`, {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          ...(csrf ? { "X-CSRF-Token": csrf } : {}),
        },
        body: JSON.stringify(args.payload),
      });
      const body = await resp.text();
      return { status: resp.status, body };
    },
    {
      apiBase: process.env.PROD_API_BASE_URL ?? "https://api.caseops.ai",
      payload: {
        company_name: QA_COMPANY_NAME,
        company_slug: QA_COMPANY_SLUG,
        company_type: "law_firm",
        owner_full_name: QA_OWNER_NAME,
        owner_email: QA_OWNER_EMAIL,
        owner_password: QA_OWNER_PASSWORD,
      },
    },
  );

  // eslint-disable-next-line no-console
  console.log(
    `BOOTSTRAP-RESULT status=${result.status} body=${result.body.slice(0, 300)}`,
  );

  // 200/201 = workspace created; 409 = already exists (idempotent ok).
  expect([200, 201, 409]).toContain(result.status);

  if (result.status === 200 || result.status === 201) {
    // eslint-disable-next-line no-console
    console.log(
      `QA-WORKSPACE-CREATED slug=${QA_COMPANY_SLUG} email=${QA_OWNER_EMAIL}`,
    );
  } else {
    // eslint-disable-next-line no-console
    console.log(`QA-WORKSPACE-EXISTS slug=${QA_COMPANY_SLUG} (idempotent ok)`);
  }
});
