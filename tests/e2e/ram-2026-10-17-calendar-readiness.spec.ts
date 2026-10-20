/** CAL13-04: actual backend readiness must survive retained cleanup states. */
import { expect, test } from "./support/prod-diagnostic-test";
import { localTransportHeaders } from "./support/cost-controls";
import { prepareIp15Workspace } from "./support/ip15-workspace";

test.use({ extraHTTPHeaders: async ({ baseURL }, use) => {
  if (!baseURL) throw new Error("IP15 requires a configured baseURL.");
  await use(localTransportHeaders(baseURL));
}, storageState: { cookies: [], origins: [] },
  trace: "off", screenshot: "off", video: "off" });
test.describe.configure({ retries: 0, mode: "default" });

for (const width of [1280, 393]) {
  test(`CAL17 actual Calendar readiness and retained cleanup remain truthful at ${width}px`,
    async ({ page, request, baseURL }) => {
      const workspace = await prepareIp15Workspace(page, request, baseURL, width);
      try {
        const response = await request.get(`${workspace.api.origin}/api/calendar/sync-status`, {
          headers: workspace.headers,
        });
        expect(response.status(), "Calendar readiness must return the current authorized contract.").toBe(200);
        const status = await response.json();
        const config = status.provider_config.find((row: { provider: string }) => row.provider === "google_calendar");
        expect(config, "The current API must explicitly classify Google readiness.").toBeTruthy();
        const connected = status.connections.some((row: { provider: string; status: string }) =>
          row.provider === "google_calendar" && row.status === "connected");
        const recognized = new Set(["pending", "synced", "failed", "retry_scheduled", "dead_letter", "deleted", "delete_pending"]);
        expect(status.syncs.every((row: { sync_status: string }) => recognized.has(row.sync_status))).toBe(true);
        test.info().annotations.push({ type: "calendar-readiness",
          description: `configured=${config.configured};connected=${connected};pending_cleanup=${status.syncs.filter((row: { sync_status: string }) => row.sync_status === "delete_pending").length};provider_writes=0` });

        await page.goto(`${workspace.web.origin}/app/calendar`);
        const panel = page.getByTestId("calendar-google-panel");
        await expect(panel).toBeVisible();
        await expect(panel.getByText("Checking Google Calendar readiness...")).toHaveCount(0);
        await expect(page.getByTestId("calendar-readiness-error")).toHaveCount(0);
        if (config.configured) {
          await expect(panel.getByText(/Google Calendar OAuth is not configured/)).toHaveCount(0);
          await expect(panel.getByText(/Missing Google config/)).toHaveCount(0);
          await expect(panel.getByText("Google Calendar readiness is unavailable.")).toHaveCount(0);
          await expect(connected ? page.getByTestId("calendar-google-sync-range")
            : page.getByTestId("calendar-google-connect")).toBeEnabled();
        } else {
          await expect(panel.getByText(/Google Calendar OAuth is not configured/)).toBeVisible();
          await expect(page.getByTestId("calendar-google-connect")).toBeDisabled();
          for (const name of config.missing_config_names) {
            await expect(panel.getByTestId("calendar-google-provider-config-status")).toContainText(name);
          }
        }
        await expect(page.getByTestId("calendar-ics-download")).toBeVisible();
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1)).toBe(true);
        if (workspace.local) {
          const paths = new Set(["/api/calendar/sync-status", "/api/calendar/connections", "/api/mailbox/gmail/status"]);
          const affectedRead = (url: URL) => url.origin === workspace.api.origin && paths.has(url.pathname);
          const failed = new Set<string>();
          await page.route(affectedRead, async route => {
            if (route.request().method() !== "GET") return route.continue();
            failed.add(new URL(route.request().url()).pathname);
            await route.abort("failed");
          });
          await page.reload();
          for (const id of ["calendar-readiness-error", "calendar-outlook-readiness-error", "calendar-gmail-readiness-error"]) {
            await expect(page.getByTestId(id)).toBeVisible();
          }
          expect([...failed].sort()).toEqual([...paths].sort());
          await expect(page.getByText(/Google Calendar OAuth is not configured|Gmail OAuth is not configured|Missing Google config|Missing Gmail config/)).toHaveCount(0);
          await expect(page.getByTestId("calendar-google-connect")).toBeDisabled();
          await expect(page.getByTestId("calendar-outlook-connect")).toBeDisabled();
          await expect(page.getByTestId("calendar-gmail-connect")).toBeDisabled();
          await expect(page.getByTestId("calendar-ics-download")).toBeVisible();
          await page.unroute(affectedRead);
          for (const id of ["calendar-readiness-error", "calendar-outlook-readiness-error", "calendar-gmail-readiness-error"]) {
            await page.getByTestId(id).getByRole("button", { name: "Try again", exact: true }).click();
            await expect(page.getByTestId(id)).toHaveCount(0);
          }
          if (config.configured) {
            await expect(connected ? page.getByTestId("calendar-google-sync-range")
              : page.getByTestId("calendar-google-connect")).toBeEnabled();
          }
        }
      } finally {
        await workspace.release();
      }
    });
}
