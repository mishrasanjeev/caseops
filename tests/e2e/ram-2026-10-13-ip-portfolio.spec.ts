/** IP13-02..09 / UJ-02,UJ-04: source cells -> saved records -> responsive UI.
 * IP13-01's historical upload failure is not inferred from this synthetic file.
 */
import { randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import path from "node:path";
import type { APIRequestContext, Page } from "@playwright/test";
import JSZip from "jszip";

import { expect, test } from "./support/prod-diagnostic-test";
import { noPaidProviderHeaders } from "./support/cost-controls";

test.use({ extraHTTPHeaders: noPaidProviderHeaders, storageState: { cookies: [], origins: [] },
  trace: "off", screenshot: "off", video: "off" });
test.describe.configure({ retries: 0, mode: "serial" });

function required(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required; missing setup is not a skip.`);
  return value;
}
const loopback = (url: URL) => ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
function csv(rows: string[][]): Buffer {
  return Buffer.from(rows.map(row => row.map(value => `"${value.replaceAll('"', '""')}"`).join(",")).join("\r\n"));
}

async function nativeDateWorkbook(page: Page, mark: string): Promise<Buffer> {
  const zip = await JSZip.loadAsync(readFileSync(path.join(process.cwd(),
    "tests/e2e/fixtures/ip-portfolio-native-dates-20261013.xlsx")));
  const member = zip.file("xl/worksheets/sheet1.xml");
  if (!member) throw new Error("Pinned native-date fixture worksheet is missing.");
  const xml = await page.evaluate(({ source, mark }) => {
    const doc = new DOMParser().parseFromString(source, "application/xml");
    if (doc.querySelector("parsererror")) throw new Error("Native-date fixture XML is invalid.");
    const cell = doc.querySelector('c[r="A2"] is t');
    if (!cell || cell.textContent !== "Synthetic native Excel date preview") {
      throw new Error("Native-date fixture mark contract changed.");
    }
    cell.textContent = mark;
    return new XMLSerializer().serializeToString(doc);
  }, { source: await member.async("string"), mark });
  zip.file("xl/worksheets/sheet1.xml", xml);
  return zip.generateAsync({ type: "nodebuffer", compression: "DEFLATE" });
}
type ImportRow = {
  created_docket_id: string | null; commit_status: string; commit_error_code: string | null;
  normalized: Record<string, unknown>; reconciliation_decision: string | null;
};
type ImportResult = {
  job: { id: string; status: string; total_rows: number; committed_rows: number; failed_rows: number;
    preview_token: string | null }; rows: ImportRow[];
};

for (const width of [1280, 393]) {
  test(`source-tolerant portfolio import, duplicate skip and renewal alert at ${width}px`, async ({ page, request, baseURL }) => {
    test.setTimeout(180_000);
    const web = new URL(baseURL ?? required("CASEOPS_WEB_BASE_URL"));
    const api = new URL(process.env.PROD_API_BASE_URL ?? (loopback(web)
      ? `http://${web.hostname}:${process.env.CASEOPS_E2E_API_PORT ?? "8000"}`
      : required("PROD_API_BASE_URL")));
    if (web.username || web.password || api.username || api.password) throw new Error("Credential-bearing origins are forbidden.");
    if (loopback(web) !== loopback(api)) throw new Error("Mixed local/remote origins are forbidden before any request.");
    const local = loopback(web) && loopback(api);
    if (!local && (web.origin !== "https://caseops.ai" || api.origin !== "https://api.caseops.ai")) {
      throw new Error("Only canonical production origins may be used.");
    }
    const sha = local ? required("CASEOPS_RELEASE_SHA") : required("CASEOPS_EXPECTED_RELEASE_SHA");
    expect(sha).toMatch(/^[a-f0-9]{40}$/);
    const run = randomUUID();
    const credentials = local ? {
      slug: `ip13-${run}`, email: `owner-${run}@example.com`, password: `Portfolio!${randomUUID()}`,
    } : {
      slug: process.env.CASEOPS_RAM_PROD_SLUG ?? "test-legal",
      email: required("CASEOPS_RAM_PROD_EMAIL"),
      password: process.env.CASEOPS_RAM_PROD_PASSWORD?.trim() || required("CASEOPS_TEST_LEGAL_PROD_PASSWORD"),
    };
    if (!local && credentials.slug !== "test-legal") throw new Error("Production writes are test-legal only.");
    async function release(client: APIRequestContext) {
      for (const path of [`${api.origin}/api/build`, `${web.origin}/api/release-identity`]) {
        const response = await client.get(path, { headers: noPaidProviderHeaders });
        expect(response.status(), "exact serving API/web identity before authentication").toBe(200);
        expect((await response.json()).release_sha).toBe(sha);
      }
    }
    await release(request);
    if (local) {
      const bootstrap = await request.post(`${api.origin}/api/bootstrap/company`, {
        headers: noPaidProviderHeaders, data: {
          company_name: `Isolated IP import ${run}`, company_slug: credentials.slug,
          company_type: "law_firm", owner_full_name: "Isolated IP portfolio owner",
          owner_email: credentials.email, owner_password: credentials.password,
        },
      });
      expect(bootstrap.status(), await bootstrap.text()).toBe(200);
    }
    const login = await request.post(`${api.origin}/api/auth/login`, {
      headers: noPaidProviderHeaders,
      data: { company_slug: credentials.slug, email: credentials.email, password: credentials.password },
    });
    expect(login.status(), await login.text()).toBe(200);
    const actor = await login.json();
    expect(actor.company.slug).toBe(credentials.slug);
    const headers = { ...noPaidProviderHeaders, Authorization: `Bearer ${actor.access_token}` };
    await page.setViewportSize({ width, height: 900 });
    await page.goto(`${web.origin}/sign-in`);
    await page.locator("#company-slug").fill(credentials.slug);
    await page.locator("#email").fill(credentials.email);
    await page.locator("#password").fill(credentials.password);
    await page.getByRole("button", { name: /^Sign in$/ }).click();
    await page.waitForURL(/\/app(?:[/?]|$)/);
    // Actual Excel datetime cells, independently pinned to this synthetic fixture.
    const nativeName = `ip13-native-${run}.xlsx`;
    const nativeMark = `Synthetic native Excel date ${run}`;
    await page.goto(`${web.origin}/app/ip/portfolio/imports`);
    await page.getByLabel("CSV or XLSX file").setInputFiles({
      name: `ip13-invalid-${run}.xlsx`,
      mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      buffer: Buffer.from("isolated invalid spreadsheet bytes"),
    });
    const parserRejected = page.waitForResponse(response =>
      new URL(response.url()).pathname === "/api/ip/imports/upload"
      && response.request().method() === "POST");
    await page.getByRole("button", { name: "Validate file", exact: true }).click();
    const rejectedFile = await parserRejected;
    expect(rejectedFile.status(), await rejectedFile.text()).toBe(422);
    const safeProblem = await rejectedFile.json();
    expect(safeProblem.detail).toBe("The XLSX file could not be read.");
    expect(rejectedFile.headers()["access-control-allow-origin"]).toBe(web.origin);
    expect(rejectedFile.headers()["x-request-id"]).toBe(safeProblem.request_id);
    await expect(page.getByText("The XLSX file could not be read.", { exact: true })).toBeVisible();
    await page.getByLabel("CSV or XLSX file").setInputFiles({ name: nativeName,
      mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      buffer: await nativeDateWorkbook(page, nativeMark) });
    const nativeUploaded = page.waitForResponse(response => new URL(response.url()).pathname === "/api/ip/imports/upload" && response.request().method() === "POST");
    await page.getByRole("button", { name: "Validate file", exact: true }).click();
    const nativeResponse = await nativeUploaded;
    expect(nativeResponse.status(), await nativeResponse.text()).toBe(201);
    expect(nativeResponse.headers()["access-control-allow-origin"]).toBe(web.origin);
    const nativePreview = await nativeResponse.json() as ImportResult;
    expect(nativePreview.job.total_rows).toBe(1);
    expect(nativePreview.rows[0].normalized.application_date).toBe("2026-01-31");
    expect(nativePreview.rows[0].normalized.renewal_due_date).toBe("2035-03-31");
    expect(nativePreview.rows[0].normalized.class_numbers).toEqual([9, 36]);
    expect(nativePreview.rows[0].created_docket_id).toBeNull();
    await expect(page.getByRole("heading", { name: `Review ${nativeName}`, exact: true })).toBeVisible();
    await expect(page.getByText("2035-03-31", { exact: true })).toBeVisible();
    await page.reload();
    await page.getByRole("button", { name: new RegExp(nativeName.replace(".xlsx", "\\.xlsx")) }).click();
    await expect(page.getByRole("heading", { name: `Review ${nativeName}`, exact: true })).toBeVisible();
    await expect(page.getByText("2035-03-31", { exact: true })).toBeVisible();
    const retainedNative = await request.get(`${api.origin}/api/ip/imports/${nativePreview.job.id}`, { headers });
    expect(retainedNative.status()).toBe(200);
    expect((await retainedNative.json()).rows).toEqual(nativePreview.rows);
    const noNativeDocket = await request.get(`${api.origin}/api/ip/portfolio`, {
      headers, params: { query: nativeMark },
    });
    expect(noNativeDocket.status()).toBe(200);
    expect((await noNativeDocket.json()).rows).toHaveLength(0);
    const nativeCommitted = page.waitForResponse(response =>
      new URL(response.url()).pathname === `/api/ip/imports/${nativePreview.job.id}/commit`
      && response.request().method() === "POST");
    await page.getByRole("button", { name: "Commit to portfolio", exact: true }).click();
    const nativeCommit = await nativeCommitted;
    expect(nativeCommit.status(), await nativeCommit.text()).toBe(200);
    const nativeSaved = await nativeCommit.json() as ImportResult;
    expect(nativeSaved.job.committed_rows).toBe(1);
    expect(nativeSaved.job.failed_rows).toBe(0);
    expect(nativeSaved.rows[0].commit_status).toBe("committed");
    expect(nativeSaved.rows[0].created_docket_id).toBeTruthy();
    const nativeRecord = await request.get(
      `${api.origin}/api/ip/dockets/${nativeSaved.rows[0].created_docket_id}`, { headers });
    expect(nativeRecord.status()).toBe(200);
    const nativeDocket = await nativeRecord.json();
    expect(nativeDocket.title).toBe(nativeMark);
    expect(nativeDocket.status).toBe("draft");
    expect(nativeDocket.current_particulars.representation_json.portfolio_import.application_date)
      .toBe("2026-01-31");
    expect(nativeDocket.current_particulars.representation_json.portfolio_import.renewal_due_date)
      .toBe("2035-03-31");
    expect(nativeDocket.current_particulars.classes_json.map((item: { class_number: number }) => item.class_number))
      .toEqual([9, 36]);
    await page.reload();
    await page.getByRole("button", { name: new RegExp(nativeName.replace(".xlsx", "\\.xlsx")) }).click();
    await expect(page.getByText(/1 created; 0 linked; 0 skipped/)).toBeVisible();
    await page.goto(`${web.origin}/app/ip/portfolio`);
    await page.getByPlaceholder("Mark, application number, opposition number").fill(nativeMark);
    await page.getByRole("button", { name: "Search portfolio", exact: true }).click();
    await expect(page.getByRole("link", { name: nativeMark, exact: true })).toBeVisible();
    const nativePortfolioRow = (width >= 768 ? page.getByRole("row") : page.getByRole("article"))
      .filter({ has: page.getByRole("link", { name: nativeMark, exact: true }) });
    await expect(nativePortfolioRow.getByText("2035-03-31", { exact: true })).toBeVisible();
    await page.goto(`${web.origin}/app/ip/portfolio/imports`);
    await page.getByLabel("CSV or XLSX file").setInputFiles({
      name: `ip13-native-separate-${run}.xlsx`,
      mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      buffer: await nativeDateWorkbook(page, nativeMark),
    });
    const duplicateNativeResponse = page.waitForResponse(response =>
      new URL(response.url()).pathname === "/api/ip/imports/upload"
      && response.request().method() === "POST");
    await page.getByRole("button", { name: "Validate file", exact: true }).click();
    const duplicateNative = await duplicateNativeResponse;
    expect(duplicateNative.status(), await duplicateNative.text()).toBe(201);
    const duplicateNativePreview = await duplicateNative.json() as ImportResult;
    expect(duplicateNativePreview.rows[0].reconciliation_decision).toBe("skip");
    await page.getByLabel("Decision for row 1").click();
    await page.getByRole("option", { name: "Create separate record", exact: true }).click();
    const reconciledNativeResponse = page.waitForResponse(response =>
      new URL(response.url()).pathname === `/api/ip/imports/${duplicateNativePreview.job.id}/reconcile`);
    await page.getByRole("button", { name: "Save duplicate decisions", exact: true }).click();
    const reconciledNative = await reconciledNativeResponse;
    expect(reconciledNative.status(), await reconciledNative.text()).toBe(200);
    const separateNativeResponse = page.waitForResponse(response =>
      new URL(response.url()).pathname === `/api/ip/imports/${duplicateNativePreview.job.id}/commit`
      && response.request().method() === "POST");
    await page.getByRole("button", { name: "Commit to portfolio", exact: true }).click();
    const separateNative = await separateNativeResponse;
    expect(separateNative.status(), await separateNative.text()).toBe(200);
    const separateSaved = await separateNative.json() as ImportResult;
    expect(separateSaved.job.committed_rows).toBe(1);
    expect(separateSaved.job.failed_rows).toBe(0);
    expect(separateSaved.rows[0].created_docket_id).toBeTruthy();
    expect(separateSaved.rows[0].created_docket_id).not.toBe(nativeSaved.rows[0].created_docket_id);
    const mark = `IP source ${run}`;
    const number = `IP13/${run}`;
    const due = `${new Date().getUTCFullYear() + 3}-03-31`;
    const sourceHeaders = ["S.No.", "Trademark", "Trademark Image", "Application Date", "Renewal Due Date",
      "Applicant Name(s)", "Class", "Application No.", "Status", "Comment", "Takeover request",
      "Name Change request", "Address Change request", "Internal Remarks", "Jurisdiction", "Office", "Extra column"];
    const positive = ["source-1", mark, "logo-source-reference", "31/01/2026", due,
      "Source Owner One; Source Owner Two", "9, 36, and 42", number, "Registered", "Original source comment",
      "Pending", "N.A.", "No", "private import remark", "IN", "IP India", "extra source evidence"];
    const separate = [...positive]; separate[0] = "source-3"; separate[7] = `${number}-B`;
    const warning = [...positive]; warning[0] = "source-4"; warning[1] = `${mark} optional`;
    warning[3] = "invalid optional date"; warning[4] = "NA"; warning[5] = "N/A";
    warning[6] = "N.A."; warning[7] = `${number}-C`;
    const content = csv([sourceHeaders, positive, positive, separate, warning, Array(17).fill("")]);
    await page.goto(`${web.origin}/app/ip/portfolio/imports`);
    await expect(page.getByRole("heading", { name: "Trademark portfolio import", exact: true })).toBeVisible();
    await page.getByLabel("CSV or XLSX file").setInputFiles({ name: `ip13-${run}.csv`, mimeType: "text/csv", buffer: content });
    const uploaded = page.waitForResponse(response => new URL(response.url()).pathname === "/api/ip/imports/upload" && response.request().method() === "POST");
    await page.getByRole("button", { name: "Validate file", exact: true }).click();
    const upload = await uploaded;
    expect(upload.status(), await upload.text()).toBe(201);
    expect(upload.request().headers()["x-caseops-automated-test"]).toBe("no-paid-providers");
    const preview = await upload.json() as ImportResult;
    expect(preview.job.total_rows).toBe(5);
    expect(preview.rows[1].reconciliation_decision).toBe("skip");
    expect(preview.rows[0].normalized.class_numbers).toEqual([9, 36, 42]);
    expect(preview.rows.every(row => row.created_docket_id === null)).toBe(true);
    const before = await request.get(`${api.origin}/api/ip/portfolio`, { headers, params: { query: number } });
    expect(before.status()).toBe(200);
    expect((await before.json()).rows).toHaveLength(0);
    await expect(page.getByRole("heading", { name: `Review ip13-${run}.csv`, exact: true })).toBeVisible();
    await page.getByLabel("Decision for row 2").click();
    await expect(page.getByRole("option", { name: "Create separate record", exact: true })).toHaveCount(0);
    await page.getByRole("option", { name: "Skip row", exact: true }).click();
    await page.getByText("Source column mapping", { exact: true }).click();
    await expect(page.getByText("Applicant Name(s): applicant_name (canonical)", { exact: true })).toBeVisible();
    await expect(page.getByText("Extra column: Unmapped (unmapped)", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Commit to portfolio", exact: true })).toBeEnabled();
    const committed = page.waitForResponse(response => new URL(response.url()).pathname === `/api/ip/imports/${preview.job.id}/commit`);
    await page.getByRole("button", { name: "Commit to portfolio", exact: true }).click();
    const commit = await committed;
    expect(commit.status(), await commit.text()).toBe(200);
    const saved = await commit.json() as ImportResult;
    expect(saved.job.status).toBe("committed");
    expect(saved.job.committed_rows).toBe(3);
    expect(saved.job.failed_rows).toBe(0);
    expect(saved.rows.map(row => row.commit_status)).toEqual(["committed", "skipped", "committed", "committed", "skipped"]);
    expect(saved.rows[1].commit_error_code).toBe("duplicate_skipped");
    const committedKey = await page.evaluate(jobId =>
      sessionStorage.getItem(`ip-import-commit:${jobId}`), preview.job.id);
    expect(committedKey).toBeTruthy();
    const explicitReplay = await request.post(`${api.origin}/api/ip/imports/${preview.job.id}/commit`, {
      headers, data: { preview_token: preview.job.preview_token, idempotency_key: committedKey },
    });
    expect(explicitReplay.status(), await explicitReplay.text()).toBe(200);
    const replayed = await explicitReplay.json();
    expect(replayed.replayed).toBe(true);
    expect(replayed.rows).toEqual(saved.rows);
    await expect(page.getByText(/3 created; 0 linked; 2 skipped \(1 duplicates\); .*0 failed\./)).toBeVisible();
    await page.reload();
    await page.getByRole("button", { name: new RegExp(`ip13-${run}\\.csv`) }).click();
    await expect(page.getByRole("heading", { name: `Review ip13-${run}.csv`, exact: true })).toBeVisible();
    const persisted = await request.get(`${api.origin}/api/ip/imports/${preview.job.id}`, { headers });
    expect(persisted.status()).toBe(200);
    expect((await persisted.json()).rows).toEqual(saved.rows);
    for (const row of saved.rows.filter(row => row.created_docket_id)) {
      const record = await request.get(`${api.origin}/api/ip/dockets/${row.created_docket_id}`, { headers });
      expect(record.status()).toBe(200);
      const docket = await record.json();
      expect(docket.status).toBe("draft");
      expect(docket.current_particulars.readiness_status).toBe("incomplete");
      expect(recordText(docket)).not.toContain("private import remark");
      if (row.normalized.application_number === `${number}-C`) {
        expect(docket.current_particulars.parties_json).toEqual([]);
        expect(docket.current_particulars.classes_json).toEqual([]);
      } else {
        expect(docket.current_particulars.classes_json.map((scope: { class_number: number }) => scope.class_number)).toEqual([9, 36, 42]);
        expect(docket.current_particulars.classes_json.every((scope: { specification: string }) => scope.specification === "")).toBe(true);
        expect(docket.current_particulars.representation_json.portfolio_import.renewal_due_date).toBe(due);
      }
    }
    await page.goto(`${web.origin}/app/ip/portfolio`);
    await page.getByPlaceholder("Mark, application number, opposition number").fill(number);
    await page.getByRole("button", { name: "Search portfolio", exact: true }).click();
    await expect(page.getByRole("link", { name: mark, exact: true })).toHaveCount(2);
    const sourceRow = (width >= 768 ? page.getByRole("row") : page.getByRole("article"))
      .filter({ has: page.getByText(number, { exact: true }) });
    await expect(sourceRow.getByText(due, { exact: true })).toBeVisible();
    await expect(sourceRow.getByText("Alert: queued", { exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
    await page.getByRole("link", { name: mark, exact: true }).first().click();
    await expect(page).toHaveURL(/\/app\/ip\?docket=/);
    await expect(page.getByRole("heading", { name: mark, exact: true })).toBeVisible();
    const docketId = saved.rows[0].created_docket_id;
    expect(docketId).toBeTruthy();
    await page.goto(`${web.origin}/app/ip/portfolio/imports`);
    await page.getByRole("button", { name: new RegExp(`ip13-${run}\\.csv`) }).click();
    const importedRow = page.getByRole("row")
      .filter({ has: page.getByText(number, { exact: true }) })
      .filter({ has: page.getByRole("button", { name: "Edit source renewal date", exact: true }) });
    const correctedDue = `${new Date().getUTCFullYear() + 3}-04-30`;
    for (const nextDue of [correctedDue, null]) {
      await importedRow.getByRole("button", { name: "Edit source renewal date", exact: true }).click();
      const editor = page.getByRole("dialog", { name: "Correct source renewal date" });
      await expect(editor).toBeVisible();
      await expect(editor.getByLabel("Renewal due date")).toHaveValue(nextDue ? due : correctedDue);
      if (nextDue) await editor.getByLabel("Renewal due date").fill(nextDue);
      else await editor.getByRole("button", { name: "Clear date", exact: true }).click();
      await editor.getByLabel("Correction reason").fill(nextDue ? "Synthetic source date correction" : "Synthetic source date withdrawn");
      const updated = page.waitForResponse(response => new URL(response.url()).pathname ===
        `/api/ip/dockets/${docketId}/portfolio-renewal-date` && response.request().method() === "PATCH");
      await editor.getByRole("button", { name: "Save source date", exact: true }).click();
      const update = await updated;
      expect(update.status(), await update.text()).toBe(200);
      await expect(editor).not.toBeVisible();
      const current = await request.get(`${api.origin}/api/ip/dockets/${docketId}`, { headers });
      expect(current.status()).toBe(200);
      expect((await current.json()).current_particulars.representation_json.portfolio_import.renewal_due_date).toBe(nextDue);
      const portfolio = await request.get(`${api.origin}/api/ip/portfolio`, { headers, params: { query: number } });
      expect(portfolio.status()).toBe(200);
      const currentRow = (await portfolio.json()).rows.find((row: { docket_id: string }) => row.docket_id === docketId);
      expect(currentRow.source_renewal_due_on).toBe(nextDue);
      expect(currentRow.source_renewal_alert_status).toBe(nextDue ? "queued" : null);
      await page.reload();
      await page.getByRole("button", { name: new RegExp(`ip13-${run}\\.csv`) }).click();
    }
    const immutableSource = await request.get(`${api.origin}/api/ip/imports/${preview.job.id}`, { headers });
    expect((await immutableSource.json()).rows).toEqual(saved.rows);
    await page.goto(`${web.origin}/app/ip/portfolio`);
    await page.getByPlaceholder("Mark, application number, opposition number").fill(number);
    await page.getByRole("button", { name: "Search portfolio", exact: true }).click();
    await expect(sourceRow.getByText(due, { exact: true })).toHaveCount(0);
    await expect(sourceRow.getByText("Alert: queued", { exact: true })).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
    if (local) await test.info().attach(`ip-import-${width}px`, { body: await page.screenshot(), contentType: "image/png" });
    await release(request);
  });
}

function recordText(value: unknown): string { return JSON.stringify(value); }
