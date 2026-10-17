/** CAL13-04 / J08: deterministic provider transport, not live OAuth certification. */
import { randomUUID } from "node:crypto";

import { expect, test, type APIResponse, type Page } from "@playwright/test";

import { noPaidProviderHeaders } from "./support/cost-controls";
import { apiBaseUrl, e2eEnv } from "./support/env";

test.use({ extraHTTPHeaders: noPaidProviderHeaders, storageState: { cookies: [], origins: [] },
  trace: "off", video: "off", screenshot: "off" });
test.describe.configure({ mode: "default", retries: 0 });

const emulator = apiBaseUrl + "/_e2e/calendar-oauth";
const account = "calendar-emulator@example.test";

function localOnly(value: string): void {
  const url = new URL(value);
  if (url.protocol !== "http:" || !["127.0.0.1", "localhost", "[::1]"].includes(url.hostname)
    || url.username || url.password) throw new Error("Calendar emulator requires HTTP loopback origins.");
}

async function json(response: APIResponse, label: string) {
  expect(response.status(), label + " must succeed (private body omitted).").toBe(200);
  return response.json();
}

async function release(page: Page, web: string): Promise<void> {
  const sha = process.env.CASEOPS_RELEASE_SHA ?? e2eEnv.CASEOPS_RELEASE_SHA;
  expect(sha).toMatch(/^[a-f0-9]{40}$/);
  for (const url of [apiBaseUrl + "/api/build", web + "/api/release-identity"]) {
    expect((await json(await page.request.get(url), "Release identity")).release_sha).toBe(sha);
  }
}

for (const width of [1280, 393]) {
  for (const provider of ["google", "outlook"] as const) {
    test(`CAL17 ${provider} refresh, event CRUD and revoked cleanup at ${width}px`,
      async ({ page, baseURL }) => {
        localOnly(apiBaseUrl);
        localOnly(baseURL!);
        const web = new URL(baseURL!).origin;
        await page.setViewportSize({ width, height: 900 });
        expect(await json(await page.request.get(emulator + "/health"), "Emulator admission"))
          .toEqual({ mode: "calendar-20261008", transport: "loopback-only" });
        await release(page, web);
        const slug = "cal17-" + randomUUID();
        const owner = slug + "@example.com";
        const password = "Synthetic!" + randomUUID();
        const actor = await json(await page.request.post(apiBaseUrl + "/api/bootstrap/company", {
          data: { company_name: "Offline Calendar acceptance", company_slug: slug,
            company_type: "law_firm", owner_full_name: "Calendar QA", owner_email: owner,
            owner_password: password },
        }), "Fresh isolated Calendar tenant");
        const headers = { ...noPaidProviderHeaders, Authorization: "Bearer " + actor.access_token };
        const configuration = provider === "google" ? {
          client_id: "caseops-calendar-browser-emulator", client_secret: "offline-calendar-browser-fixture-secret",
          calendar_redirect_uri: apiBaseUrl + "/api/calendar/connections/google-calendar/callback",
          gmail_redirect_uri: apiBaseUrl + "/api/mailbox/gmail/callback",
          drive_redirect_uri: apiBaseUrl + "/api/drive/google/callback",
          calendar_enabled: true, gmail_enabled: false, drive_enabled: false, enabled: true,
        } : {
          client_id: "caseops-calendar-browser-emulator", client_secret: "offline-calendar-browser-fixture-secret",
          tenant_id: "organizations", redirect_uri: apiBaseUrl + "/api/calendar/connections/outlook/callback",
          scopes: ["offline_access", "User.Read", "Calendars.ReadWrite"],
          oauth_consent_model_approved: true, scopes_approved: true, enabled: true,
        };
        await json(await page.request.patch(apiBaseUrl + "/api/admin/" + (
          provider === "google" ? "google-workspace-configuration" : "outlook-configuration"
        ), { headers, data: configuration }), "Offline-only provider configuration");

        await page.goto(web + "/sign-in");
        await page.locator("#company-slug").fill(slug);
        await page.locator("#email").fill(owner);
        await page.locator("#password").fill(password);
        await page.getByRole("button", { name: "Sign in", exact: true }).click();
        await page.waitForURL(/\/app(?:[/?]|$)/);
        await page.goto(web + "/app/calendar");
        const connect = page.getByTestId(`calendar-${provider}-connect`);
        await expect(connect).toBeEnabled();
        await connect.click();
        await page.waitForURL(new RegExp("/_e2e/calendar-oauth/(outlook/)?authorize\\?"));
        const attempt = await page.getByTestId("oauth-emulator-attempt").inputValue();
        await page.getByRole("button", { name: "Allow short-lived calendar access", exact: true }).click();
        await page.waitForURL(/\/app\/calendar$/);
        await expect(page.getByTestId(`calendar-${provider}-panel`)).toContainText("Connected as " + account);
        await page.reload();
        await expect(page.getByTestId(`calendar-${provider}-revoke`)).toBeVisible();

        const matter = await json(await page.request.post(apiBaseUrl + "/api/matters/", { headers,
          data: { matter_code: "CAL17-" + randomUUID(), title: "Offline calendar event",
            practice_area: "Commercial", forum_level: "high_court", court_name: "Delhi High Court",
            status: "intake" },
        }), "Calendar source Matter");
        const date = new Date(Date.now() + 7 * 86_400_000).toISOString().slice(0, 10);
        const hearing = await json(await page.request.post(`${apiBaseUrl}/api/matters/${matter.id}/hearings`, {
          headers, data: { hearing_on: date, forum_name: "Delhi High Court", purpose: "Synthetic calendar check",
            time_status: "time_not_published", timezone: "Asia/Kolkata" },
        }), "Calendar source hearing");
        const syncUrl = apiBaseUrl + "/api/calendar/sync/" + (
          provider === "google" ? "google-calendar/hearings/" : "hearings/"
        ) + hearing.id;
        const first = await json(await page.request.post(syncUrl, { headers }), "Initial event sync");
        expect(first.sync.sync_status).toBe("synced");
        const eventId = first.sync.provider_event_id;
        expect(eventId).toMatch(/^offline-event-[a-f0-9]{32}$/);
        const initial = await json(await page.request.get(emulator + "/evidence/" + attempt), "Provider evidence");
        expect(initial).toMatchObject({ token_calls: 1, refresh_calls: 1, event_calls: ["POST"] });
        expect(initial.events).toHaveLength(1);
        expect(initial.events[0].id).toBe(eventId);
        expect(initial.events[0].start).toEqual(provider === "google" ? { date } : {
          dateTime: date + "T00:00:00", timeZone: "India Standard Time",
        });

        const updated = await json(await page.request.post(syncUrl, { headers }), "Idempotent event update");
        expect(updated.sync.provider_event_id).toBe(eventId);
        await json(await page.request.patch(`${apiBaseUrl}/api/matters/${matter.id}/hearings/${hearing.id}`, {
          headers, data: { status: "cancelled" },
        }), "Canonical hearing cancellation");
        const deleted = await json(await page.request.get(emulator + "/evidence/" + attempt), "Deletion evidence");
        expect(deleted.refresh_calls).toBe(1);
        expect(deleted.event_calls).toEqual(["POST", "PATCH", "DELETE"]);
        expect(deleted.events).toEqual([]);

        const retained = await json(await page.request.post(`${apiBaseUrl}/api/matters/${matter.id}/hearings`, {
          headers, data: { hearing_on: date, forum_name: "Delhi High Court", purpose: "Revocation cleanup" },
        }), "Second explicit source");
        await json(await page.request.post(syncUrl.replace(hearing.id, retained.id), { headers }), "Second event sync");
        await page.reload();
        await expect(page.getByTestId(`calendar-${provider}-revoke`)).toBeVisible();
        await page.getByTestId(`calendar-${provider}-revoke`).click();
        await expect(connect).toBeVisible();
        const status = await json(await page.request.get(apiBaseUrl + "/api/calendar/sync-status", { headers }),
          "Readiness after real revocation");
        const kind = provider === "google" ? "google_calendar" : "outlook";
        expect(status.connections.find((row: { provider: string }) => row.provider === kind).status).toBe("revoked");
        expect(status.syncs.find((row: { source_id: string }) => row.source_id === retained.id).sync_status)
          .toBe("delete_pending");
        await page.reload();
        await expect(page.getByTestId("calendar-readiness-error")).toHaveCount(0);
        await expect(connect).toBeEnabled();
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1))
          .toBe(true);
        await release(page, web);
      });
  }
}
