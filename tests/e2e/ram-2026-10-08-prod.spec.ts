import { randomUUID } from "node:crypto";

import { expect, test, type Locator, type Page } from "@playwright/test";

import { noPaidProviderHeaders } from "./support/cost-controls";
import { e2eEnv } from "./support/env";

const enabled = process.env.CASEOPS_CALENDAR_OAUTH_PROD === "true";
const api = process.env.PROD_API_BASE_URL ?? "https://api.caseops.ai";
const expectedSha = process.env.CASEOPS_EXPECTED_RELEASE_SHA;
const expectedAccount = process.env.CASEOPS_CALENDAR_OAUTH_ACCOUNT;

test.use({
  extraHTTPHeaders: noPaidProviderHeaders,
  storageState: { cookies: [], origins: [] },
  trace: "off", screenshot: "off", video: "off",
});
test.describe.configure({ retries: 0 });
test.setTimeout(120_000);

async function assertRelease(page: Page) {
  if (!expectedSha || !/^[a-f0-9]{40}$/.test(expectedSha)) {
    throw new Error("An exact expected production release SHA is required.");
  }
  for (const url of [`${api}/api/build`, "/api/release-identity"]) {
    const response = await page.request.get(url);
    expect(response.status()).toBe(200);
    expect((await response.json()).release_sha).toBe(expectedSha);
  }
}

async function signIn(page: Page) {
  const password = process.env.CASEOPS_RAM_PROD_PASSWORD;
  if (!password) throw new Error("Calendar acceptance requires tester credentials.");
  await assertRelease(page);
  await page.goto("/sign-in");
  await page.locator("#company-slug").fill(process.env.CASEOPS_RAM_PROD_SLUG ?? "test-legal");
  await page.locator("#email").fill(process.env.CASEOPS_RAM_PROD_EMAIL ?? "ram@testfirm.com");
  await page.locator("#password").fill(password);
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  await page.waitForURL(/\/app(?:\/|$)/);
}

test("BUG-003/004: live authorization scopes and rejected callback return to Calendar safely", async ({ page }) => {
  test.skip(!enabled, "Explicit Calendar OAuth production acceptance is required; no Google consent is fabricated.");
  await signIn(page);
  await page.goto("/app/calendar");
  await expect(page.getByTestId("calendar-google-panel")).toBeVisible({ timeout: 60_000 });
  const csrf = (await page.context().cookies(api)).find((cookie) => cookie.name === "caseops_csrf");
  expect(csrf, "Authenticated browser CSRF cookie is required").toBeTruthy();
  const start = await page.request.post(`${api}/api/calendar/connections/google-calendar/start`, {
    headers: { "X-CSRF-Token": csrf!.value },
  });
  expect(start.status()).toBe(200);
  const result = await start.json();
  expect(result.provider_available).toBe(true);
  const authorization = new URL(result.auth_url);
  expect(authorization.origin).toBe("https://accounts.google.com");
  expect(authorization.searchParams.get("scope")?.split(" ")).toEqual(expect.arrayContaining([
    "openid", "email", "https://www.googleapis.com/auth/calendar.events",
  ]));

  // An invalid state must fail before transport. Do not spend a live Google code.
  await page.goto(`${api}/api/calendar/connections/google-calendar/callback?code=invalid-acceptance-code&state=invalid-acceptance-state`);
  await page.waitForURL(/\/app\/calendar\?oauth_provider=google_calendar&oauth_result=retry$/);
  for (const width of [1280, 393]) {
    await page.setViewportSize({ width, height: 900 });
    await expect(page.getByTestId("oauth-callback-notice")).toHaveText(/Start a new connection/);
    await expect(page.getByTestId("calendar-google-panel")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.reload();
    await expect(page.getByTestId("oauth-callback-notice")).toBeVisible();
  }
  await assertRelease(page);
});

test("BUG-003: owner-consented Google account remains connected after responsive reloads", async ({ page }) => {
  test.skip(!enabled, "Explicit Calendar OAuth production acceptance is required; no Google consent is fabricated.");
  test.skip(!expectedAccount, "No owner-authorized Google account/consent supplied; live successful OAuth is unverified.");
  await signIn(page);
  for (const width of [1280, 393]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/app/calendar");
    const response = await page.request.get(`${api}/api/calendar/connections`);
    expect(response.status()).toBe(200);
    const records = (await response.json()).connections;
    const connection = records.find((row: { provider: string; status: string; display_email: string }) =>
      row.provider === "google_calendar" && row.status === "connected" && row.display_email === expectedAccount);
    expect(connection, "The actual owner-consented Google connection must be persisted").toBeTruthy();
    expect(connection.provider_account_id).toBeTruthy();
    await expect(page.getByTestId("calendar-google-panel")).toContainText(`Connected as ${expectedAccount}`);
    await expect(page.getByTestId("calendar-google-sync-range")).toBeEnabled();
    await page.reload();
    await expect(page.getByTestId("calendar-google-panel")).toContainText(`Connected as ${expectedAccount}`);
  }
  await assertRelease(page);
});

type IntakeMatter = { id: string; matter_code: string; status: string; updated_at: string };
type IntakeCandidate = {
  id: string; company_id: string; provider_event_id: string; title: string; status: string;
  suggested_matter_id: string | null; linked_matter_id: string | null;
  linked_hearing_id: string | null; confidence: number | null;
};

function requiredQa(value: string | undefined, label: string): string {
  if (!value?.trim()) throw new Error(`Calendar intake requires ${label}; missing setup is not a skip.`);
  return value.trim();
}

async function visibleControl(control: Locator, page: Page) {
  await expect(control).toBeVisible();
  await control.scrollIntoViewIfNeeded();
  const box = await control.boundingBox();
  expect(box).not.toBeNull();
  expect(box!.width).toBeGreaterThan(24);
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(page.viewportSize()!.width + 1);
}

test("Calendar auto-candidate intake persists the suggested Matter without OAuth or provider calls", async ({ page, request, baseURL }) => {
  if (!baseURL) throw new Error("Use the canonical app, Docker or production config.");
  const web = new URL(baseURL);
  const loopback = (url: URL) => ["127.0.0.1", "localhost", "[::1]"].includes(url.hostname);
  const local = loopback(web);
  const localApi = `http://127.0.0.1:${process.env.CASEOPS_E2E_API_PORT || "8000"}`;
  const suppliedApi = process.env.PROD_API_BASE_URL?.trim();
  const apiUrl = new URL(local
    ? process.env.CASEOPS_E2E_API_PORT ? localApi
      : suppliedApi && loopback(new URL(suppliedApi)) ? suppliedApi : localApi
    : requiredQa(suppliedApi, "PROD_API_BASE_URL"));
  if (loopback(apiUrl) !== local) throw new Error("Calendar intake refuses mixed local/live endpoints.");
  if (!local && (web.origin !== "https://caseops.ai" || apiUrl.origin !== "https://api.caseops.ai")) {
    throw new Error("Live Calendar intake is restricted to canonical production origins.");
  }
  const sha = local
    ? process.env.CASEOPS_EXPECTED_RELEASE_SHA || process.env.CASEOPS_RELEASE_SHA || e2eEnv.CASEOPS_RELEASE_SHA
    : requiredQa(expectedSha, "CASEOPS_EXPECTED_RELEASE_SHA");
  expect(sha, "exact API and web identity is mandatory, including Docker").toMatch(/^[a-f0-9]{40}$/);
  const identity = async () => {
    for (const endpoint of [`${apiUrl.origin}/api/build`, `${web.origin}/api/release-identity`]) {
      const response = await page.request.get(endpoint, {
        headers: noPaidProviderHeaders, maxRetries: 0, maxRedirects: 0,
      });
      expect(response.status(), "exact Calendar intake serving identity").toBe(200);
      expect((await response.json()).release_sha).toBe(sha);
    }
  };
  await identity();
  const run = randomUUID().replaceAll("-", "").toUpperCase();
  const slug = local ? `calendar-intake-${run.toLowerCase()}`
    : requiredQa(process.env.CASEOPS_QA_SLUG || process.env.CASEOPS_RAM_PROD_SLUG, "existing dedicated QA slug");
  if (!local && !["caseops-qa", "test-legal"].includes(slug)) {
    throw new Error("Calendar intake may mutate only existing dedicated QA tenants, never GBA or a real tenant.");
  }
  const email = local ? `calendar-${run.toLowerCase()}@example.com`
    : requiredQa(process.env.CASEOPS_QA_EMAIL || process.env.CASEOPS_RAM_PROD_EMAIL, "existing dedicated QA email");
  const password = local ? `CalendarIntake!${randomUUID()}`
    : requiredQa(process.env.CASEOPS_QA_PASSWORD || process.env.CASEOPS_RAM_PROD_PASSWORD, "existing dedicated QA password");
  if (local) {
    const bootstrap = await request.post(`${apiUrl.origin}/api/bootstrap/company`, {
      headers: noPaidProviderHeaders, maxRetries: 0, maxRedirects: 0,
      data: { company_name: "Calendar candidate loopback acceptance", company_slug: slug,
        company_type: "law_firm", owner_full_name: "Calendar intake fixture",
        owner_email: email, owner_password: password },
    });
    expect(bootstrap.status(), "bootstrap only this fresh loopback tenant").toBe(200);
  }
  const forbidden: string[] = [];
  await page.route("**/*", async route => {
    const url = new URL(route.request().url());
    const oauthPath = /\/api\/calendar\/connections\/.+\/(?:start|callback)$/;
    const providerPath = /\/api\/(?:mailbox\/gmail\/import|drive\/google\/candidates\/sync|case-tracking\/.*(?:search|refresh|resolve))/;
    const calendarMutation = route.request().method() !== "GET"
      && url.pathname.startsWith("/api/calendar/")
      && !url.pathname.startsWith("/api/calendar/provider-event-candidates");
    if ((/^https?:$/.test(url.protocol) && ![web.origin, apiUrl.origin].includes(url.origin))
      || oauthPath.test(url.pathname) || providerPath.test(url.pathname) || calendarMutation) {
      forbidden.push(url.pathname);
      return route.abort("blockedbyclient");
    }
    return route.continue();
  });
  await page.goto("/sign-in");
  await page.locator("#company-slug").fill(slug);
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(password);
  const loggedIn = page.waitForResponse(response => new URL(response.url()).pathname === "/api/auth/login"
    && response.request().method() === "POST");
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  expect((await loggedIn).status(), "authenticate existing QA actor through the visible sign-in").toBe(200);
  await page.waitForURL(/\/app(?:[/?]|$)/);
  const current = await page.request.get(`${apiUrl.origin}/api/companies/current`, {
    headers: noPaidProviderHeaders, maxRetries: 0, maxRedirects: 0,
  });
  expect(current.status()).toBe(200);
  const actor = await current.json();
  expect(actor.company.slug).toBe(slug);
  expect(actor.user.email.toLowerCase()).toBe(email.toLowerCase());
  const csrf = (await page.context().cookies(apiUrl.origin)).find(cookie => cookie.name === "caseops_csrf");
  expect(csrf, "authenticated browser CSRF is required").toBeTruthy();
  const headers = { ...noPaidProviderHeaders, "X-CSRF-Token": csrf!.value };
  const candidates: string[] = [];
  let matter: IntakeMatter | undefined;
  try {
    await identity();
    const createdMatter = await page.request.post(`${apiUrl.origin}/api/matters/`, {
      headers, maxRetries: 0, maxRedirects: 0,
      data: { matter_code: run, title: `Calendar intake QA ${run}`, practice_area: "litigation",
        forum_level: "high_court", status: "intake", assignee_membership_id: null, team_id: null },
    });
    expect(createdMatter.status(), "unique known QA Matter with no external court identity").toBe(200);
    matter = await createdMatter.json() as IntakeMatter;
    expect(matter.matter_code).toBe(run);
    expect(matter.status).toBe("intake");
    const starts = new Date(Date.now() + 7 * 86_400_000).toISOString();
    const admit = async (title: string, event: string): Promise<IntakeCandidate> => {
      const data = { provider: "google_calendar", provider_event_id: event, title, starts_at: starts };
      expect(data).not.toHaveProperty("suggested_matter_id");
      const response = await page.request.post(`${apiUrl.origin}/api/calendar/provider-event-candidates`, {
        headers, data, maxRetries: 0, maxRedirects: 0,
      });
      expect(response.status(), "single local metadata admission; no OAuth/provider transport").toBe(200);
      const record = await response.json() as IntakeCandidate;
      candidates.push(record.id);
      expect(record).toMatchObject({ company_id: actor.company.id, provider_event_id: event, title,
        status: "new", linked_matter_id: null, linked_hearing_id: null });
      return record;
    };
    const matched = await admit(run.toLowerCase(), `calendar-intake-${run}-match`);
    expect(matched.suggested_matter_id).toBe(matter.id);
    expect(matched.confidence).toBe(0.9);
    const unmatched = await admit(randomUUID(), `calendar-intake-${run}-unmatched`);
    expect(unmatched.suggested_matter_id).toBeNull();
    expect(unmatched.confidence).toBeNull();
    const deniedEvent = `calendar-intake-${run}-denied`;
    const denied = await page.request.post(`${apiUrl.origin}/api/calendar/provider-event-candidates`, {
      headers, maxRetries: 0, maxRedirects: 0,
      data: { provider: "google_calendar", provider_event_id: deniedEvent, title: run,
        starts_at: starts, suggested_matter_id: randomUUID() },
    });
    expect(denied.status(), "an explicit nonexistent Matter cannot fall back to the visible title match").toBe(404);

    const inspect = async (reload: boolean) => {
      const loaded = page.waitForResponse(response => {
        const url = new URL(response.url());
        return url.pathname === "/api/calendar/provider-event-candidates"
          && response.request().method() === "GET" && url.searchParams.get("limit") === "75";
      });
      if (reload) await page.reload();
      else await page.goto("/app/calendar/conflicts");
      const response = await loaded;
      expect(response.status(), "actual browser intake read after persistence").toBe(200);
      expect(response.request().headers()["x-caseops-automated-test"]).toBe("no-paid-providers");
      const rows = (await response.json()).candidates as IntakeCandidate[];
      expect(rows.find(row => row.id === matched.id)).toMatchObject({ suggested_matter_id: matter!.id, status: "new" });
      expect(rows.find(row => row.id === unmatched.id)).toMatchObject({ suggested_matter_id: null, status: "new" });
      expect(rows.filter(row => row.provider_event_id === deniedEvent)).toEqual([]);
      await expect(page.getByRole("heading", { name: "Sync conflicts", exact: true })).toBeVisible();
      await expect(page.getByText("Could not load calendar candidates", { exact: true })).toHaveCount(0);
      await expect(page.getByLabel("Matter id for accept")).toHaveValue("");
      for (const [record, suggested] of [[matched, matter!.id], [unmatched, "none"]] as const) {
        const row = page.locator("div.grid").filter({ has: page.getByText(record.title, { exact: true }) });
        await expect(row).toHaveCount(1);
        await expect(row.getByText(record.title, { exact: true })).toBeVisible();
        await expect(row.getByText(`Suggested: ${suggested}`, { exact: true })).toBeVisible();
        await expect(row.getByText("Linked: none", { exact: true })).toBeVisible();
        await expect(row.getByText("new", { exact: true })).toBeVisible();
        const accept = row.getByRole("button", { name: "Accept", exact: true });
        if (record.id === matched.id) await expect(accept).toBeEnabled();
        else await expect(accept).toBeDisabled();
        for (const label of ["Accept", "Reject", "Ignore"]) {
          const control = row.getByRole("button", { name: label, exact: true });
          await visibleControl(control, page);
          if (label !== "Accept") await expect(control).toBeEnabled();
        }
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
    };
    for (const width of [1280, 393]) {
      await page.setViewportSize({ width, height: 900 });
      await inspect(false);
      await inspect(true);
    }
    const persistedMatter = await page.request.get(`${apiUrl.origin}/api/matters/${matter.id}`, {
      headers, maxRetries: 0, maxRedirects: 0,
    });
    expect(persistedMatter.status()).toBe(200);
    expect(await persistedMatter.json()).toMatchObject({ status: "intake", next_hearing_on: null });
    expect(forbidden, "intake never attempts OAuth or a provider operation").toEqual([]);
    await identity();
  } finally {
    const cleanupFailures: string[] = [];
    const clean = async (label: string, action: () => Promise<void>) => {
      try { await action(); } catch (error) {
        cleanupFailures.push(`${label}: ${error instanceof Error ? error.message : "Unknown cleanup failure"}`);
      }
    };
    for (const id of candidates) await clean("ignore retained intake candidate", async () => {
      const ignored = await page.request.patch(`${apiUrl.origin}/api/calendar/provider-event-candidates/${id}`, {
        headers, data: { action: "ignore" }, maxRetries: 0, maxRedirects: 0,
      });
      expect(ignored.status()).toBe(200);
      expect((await ignored.json()).candidate.status).toBe("ignored");
    });
    if (matter) await clean("dispose only this unique QA Matter", async () => {
      const read = await page.request.get(`${apiUrl.origin}/api/matters/${matter!.id}`, {
        headers, maxRetries: 0, maxRedirects: 0,
      });
      expect(read.status()).toBe(200);
      const currentMatter = await read.json() as IntakeMatter;
      const disposed = await page.request.patch(`${apiUrl.origin}/api/matters/${matter!.id}/lifecycle/status`, {
        headers, maxRetries: 0, maxRedirects: 0,
        data: { to_status: "disposed", expected_from_status: currentMatter.status,
          expected_updated_at: currentMatter.updated_at,
          reason: "Calendar intake 2026-10-10 acceptance completed; retain terminal evidence." },
      });
      expect(disposed.status()).toBe(200);
      const persisted = await page.request.get(`${apiUrl.origin}/api/matters/${matter!.id}`, {
        headers, maxRetries: 0, maxRedirects: 0,
      });
      expect(persisted.status()).toBe(200);
      expect((await persisted.json()).status).toBe("disposed");
    });
    await clean("exact serving release after cleanup", identity);
    expect(cleanupFailures, "all cleanup attempts are single-shot and failures remain actionable").toEqual([]);
  }
});
