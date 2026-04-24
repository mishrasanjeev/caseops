/**
 * BUG-011 reproduction probe (2026-04-24, Ram).
 * Logs in to prod, then triggers a mutating request and captures the
 * exact failure shape so we can see whether:
 *  (a) the CSRF cookie isn't being set on login (server bug)
 *  (b) the cookie is set but the web client isn't echoing it (client bug)
 *  (c) the request reaches the server with both but the comparison
 *      fails (timing/middleware bug)
 *
 * Not part of the regular smoke suite — used only for triage.
 */
import { expect, request as pwRequest, test } from "@playwright/test";

const STAMP = `${Date.now()}-${Math.floor(Math.random() * 1e6).toString(36)}`;
const SLUG = `csrf-probe-${STAMP}`;
const EMAIL = `csrf+${STAMP}@example.com`;
const PASSWORD = "SmokePass1234!";
const API_BASE = "https://api.caseops.ai";

test("BUG-011 reproduction: capture CSRF cookie + header round trip", async ({
  page,
}) => {
  // Bootstrap a fresh tenant via the API so we're not hijacking a
  // shared one. This sets the session + CSRF cookies on the
  // browser via a direct page.goto + sign-in.
  const ctx = await pwRequest.newContext({ baseURL: API_BASE });
  const boot = await ctx.post("/api/bootstrap/company", {
    data: {
      company_name: `CSRF Probe ${STAMP}`,
      company_slug: SLUG,
      company_type: "law_firm",
      owner_full_name: "CSRF Probe",
      owner_email: EMAIL,
      owner_password: PASSWORD,
    },
  });
  expect(boot.status()).toBe(200);
  await ctx.dispose();

  // Capture every request URL + headers + every response cookie set.
  const requests: Array<{ url: string; method: string; headers: Record<string, string> }> = [];
  const responses: Array<{ url: string; status: number; setCookie: string | null }> = [];
  page.on("request", (r) =>
    requests.push({ url: r.url(), method: r.method(), headers: r.headers() }),
  );
  page.on("response", async (r) => {
    if (r.url().includes("/api/")) {
      responses.push({
        url: r.url(),
        status: r.status(),
        setCookie: r.headers()["set-cookie"] ?? null,
      });
    }
  });

  await page.goto("https://caseops.ai/sign-in");
  await page.locator("#company-slug").fill(SLUG);
  await page.locator("#email").fill(EMAIL);
  await page.locator("#password").fill(PASSWORD);
  await page.getByRole("button", { name: /^sign in$/i }).click();
  await page.waitForURL(/\/app(\/|$)/);

  // Cookies after login.
  const cookies = await page.context().cookies();
  console.log("[BUG-011] cookies after login:", cookies.map((c) => `${c.name}=${c.value.length} chars (httpOnly=${c.httpOnly}, sameSite=${c.sameSite})`));

  // Trigger a mutating request: create a matter via the UI.
  await page.goto("https://caseops.ai/app/matters");
  await page.getByRole("button", { name: /new matter|create matter/i }).first().click({ timeout: 15_000 }).catch(() => {});

  // Wait + dump the API requests we observed.
  await page.waitForTimeout(2000);
  const apiReqs = requests.filter((r) => r.url.includes("/api/") && r.method !== "GET");
  console.log("[BUG-011] mutating /api/* requests observed:");
  for (const r of apiReqs) {
    console.log(
      `  ${r.method} ${r.url}\n    cookie? ${Boolean(r.headers["cookie"])}, x-csrf-token? ${Boolean(r.headers["x-csrf-token"])}`,
    );
  }
  console.log("[BUG-011] /api responses:");
  for (const r of responses) {
    console.log(`  ${r.status} ${r.url}`);
  }
});
