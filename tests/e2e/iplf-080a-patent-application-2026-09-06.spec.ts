import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { expect, test, type Page } from "@playwright/test";
import { apiBaseUrl, patentRunId, patentScreenshot } from "./support/patent-acceptance";
import { noPaidProviderHeaders } from "./support/cost-controls";
import { assertPatentControlsFit as assertControlsFit } from "./support/patent-layout";
import {
  bootstrapPatentTenant, enablePatentWorkspace,
  signInPatentTenant,
} from "./support/patent-acceptance";

test.use({ extraHTTPHeaders: noPaidProviderHeaders });

// UJ-29 / PAT-01 / IPLF-080-FAMILY: source facts never infer prosecution completion.
async function lifecycle(page: Page, evidence: string, effectiveAt: string, backdated = false) {
  await page.getByRole("tab", { name: "Lifecycle", exact: true }).click();
  await page.getByLabel("Effective date and time", { exact: true }).fill(effectiveAt);
  await page.getByLabel("Reason", { exact: true }).fill("Explicit client instruction for this application only.");
  await page.getByLabel("Outcome", { exact: true }).fill("client instruction recorded");
  await page.getByLabel("Instruction or evidence reference", { exact: true }).fill(evidence);
  await page.getByRole("button", { name: "Preview lifecycle change" }).click();
  await expect(page.getByRole("button", { name: "Confirm lifecycle change" })).toBeDisabled();
  if (backdated) await page.getByLabel("Reviewed exception: backdated recalculation review required", { exact: true }).check();
  await page.getByLabel("I confirm this lifecycle change and its recorded impacts.").check();
  await assertControlsFit(page);
  await page.getByRole("button", { name: "Confirm lifecycle change" }).click();
  await expect(page.getByRole("list", { name: "Lifecycle events" })).toContainText(evidence);
}

for (const width of [393, 768, 1280]) {
  test(`IPLF-080 independent application, identifiers, evidence and lifecycle at ${width}px`, async ({ page, playwright }, testInfo) => {
    const run = patentRunId();
    const tenant = await bootstrapPatentTenant(page.request);
    const headers = { ...await enablePatentWorkspace(page.request, tenant), ...noPaidProviderHeaders };
    const client = await page.request.post(`${apiBaseUrl}/api/clients`, {
      headers, data: { name: `Application journey client ${run}`, client_type: "corporate" },
    });
    expect(client.status(), await client.text()).toBe(200);
    const familyResponse = await page.request.post(`${apiBaseUrl}/api/ip/patents/families`, {
      headers: { ...headers, "Idempotency-Key": crypto.randomUUID() }, data: {
        title: `Independent application family ${run}`, client_id: (await client.json()).id,
        disclosure_date: "2026-09-05", disclosure_narrative: "Unpublished invention disclosure.",
      },
    });
    expect(familyResponse.status(), await familyResponse.text()).toBe(201);
    const family = await familyResponse.json();
    const taxonomy = await page.request.post(`${apiBaseUrl}/api/ip/document-taxonomy/seed`, { headers });
    expect(taxonomy.status(), await taxonomy.text()).toBe(200);
    await signInPatentTenant(page, tenant);
    await page.setViewportSize({ width, height: 900 });
    // The API returned the authoritative family identity. Do not assume a
    // bounded, UUID-ordered list page contains a newly-created record.
    await page.goto(`/app/ip/patents/${family.id}`);
    await page.getByRole("tab", { name: "Documents", exact: true }).click();
    const bytes = Buffer.from(`Original application number and filing evidence. ${run} `.repeat(30));
    await page.getByLabel("Original file", { exact: true }).setInputFiles({
      name: "application-source.txt", mimeType: "text/plain", buffer: bytes,
    });
    await page.getByLabel("Title", { exact: true }).fill("Original application source");
    await page.getByLabel("Invention", { exact: true }).fill("Substrate");
    await page.getByRole("button", { name: "Preview controlled name" }).click();
    await expect(page.getByText("Controlled name preview", { exact: true })).toBeVisible();
    const uploadPromise = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/ip/documents/upload" && response.request().method() === "POST");
    await page.getByRole("button", { name: "Upload reviewed document" }).click();
    const upload = await uploadPromise;
    expect(upload.status(), await upload.text()).toBe(200);
    const uploaded = await upload.json();
    expect(uploaded.outcome).toBe("created");
    const document = uploaded.document;
    expect(document).not.toBeNull();
    const source = { kind: "document_version", document_id: document.id,
      document_version_id: document.versions[0].id, content_sha256: document.versions[0].sha256_hex };
    await page.getByRole("tab", { name: "Applications", exact: true }).click();
    await page.getByRole("button", { name: "New application" }).click();
    await page.getByLabel("Application title", { exact: true }).fill("Independent sourced application");
    await page.getByLabel("Application kind", { exact: true }).selectOption("complete");
    await page.getByLabel("Jurisdiction code", { exact: true }).fill("IN");
    await page.getByLabel("Office", { exact: true }).fill("IP India");
    await page.getByLabel("Recorded filing date", { exact: true }).fill("2026-09-05");
    await page.getByLabel("Application source version", { exact: true }).selectOption(source.document_version_id);
    await expect(page.getByLabel("Application number pending allocation", { exact: true })).toBeChecked();
    await assertControlsFit(page);
    await page.getByRole("button", { name: "Create application" }).click();
    await page.waitForURL(/\/app\/ip\/patents\/applications\/[a-f0-9-]{36}$/);
    const applicationId = page.url().split("/").at(-1)!;
    const applicationUrl = page.url();
    const endpoint = `${apiBaseUrl}/api/ip/patents/applications/${applicationId}`;
    const originalResponse = await page.request.get(endpoint, { headers });
    expect(originalResponse.status(), await originalResponse.text()).toBe(200);
    const original = await originalResponse.json();
    expect(original.docket_id).not.toBe(family.docket_id);
    expect(original.facts.source).toEqual(source);
    expect(original.prosecution_phase).toBe("disclosure");
    expect(original.facts.source_pending_identifier_allocation).toBe(true);
    await page.reload();
    await page.getByRole("button", { name: "Edit application" }).click();
    const rawNumber = `  IN/2026-${run}-A  `;
    const publicationNumber = `Publication-${run}`;
    const grantNumber = `Grant-${run}`;
    for (const [index, kind, value] of [[1, "application", rawNumber], [2, "publication", publicationNumber], [3, "grant", grantNumber]] as const) {
      await page.getByRole("button", { name: "Add identifier" }).click();
      await page.getByLabel(`Identifier ${index} kind`, { exact: true }).selectOption(kind);
      await page.getByLabel(`Identifier ${index} value`, { exact: true }).fill(value);
      await expect(page.getByLabel(`Identifier ${index} source version`, { exact: true })).toHaveValue(source.document_version_id);
    }
    await expect(page.getByLabel("Application number pending allocation", { exact: true })).not.toBeChecked();
    await expect(page.getByLabel("Application number pending allocation", { exact: true })).toBeDisabled();
    await page.getByLabel("Correction reason").fill("Transcribe the three source-published identifiers.");
    if (width === 1280) {
      for (const boundary of [639, 640, 641, 767, 768, 769, 1023, 1024, 1025]) {
        await page.setViewportSize({ width: boundary, height: 900 });
        await assertControlsFit(page);
      }
      await page.setViewportSize({ width, height: 900 });
    }
    await assertControlsFit(page);
    await patentScreenshot(page, testInfo, `patent-application-editor-${width}.png`);
    await page.getByRole("button", { name: "Save application correction" }).click();
    await expect(page.getByRole("button", { name: "Edit application" })).toBeVisible();
    await page.reload();
    const currentResponse = await page.request.get(endpoint, { headers });
    expect(currentResponse.status(), await currentResponse.text()).toBe(200);
    const current = await currentResponse.json();
    expect(current.version).toBe(2);
    expect(current.prosecution_phase).toBe("disclosure");
    expect(current.facts.identifiers.map((row: { raw_value: string }) => row.raw_value)).toEqual([rawNumber, publicationNumber, grantNumber]);
    expect(current.facts.identifiers.every((row: { source: unknown }) => JSON.stringify(row.source) === JSON.stringify(source))).toBe(true);
    const stale = await page.request.post(`${endpoint}/corrections`, { headers, data: {
      expected_version: original.version, expected_lifecycle_version: original.lifecycle_version,
      reason: "Stale application correction regression.", facts: original.facts,
    } });
    expect(stale.status(), await stale.text()).toBe(409);
    await page.getByLabel("Version", { exact: true }).fill("1");
    await page.getByRole("button", { name: "Open version" }).click();
    await expect(page.getByRole("region", { name: "Application facts" })).toContainText("Application number pending allocation");
    await expect(page.getByRole("button", { name: "Edit application" })).toHaveCount(0);
    await page.getByRole("button", { name: "Current version" }).click();
    const downloadPromise = page.waitForEvent("download");
    await page.getByRole("list", { name: "Application identifiers" }).getByRole("button", { name: "Download source version" }).first().click();
    const download = await downloadPromise;
    const downloadedPath = testInfo.outputPath("application-original-source.txt");
    await download.saveAs(downloadedPath);
    expect(createHash("sha256").update(await readFile(downloadedPath)).digest("hex")).toBe(source.content_sha256);
    expect(createHash("sha256").update(bytes).digest("hex")).toBe(source.content_sha256);

    await page.getByRole("link", { name: "Patent family", exact: true }).click();
    await page.getByRole("tab", { name: "Applications", exact: true }).click();
    await page.getByLabel("Title or exact identifier").fill(rawNumber.trim().toLowerCase());
    await page.getByRole("button", { name: "Search patent applications" }).click();
    await expect(page.getByRole("link", { name: current.facts.title, exact: true })).toBeVisible();
    await page.getByRole("button", { name: "New application" }).click();
    await page.getByLabel("Application title", { exact: true }).fill("Duplicate must not be admitted");
    await page.getByLabel("Jurisdiction code", { exact: true }).fill("IN");
    await page.getByLabel("Office", { exact: true }).fill("  ip   INDIA  ");
    await page.getByLabel("Application source version", { exact: true }).selectOption(source.document_version_id);
    await page.getByRole("button", { name: "Add identifier" }).click();
    await page.getByLabel("Identifier 1 value", { exact: true }).fill(rawNumber.trim().toLowerCase());
    await page.getByRole("button", { name: "Create application" }).click();
    await expect(page.getByRole("form", { name: "New patent application", exact: true })
      .getByRole("alert")).toContainText("already uses this identifier");
    await page.getByRole("button", { name: "Cancel", exact: true }).click();
    const siblingResponse = await page.request.post(`${apiBaseUrl}/api/ip/patents/applications`, {
      headers: { ...headers, "Idempotency-Key": crypto.randomUUID() }, data: {
        family_id: family.id, expected_family_version: family.version, expected_family_lifecycle_version: family.lifecycle_version,
        facts: { ...original.facts, title: "Independent sibling application" },
      },
    });
    expect(siblingResponse.status(), await siblingResponse.text()).toBe(201);
    let sibling = await siblingResponse.json();
    const otherApi = await playwright.request.newContext({ extraHTTPHeaders: noPaidProviderHeaders });
    try {
      const other = await bootstrapPatentTenant(otherApi, true);
      for (const suffix of ["", "/versions/1", "/lifecycle-history"]) {
        const denied = await otherApi.get(endpoint + suffix, { headers: { Authorization: `Bearer ${other.access_token}` } });
        expect(denied.status()).toBe(404);
      }
    } finally { await otherApi.dispose(); }
    await page.goto(applicationUrl);
    await lifecycle(page, "local-fixture:application-close", "2026-09-06T10:00");
    await page.reload();
    await expect(page.getByRole("button", { name: "Edit application" })).toHaveCount(0);
    await page.getByRole("tab", { name: "Documents", exact: true }).click();
    await expect(page.getByRole("button", { name: "Upload reviewed document" })).toHaveCount(0);
    const terminal = await page.request.post(`${endpoint}/corrections`, { headers, data: {
      expected_version: current.version, expected_lifecycle_version: 1,
      reason: "Closed application must reject changes.", facts: current.facts,
    } });
    expect(terminal.status()).toBe(404);
    await page.goto(`/app/ip/patents/applications/${sibling.id}`);
    await page.getByRole("button", { name: "Edit application" }).click();
    await page.getByLabel("Application title", { exact: true }).fill("Independent sibling corrected");
    await page.getByLabel("Correction reason").fill("The closed sibling does not disable this active application.");
    await page.getByRole("button", { name: "Save application correction" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Independent sibling corrected" })).toBeVisible();
    await page.reload();
    const siblingCorrection = await page.request.get(`${apiBaseUrl}/api/ip/patents/applications/${sibling.id}`, { headers });
    expect(siblingCorrection.status(), await siblingCorrection.text()).toBe(200);
    sibling = await siblingCorrection.json();
    expect(sibling.version).toBe(2);
    expect(sibling.is_active).toBe(true);
    await page.goto(applicationUrl);
    await lifecycle(page, "local-fixture:application-reopen", "2026-09-06T10:01");
    await page.reload();
    await expect(page.getByRole("button", { name: "Edit application" })).toBeVisible();
    await lifecycle(page, "local-fixture:application-final-close", "2026-09-06T09:59", true);
    await patentScreenshot(page, testInfo, `patent-application-lifecycle-${width}.png`);
    const history = await page.request.get(`${endpoint}/lifecycle-history`, { headers });
    expect(history.status(), await history.text()).toBe(200);
    expect((await history.json()).events.map((row: { to_status: string }) => row.to_status)).toEqual(["closed", "ready", "closed"]);
    const final = await page.request.get(endpoint, { headers });
    expect((await final.json()).facts).toEqual(current.facts);
    expect((await final.json()).lifecycle_version).toBe(3);
    expect((await final.json()).is_active).toBe(false);
    const retainedFamily = await page.request.get(`${apiBaseUrl}/api/ip/patents/families/${family.id}`, { headers });
    expect(await retainedFamily.json()).toEqual(family);
    const retainedSibling = await page.request.get(`${apiBaseUrl}/api/ip/patents/applications/${sibling.id}`, { headers });
    expect(await retainedSibling.json()).toEqual(sibling);
    await page.reload();
    await expect(page.getByRole("button", { name: "Edit application" })).toHaveCount(0);
    await assertControlsFit(page);
  });
}
