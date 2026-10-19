/** IP15-018: real tenant source-date filters, saved views, continuation and CSV. */
import { createHash } from "node:crypto";
import type { APIRequestContext, APIResponse, Locator, Page } from "@playwright/test";

import { expect, test } from "./support/prod-diagnostic-test";
import { localTransportHeaders } from "./support/cost-controls";
import { prepareIp15Workspace, type Ip15Workspace } from "./support/ip15-workspace";

test.use({ extraHTTPHeaders: async ({ baseURL }, use) => {
  if (!baseURL) throw new Error("IP15 requires a configured baseURL.");
  await use(localTransportHeaders(baseURL));
}, storageState: { cookies: [], origins: [] },
  trace: "off", screenshot: "off", video: "off" });
test.describe.configure({ retries: 0, mode: "default" });

type SourceRow = { created_docket_id: string | null; commit_status: string };
type ImportResult = { job: { id: string; status: string; version: number; source_sha256: string;
  preview_token: string | null; total_rows: number; valid_rows: number; committed_rows: number;
  failed_rows: number; commit_batch_size: number }; rows: SourceRow[] };
type TrackerPage = { rows: Array<{ docket_id: string; source_application_state: string;
  source_renewal_state: string }>; counts: Record<string, number>; next_cursor: string | null };

async function json<T>(response: APIResponse, expected = 200): Promise<T> {
  expect(response.status(), "IP18 request rejected; private response and credentials are not logged.").toBe(expected);
  return response.json() as Promise<T>;
}

async function sourceFixture(workspace: Ip15Workspace, request: APIRequestContext) {
  const prefix = `IP18 ${workspace.run}`;
  const names = Array.from({ length: 51 }, (_, index) => `${prefix} missing ${String(index).padStart(2, "0")}`);
  const due = new Date(Date.now() + 60 * 86_400_000).toISOString().slice(0, 10);
  const dueName = `${prefix} due`;
  const text = ["Trademark,Application Date,Renewal Date", ...names.map(name => `${name},2020-01-15,`),
    `${prefix} outside,2010-01-15,`, `${dueName},2020-01-15,${due}`].join("\r\n") + "\r\n";
  const bytes = Buffer.from(text);
  const sourceHash = createHash("sha256").update(bytes).digest("hex");
  const preview = await json<ImportResult>(await request.post(`${workspace.api.origin}/api/ip/imports/upload`, {
    headers: workspace.headers,
    multipart: { file: { name: `ip18-${workspace.run}.csv`, mimeType: "text/csv", buffer: bytes } },
  }), 201);
  expect(preview.job.source_sha256).toBe(sourceHash);
  expect(preview.job.valid_rows).toBe(53);
  expect(preview.job.total_rows).toBe(53);
  const firstResponse = await request.post(`${workspace.api.origin}/api/ip/imports/${preview.job.id}/commit`, {
    headers: workspace.headers, data: { preview_token: preview.job.preview_token, idempotency_key: `ip18-${workspace.run}` },
  });
  const first = await json<ImportResult>(firstResponse, 202);
  expect(first.job.committed_rows).toBe(50);
  expect(first.job.failed_rows).toBe(0);
  expect(first.job.commit_batch_size).toBe(50);
  expect(first.job.source_sha256).toBe(sourceHash);
  const final = await json<ImportResult>(await request.post(`${workspace.api.origin}/api/ip/imports/${preview.job.id}/resume`, {
    headers: workspace.headers, data: { expected_job_version: first.job.version, preview_token: first.job.preview_token },
  }));
  expect(final.job.version).toBeGreaterThan(first.job.version);
  expect(final.job.status).toBe("committed");
  expect(final.job.committed_rows).toBe(53);
  expect(final.job.failed_rows).toBe(0);
  expect(final.job.source_sha256).toBe(sourceHash);
  expect(final.rows.every(row => row.commit_status === "committed" && row.created_docket_id)).toBe(true);
  expect(new Set(final.rows.map(row => row.created_docket_id)).size).toBe(53);
  return { prefix, names, dueName, due, missingIds: final.rows.slice(0, 51).map(row => row.created_docket_id as string) };
}

async function select(page: Page, name: string, option: string) {
  const control = page.getByRole("combobox", { name, exact: true });
  await expect(control).toHaveCount(1);
  await control.click();
  await page.getByRole("option", { name: option, exact: true }).click();
}

async function docketIds(region: Locator) {
  return region.locator('a[href^="/app/ip?docket="]').evaluateAll(links =>
    links.map(link => new URL((link as HTMLAnchorElement).href).searchParams.get("docket")));
}

for (const width of [1280, 393]) {
  test(`IP18 current-source tracker filters saved views export and full continuation at ${width}px`,
    async ({ page, request, baseURL }) => {
      test.setTimeout(240_000);
      const workspace = await prepareIp15Workspace(page, request, baseURL, width);
      const fixture = await sourceFixture(workspace, request);
      await page.goto(`${workspace.web.origin}/app/ip/portfolio`);
      const columns = page.getByRole("button", { name: "Choose portfolio columns", exact: true });
      await columns.click();
      const menu = page.getByRole("menu");
      const labels = menu.locator("label");
      expect(await labels.count()).toBeGreaterThanOrEqual(3);
      for (const label of await labels.all()) {
        const name = (await label.innerText()).trim();
        const checkbox = label.getByRole("checkbox");
        if (["Mark", "Application Date", "Renewal Due Date"].includes(name)) await checkbox.check();
        else await checkbox.uncheck();
      }
      await page.keyboard.press("Escape");
      await expect(menu).toHaveCount(0);
      await page.getByRole("button", { name: "Deadline tracker view", exact: true }).click();
      const tracker = page.getByRole("region", { name: "Deadline tracker", exact: true });
      await tracker.getByRole("textbox", { name: "Search renewal tracker", exact: true }).fill(fixture.prefix);
      await tracker.getByRole("button", { name: "Search renewal tracker", exact: true }).click();
      await tracker.getByLabel("Application Date from", { exact: true }).fill("2020-01-01");
      await tracker.getByLabel("Application Date to", { exact: true }).fill("2020-12-31");
      await select(page, "Renewal tracker category", "Missing Renewal Date");
      await expect(tracker.locator("tbody tr")).toHaveCount(50);
      await tracker.getByRole("button", { name: "Load more renewal records", exact: true }).click();
      await expect(tracker.locator("tbody tr")).toHaveCount(51);
      expect((await docketIds(tracker)).sort()).toEqual([...fixture.missingIds].sort());
      await expect(tracker.getByRole("button", { name: "Load more renewal records" })).toHaveCount(0);
      await expect(tracker.getByText("Verified", { exact: true })).toHaveCount(0);
      const filters = { query: fixture.prefix, application_date_from: "2020-01-01",
        application_date_to: "2020-12-31", renewal_tracker_state: ["missing"] };
      const apiPage = await json<TrackerPage>(await request.get(`${workspace.api.origin}/api/ip/portfolio/renewal-tracker`, {
        headers: workspace.headers, params: { query: fixture.prefix, application_date_from: "2020-01-01",
          application_date_to: "2020-12-31", category: "missing", limit: 50 },
      }));
      expect(apiPage.rows).toHaveLength(50);
      expect(apiPage.next_cursor).toBeTruthy();
      expect(apiPage.counts.missing).toBe(51);
      expect(apiPage.rows.every(row => row.source_application_state === "imported_unverified"
        && row.source_renewal_state === "missing")).toBe(true);
      await page.getByRole("button", { name: "Family view", exact: true }).click();
      const families = page.getByRole("region", { name: "Application families", exact: true });
      await expect(families.locator('[data-testid^="ip-family-"]')).toHaveCount(25);
      for (const count of [50, 51]) {
        await families.getByRole("button", { name: "Load more families", exact: true }).click();
        await expect(families.locator('[data-testid^="ip-family-"]')).toHaveCount(count);
      }
      expect((await docketIds(families)).sort()).toEqual([...fixture.missingIds].sort());
      await expect(families.getByRole("button", { name: "Load more families", exact: true })).toHaveCount(0);
      await page.getByRole("button", { name: "Deadline tracker view", exact: true }).click();
      await expect(tracker.getByRole("textbox", { name: "Search renewal tracker", exact: true })).toHaveValue(fixture.prefix);
      await expect(tracker.getByLabel("Application Date from", { exact: true })).toHaveValue("2020-01-01");
      await expect(tracker.getByLabel("Application Date to", { exact: true })).toHaveValue("2020-12-31");
      const viewName = `IP18 dates ${workspace.run}`;
      await page.getByRole("button", { name: "Save view", exact: true }).click();
      const dialog = page.getByRole("dialog", { name: "Save current view", exact: true });
      await dialog.getByLabel("View name", { exact: true }).fill(viewName);
      const saved = page.waitForResponse(response => new URL(response.url()).pathname === "/api/ip/portfolio/views"
        && response.request().method() === "POST");
      await dialog.getByRole("button", { name: "Save", exact: true }).click();
      const savedResponse = await saved;
      expect(savedResponse.status()).toBe(201);
      const savedView = await savedResponse.json();
      expect(savedView.filters).toMatchObject(filters);
      expect(savedView.columns).toEqual(["mark", "application_date", "renewal_due_date"]);
      await expect(dialog).toHaveCount(0);
      await tracker.getByRole("textbox", { name: "Search renewal tracker", exact: true }).fill("IP18 deliberately no matching source");
      await tracker.getByRole("button", { name: "Search renewal tracker", exact: true }).click();
      await expect(tracker.getByText("No matching renewal records", { exact: true })).toBeVisible();
      await page.reload();
      await page.getByRole("button", { name: "Deadline tracker view", exact: true }).click();
      await select(page, "Saved view", viewName);
      await expect(tracker.getByRole("textbox", { name: "Search renewal tracker", exact: true })).toHaveValue(fixture.prefix);
      await expect(tracker.getByLabel("Application Date from", { exact: true })).toHaveValue("2020-01-01");
      await expect(tracker.locator("tbody tr")).toHaveCount(50);
      await tracker.getByRole("button", { name: "Load more renewal records", exact: true }).click();
      await expect(tracker.locator("tbody tr")).toHaveCount(51);
      expect((await docketIds(tracker)).sort()).toEqual([...fixture.missingIds].sort());
      const previewed = page.waitForResponse(response => new URL(response.url()).pathname === "/api/ip/portfolio/exports/preview"
        && response.request().method() === "POST");
      await page.getByRole("button", { name: "Export", exact: true }).click();
      const previewResponse = await previewed;
      expect(previewResponse.status()).toBe(200);
      const preview = await previewResponse.json();
      expect(preview.row_count).toBe(51);
      expect(preview.truncated).toBe(false);
      const exportDialog = page.getByRole("dialog", { name: "Confirm portfolio export", exact: true });
      await expect(exportDialog).toContainText("51 accessible records");
      const queued = page.waitForResponse(response => new URL(response.url()).pathname === "/api/ip/portfolio/exports"
        && response.request().method() === "POST");
      await exportDialog.getByRole("button", { name: "Queue export", exact: true }).click();
      const queuedResponse = await queued;
      expect(queuedResponse.status()).toBe(202);
      const exportJob = await queuedResponse.json();
      await expect.poll(async () => (await json<{ status: string }>(await request.get(
        `${workspace.api.origin}/api/ip/portfolio/exports/${exportJob.id}`, { headers: workspace.headers }))).status).toBe("completed");
      const csv = await request.get(`${workspace.api.origin}/api/ip/portfolio/exports/${exportJob.id}/download`, { headers: workspace.headers });
      expect(csv.status()).toBe(200);
      expect(csv.headers()["cache-control"]).toBe("private, no-store");
      const lines = (await csv.text()).replace(/^\uFEFF/, "").trim().split(/\r?\n/);
      expect(lines[0]).toBe("Mark,Application Date,Renewal Due Date");
      // All controlled fixture cells exclude commas/newlines, so compare exact CSV records.
      expect(lines.slice(1).sort()).toEqual(fixture.names.map(name => `${name},2020-01-15,`).sort());
      await expect(exportDialog).toHaveCount(0);
      await select(page, "Renewal tracker category", "Upcoming Renewals");
      await tracker.getByLabel("Renewal Due Date from", { exact: true }).fill(fixture.due);
      await tracker.getByLabel("Renewal Due Date to", { exact: true }).fill(fixture.due);
      await expect(tracker.locator("tbody tr")).toHaveCount(1);
      await expect(tracker.getByRole("link", { name: fixture.dueName, exact: true })).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1)).toBe(true);
      await workspace.release();
    });
}
