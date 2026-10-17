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
        const kind = provider === "google" ? "google_calendar" : "outlook";
        const statusUrl = apiBaseUrl + "/api/calendar/sync-status";
        const connected = await json(await page.request.get(statusUrl, { headers }), "Connected Calendar identity");
        expect(connected.connections).toHaveLength(1);
        const connection = connected.connections[0];
        expect(connection.id).toEqual(expect.any(String));
        expect(connection.id).not.toBe("");
        expect(connection).toMatchObject({ company_id: actor.company.id, membership_id: actor.membership.id,
          provider: kind, status: "connected", display_email: account });

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
        expect(first.sync.id).toEqual(expect.any(String));
        expect(first.sync.id).not.toBe("");
        const syncIdentity = { id: first.sync.id, company_id: actor.company.id,
          calendar_connection_id: connection.id, source_type: "matter_hearing", source_id: hearing.id,
          provider_event_id: eventId };
        expect(first.sync).toMatchObject(syncIdentity);
        const readRetainedSync = async (label: string) => {
          const current = await json(await page.request.get(statusUrl, { headers }), label);
          expect(current.connections).toEqual([expect.objectContaining({ id: connection.id,
            company_id: actor.company.id, membership_id: actor.membership.id, provider: kind, status: "connected" })]);
          expect(current.syncs).toHaveLength(1);
          expect(current.syncs[0]).toMatchObject(syncIdentity);
          return current.syncs[0];
        };
        const initial = await json(await page.request.get(emulator + "/evidence/" + attempt), "Provider evidence");
        expect(initial).toMatchObject({ token_calls: 1, refresh_calls: 1, event_calls: ["POST"] });
        expect(initial.events).toHaveLength(1);
        expect(initial.events[0].id).toBe(eventId);
        expect(initial.events[0].start).toEqual(provider === "google" ? { date } : {
          dateTime: date + "T00:00:00", timeZone: "India Standard Time",
        });

        const updated = await json(await page.request.post(syncUrl, { headers }), "Idempotent event update");
        expect(updated.sync).toMatchObject({ ...syncIdentity, sync_status: "synced" });
        const cancelled = await json(await page.request.patch(`${apiBaseUrl}/api/matters/${matter.id}/hearings/${hearing.id}`, {
          headers, data: { status: "cancelled" },
        }), "Canonical hearing cancellation");
        expect(cancelled).toMatchObject({ id: hearing.id, matter_id: matter.id, status: "cancelled" });
        // Matter cancellation commits a tombstone; provider I/O belongs to the later drain.
        expect(await readRetainedSync("Queued cancellation identity")).toMatchObject({
          sync_status: "delete_pending", dead_letter_reason: "hearing_cancelled_delete" });
        const queued = await json(await page.request.get(emulator + "/evidence/" + attempt), "Queued provider evidence");
        expect(queued.refresh_calls).toBe(1);
        expect(queued.event_calls).toEqual(["POST", "PATCH"]);
        expect(queued.events.map((row: { id: string }) => row.id)).toEqual([eventId]);
        const replayUrl = apiBaseUrl + "/api/admin/" + (
          provider === "google" ? "google-calendar" : "outlook"
        ) + "-sync/replay";
        if (provider === "outlook") {
          const readiness = await json(await page.request.get(apiBaseUrl + "/api/admin/outlook-configuration", {
            headers,
          }), "Outlook durable policy before cleanup drain");
          expect(readiness).toMatchObject({ configured: true, enabled: true, last_test_status: "not_run",
            adp20_readiness: "blocked_pending_admin_configuration", missing_config_names: [], missing_approval_keys: [] });
        }
        const expectedReplay = { provider: kind, status: provider === "outlook" ? "blocked" : "processed",
          adp20_readiness: provider === "outlook" ? "blocked_pending_admin_configuration" : "ready_for_adp20_implementation",
          missing_config_names: [], missing_approval_keys: [], failed: 0, retry_scheduled: 0, dead_lettered: 0 };
        const drained = await json(await page.request.post(replayUrl, { headers, data: { limit: 1 } }),
          "Bounded cancellation drain");
        expect(drained).toMatchObject(expectedReplay);
        const deletedSync = await readRetainedSync("Retained deleted cancellation identity");
        expect(deletedSync).toMatchObject({ sync_status: "deleted", last_error: null,
          next_attempt_at: null, dead_letter_reason: null });
        const deleted = await json(await page.request.get(emulator + "/evidence/" + attempt), "Deletion evidence");
        expect(deleted.token_calls).toBe(1);
        expect(deleted.refresh_calls).toBe(1);
        expect(deleted.event_calls).toEqual(["POST", "PATCH", "DELETE"]);
        expect(deleted.events).toEqual([]);
        const replayed = await json(await page.request.post(replayUrl, { headers, data: { limit: 1 } }),
          "Idempotent cancellation drain");
        expect(replayed).toMatchObject(expectedReplay);
        expect(await readRetainedSync("Deleted identity after second drain")).toEqual(deletedSync);
        expect(await json(await page.request.get(emulator + "/evidence/" + attempt), "Second drain evidence"))
          .toEqual(deleted);

        const retained = await json(await page.request.post(`${apiBaseUrl}/api/matters/${matter.id}/hearings`, {
          headers, data: { hearing_on: date, forum_name: "Delhi High Court", purpose: "Revocation cleanup" },
        }), "Second explicit source");
        const retainedSync = await json(await page.request.post(syncUrl.replace(hearing.id, retained.id), { headers }),
          "Second event sync");
        expect(retainedSync.sync.id).toEqual(expect.any(String));
        expect(retainedSync.sync.id).not.toBe("");
        expect(retainedSync.sync.id).not.toBe(syncIdentity.id);
        expect(retainedSync.sync.provider_event_id).toMatch(/^offline-event-[a-f0-9]{32}$/);
        expect(retainedSync.sync.provider_event_id).not.toBe(eventId);
        const retainedIdentity = { id: retainedSync.sync.id, company_id: actor.company.id,
          calendar_connection_id: connection.id, source_type: "matter_hearing", source_id: retained.id,
          provider_event_id: retainedSync.sync.provider_event_id };
        expect(retainedSync.sync).toMatchObject({ ...retainedIdentity, sync_status: "synced" });
        await page.reload();
        await expect(page.getByTestId(`calendar-${provider}-revoke`)).toBeVisible();
        await page.getByTestId(`calendar-${provider}-revoke`).click();
        await expect(connect).toBeVisible();
        const status = await json(await page.request.get(statusUrl, { headers }),
          "Readiness after real revocation");
        expect(status.connections).toEqual([expect.objectContaining({ id: connection.id,
          company_id: actor.company.id, membership_id: actor.membership.id, provider: kind, status: "revoked" })]);
        expect(status.syncs).toHaveLength(2);
        expect(status.syncs.find((row: { id: string }) => row.id === syncIdentity.id))
          .toMatchObject(syncIdentity);
        expect(status.syncs.find((row: { id: string }) => row.id === retainedIdentity.id))
          .toMatchObject({ ...retainedIdentity, sync_status: "delete_pending" });
        await page.reload();
        await expect(page.getByTestId("calendar-readiness-error")).toHaveCount(0);
        await expect(connect).toBeEnabled();
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1))
          .toBe(true);
        await release(page, web);
      });
  }
}
