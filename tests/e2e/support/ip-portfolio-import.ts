/**
 * The trademark portfolio import, driven through its own page: the product's
 * bulk path for creating IP records. Specs use it to build local populations
 * (never raw database writes). An import job cannot be retired, so production
 * specs must not call it.
 */
import { expect, type Page } from "@playwright/test";

import { json, type TesterRuntime } from "./ram-bugs4";

export type ImportRow = {
  id: string; row_number: number; created_docket_id: string | null; duplicate_candidates: unknown[];
};
export type ImportPreview = {
  job: { id: string; status: string; total_rows: number; committed_rows: number }; rows: ImportRow[];
};

export function csv(rows: string[][]): Buffer {
  return Buffer.from(rows.map(row => row.map(value => `"${value.replaceAll('"', '""')}"`).join(",")).join("\r\n"));
}

/** Uploads a CSV (header row first) through the import page; returns the preview the page received. */
export async function uploadImportThroughUi(
  page: Page, rt: TesterRuntime, name: string, rows: string[][],
): Promise<ImportPreview> {
  expect(rt.local, "A portfolio import job cannot be retired; imports are local-only").toBe(true);
  await page.goto(`${rt.web.origin}/app/ip/portfolio/imports`);
  await expect(page.getByRole("heading", { name: "Trademark portfolio import", exact: true })).toBeVisible();
  await page.getByLabel("CSV or XLSX file").setInputFiles({ name, mimeType: "text/csv", buffer: csv(rows) });
  const uploaded = page.waitForResponse(response => new URL(response.url()).pathname === "/api/ip/imports/upload"
    && response.request().method() === "POST");
  await page.getByRole("button", { name: "Validate file", exact: true }).click();
  const preview = await json<ImportPreview>(await uploaded, "Validate the portfolio file", 201);
  expect(preview.job.total_rows).toBe(rows.length - 1);
  return preview;
}

/** Commits the shown preview through the page and waits until the server has committed every batch. */
export async function commitImportThroughUi(
  page: Page, rt: TesterRuntime, jobId: string, expectedRows: number,
): Promise<ImportPreview> {
  const commit = page.getByRole("button", { name: "Commit to portfolio", exact: true });
  await expect(commit).toBeEnabled();
  await commit.click();
  let finished: ImportPreview | undefined;
  await expect.poll(async () => {
    finished = await json<ImportPreview>(await page.request.get(`${rt.api.origin}/api/ip/imports/${jobId}`,
      { headers: rt.headers }), "Read the import job");
    return finished.job.status;
  }, { timeout: 180_000, message: "the import commits every batch" }).toBe("committed");
  expect(finished!.job.committed_rows).toBe(expectedRows);
  await expect(page.locator("main").getByText(/\d+ created; \d+ linked; \d+ skipped/)).toBeVisible({ timeout: 30_000 });
  return finished!;
}
