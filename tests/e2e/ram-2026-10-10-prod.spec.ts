import { createHash, randomUUID } from "node:crypto";
import type { APIRequestContext } from "@playwright/test";

import { expect, test } from "./support/prod-diagnostic-test";
import { noPaidProviderHeaders } from "./support/cost-controls";
import { apiBaseUrl } from "./support/env";
import { runDocumentWorkerOnce } from "./support/helpers";

test.use({ extraHTTPHeaders: noPaidProviderHeaders, storageState: { cookies: [], origins: [] },
  trace: "off", screenshot: "off", video: "off" });
test.describe.configure({ retries: 0 });
test.setTimeout(300_000);

type Attachment = {
  id: string; sha256_hex: string; processing_status: string; extracted_char_count: number;
  latest_job: { id: string; status: string; action: string; processed_char_count: number;
    attempt_count: number; error_message: string | null };
};
const required = (name: string) => {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required; missing setup is not a skip.`);
  return value;
};
const loopback = (url: URL) => ["127.0.0.1", "localhost", "[::1]"].includes(url.hostname);

for (const target of ["matter", "contract"] as const) {
  for (const width of [1280, 393]) {
    test.describe(`${target} retained index at ${width}px`, () => {
      test.use({ viewport: { width, height: 900 }, isMobile: width === 393, hasTouch: width === 393 });
      test("upload and two distinct reindexes complete without losing bytes after reload", async ({ page, request, baseURL }) => {
        if (!baseURL) throw new Error("Use the standard app, Docker or exact-release production config.");
        const web = new URL(baseURL);
        const local = loopback(web);
        const api = new URL(local ? apiBaseUrl : required("PROD_API_BASE_URL"));
        if (local !== loopback(api)) throw new Error("Mixed live/local endpoints are forbidden.");
        if (!local && (web.origin !== "https://caseops.ai" || api.origin !== "https://api.caseops.ai")) {
          throw new Error("Only canonical production origins are authorized.");
        }
        const sha = local ? required("CASEOPS_RELEASE_SHA") : required("CASEOPS_EXPECTED_RELEASE_SHA");
        expect(sha).toMatch(/^[a-f0-9]{40}$/);
        async function release(client: APIRequestContext) {
          for (const endpoint of [`${api.origin}/api/build`, `${web.origin}/api/release-identity`]) {
            const response = await client.get(endpoint, { headers: noPaidProviderHeaders });
            expect(response.status(), "exact serving release readback").toBe(200);
            expect((await response.json()).release_sha).toBe(sha);
          }
        }
        await release(request);
        const run = randomUUID().slice(0, 8);
        const credentials = local
          ? { slug: `document-index-${run}`, email: `owner-${run}@example.com`, password: `Index!${randomUUID()}` }
          : { slug: required("CASEOPS_NOTICE_QA_SLUG"), email: required("CASEOPS_NOTICE_OWNER_EMAIL"),
              password: required("CASEOPS_NOTICE_OWNER_PASSWORD") };
        if (!local && !["test-legal", "caseops-qa"].includes(credentials.slug)) {
          throw new Error("Only authorized QA tenants may be mutated, never GBA or another real tenant.");
        }
        if (local) {
          const response = await request.post(`${api.origin}/api/bootstrap/company`, {
            headers: noPaidProviderHeaders,
            data: { company_name: `Index acceptance ${run}`, company_slug: credentials.slug,
              company_type: "law_firm", owner_full_name: "Index acceptance owner",
              owner_email: credentials.email, owner_password: credentials.password },
          });
          expect(response.status(), "loopback-only fixture bootstrap").toBe(200);
        }
        const login = await request.post(`${api.origin}/api/auth/login`, { headers: noPaidProviderHeaders,
          data: { company_slug: credentials.slug, email: credentials.email, password: credentials.password } });
        expect(login.status(), "authenticate existing production or local QA actor").toBe(200);
        const identity = await login.json();
        expect(identity.company.slug).toBe(credentials.slug);
        const headers = { ...noPaidProviderHeaders, Authorization: `Bearer ${identity.access_token}` };
        await page.goto("/sign-in");
        await page.locator("#company-slug").fill(credentials.slug);
        await page.locator("#email").fill(credentials.email);
        await page.locator("#password").fill(credentials.password);
        await page.getByRole("button", { name: /^Sign in$/ }).click();
        await page.waitForURL(/\/app(?:[/?]|$)/);
        const collection = target === "matter" ? "matters" : "contracts";
        const title = `Index retention QA ${target} ${run}`;
        await release(request);
        const created = await request.post(`${api.origin}/api/${collection}/`, { headers,
          data: target === "matter"
            ? { title, matter_code: `IDX-${run}`, practice_area: "Civil", forum_level: "high_court", status: "intake" }
            : { title, contract_code: `IDX-${run}`, contract_type: "agreement", status: "under_review" } });
        expect(created.status(), "create this run's unique QA parent").toBe(200);
        const parentId = (await created.json()).id as string;
        const parentPath = `/api/${collection}/${parentId}`;
        await page.goto(`/app/${collection}/${parentId}${target === "matter" ? "/documents" : ""}`);
        if (target === "contract") await page.getByRole("tab", { name: /^Attachments/ }).click();
        const filename = `retained-index-${run}.txt`;
        const body = `Synthetic ${target} index acceptance ${run}. No real legal instruction. `.repeat(40).trim();
        const digest = createHash("sha256").update(body).digest("hex");
        const uploading = page.waitForResponse(response => new URL(response.url()).pathname === `${parentPath}/attachments`
          && response.request().method() === "POST");
        await release(request);
        await page.getByTestId(`${target}-attachment-${target === "matter" ? "file-input" : "input"}`)
          .setInputFiles({ name: filename, mimeType: "text/plain", buffer: Buffer.from(body) });
        if (target === "matter") await page.getByTestId("matter-attachment-upload").click();
        const uploaded = await uploading;
        expect(uploaded.status(), "original upload, without retry").toBe(200);
        expect(uploaded.request().headers()["x-caseops-automated-test"]).toBe("no-paid-providers");
        let attachment = await uploaded.json() as Attachment;
        const attachmentId = attachment.id;
        const jobIds = new Set<string>();
        async function complete(jobId: string, action: string) {
          expect(jobIds.has(jobId), "each command must admit a distinct durable job").toBe(false);
          jobIds.add(jobId);
          if (local) await runDocumentWorkerOnce();
          const deadline = Date.now() + 90_000;
          while (Date.now() < deadline) {
            const workspace = await request.get(`${api.origin}${parentPath}/workspace`, { headers });
            expect(workspace.status(), "read retained index through the authorized workspace").toBe(200);
            const found = (await workspace.json()).attachments.find((row: Attachment) => row.id === attachmentId) as Attachment | undefined;
            expect(found, "uploaded source must remain present").toBeDefined();
            attachment = found!;
            expect(attachment.latest_job.id).toBe(jobId);
            expect(attachment.latest_job.action).toBe(action);
            if (attachment.latest_job.status === "failed") throw new Error(`Index job failed: ${attachment.latest_job.error_message}`);
            if (attachment.latest_job.status === "completed") {
              expect(attachment).toMatchObject({ processing_status: "indexed", sha256_hex: digest,
                extracted_char_count: body.length });
              expect(attachment.latest_job).toMatchObject({ processed_char_count: body.length,
                error_message: null, attempt_count: 1 });
              return;
            }
            expect(["queued", "processing"]).toContain(attachment.latest_job.status);
            await page.waitForTimeout(1500);
          }
          throw new Error("Durable index did not complete within the 90-second acceptance budget.");
        }
        await complete(attachment.latest_job.id, "initial_index");
        for (let iteration = 0; iteration < 2; iteration++) {
          await page.reload();
          if (target === "contract") await page.getByRole("tab", { name: /^Attachments/ }).click();
          const row = page.getByRole(target === "matter" ? "row" : "listitem").filter({ hasText: filename });
          await expect(row).toBeVisible();
          await expect(row.getByText("Indexed", { exact: true })).toBeVisible();
          await release(request);
          if (target === "matter") {
            const responsePromise = page.waitForResponse(response => new URL(response.url()).pathname === `${parentPath}/attachments/${attachmentId}/reindex`
              && response.request().method() === "POST");
            const button = page.getByTestId(`matter-attachment-reindex-${attachmentId}`);
            await expect(button).toBeVisible();
            await expect(button).toBeEnabled();
            await button.scrollIntoViewIfNeeded();
            const box = await button.boundingBox();
            expect(box!.width).toBeGreaterThan(24);
            expect(box!.x).toBeGreaterThanOrEqual(0);
            expect(box!.x + box!.width).toBeLessThanOrEqual(width + 1);
            await button.click();
            const response = await responsePromise;
            expect(response.status(), "original browser reindex, without retry").toBe(200);
            attachment = await response.json() as Attachment;
          } else {
            // Contract currently exposes reindex through its public API, not a
            // browser control. Prove that boundary and the visible workspace.
            const response = await request.post(`${api.origin}${parentPath}/attachments/${attachmentId}/reindex`, { headers });
            expect(response.status(), "original public Contract reindex, without retry").toBe(200);
            attachment = await response.json() as Attachment;
          }
          await complete(attachment.latest_job.id, "reindex");
        }
        expect(jobIds.size).toBe(3);
        await page.reload();
        if (target === "contract") await page.getByRole("tab", { name: /^Attachments/ }).click();
        const finalRow = page.getByRole(target === "matter" ? "row" : "listitem").filter({ hasText: filename });
        await expect(finalRow).toBeVisible();
        await expect(finalRow.getByText("Indexed", { exact: true })).toBeVisible();
        const downloaded = await request.get(`${api.origin}${parentPath}/attachments/${attachmentId}/download`, { headers });
        expect(downloaded.status(), "authorized immutable original bytes").toBe(200);
        expect(await downloaded.body()).toEqual(Buffer.from(body));
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
        await release(request);
      });
    });
  }
}
