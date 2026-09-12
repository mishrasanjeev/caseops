import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { expect, test } from "@playwright/test";
import { apiBaseUrl, patentRunId, patentScreenshot } from "./support/patent-acceptance";
import { noPaidProviderHeaders } from "./support/cost-controls";
import { assertPatentControlsFit as assertControlsFit } from "./support/patent-layout";
import {
  bootstrapPatentTenant, enablePatentWorkspace,
  signInPatentTenant,
} from "./support/patent-acceptance";

test.use({ extraHTTPHeaders: noPaidProviderHeaders });

// UJ-29 / PAT-01: restricted family intake; not prosecution or maintenance acceptance.

for (const width of [393, 768, 1280]) {
  test(`IPLF-080 family disclosure, immutable source and closure at ${width}px`, async ({ page, playwright }, testInfo) => {
    const run = patentRunId();
    const tenant = await bootstrapPatentTenant(page.request);
    const headers = { ...await enablePatentWorkspace(page.request, tenant), ...noPaidProviderHeaders };
    const client = await page.request.post(`${apiBaseUrl}/api/clients`, {
      headers, data: { name: `Patent journey client ${run}`, client_type: "corporate" },
    });
    expect(client.status(), await client.text()).toBe(200);
    const taxonomy = await page.request.post(`${apiBaseUrl}/api/ip/document-taxonomy/seed`, { headers });
    expect(taxonomy.status(), await taxonomy.text()).toBe(200);
    await signInPatentTenant(page, tenant);
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/app/ip");
    await page.getByRole("link", { name: "Patent disclosures", exact: true }).click();
    await page.getByRole("button", { name: "New disclosure" }).click();
    await page.getByLabel("Invention title", { exact: true }).fill(`Restricted substrate invention ${run}`);
    await page.getByLabel("Client", { exact: true }).selectOption({ label: `Patent journey client ${run}` });
    await page.getByLabel("Disclosure date", { exact: true }).fill("2026-09-05");
    await page.getByLabel("Invention disclosure", { exact: true }).fill("Original inventor disclosure with unpublished technical details.");
    await assertControlsFit(page);
    await page.getByRole("button", { name: "Create disclosure" }).click();
    await page.waitForURL(/\/app\/ip\/patents\/[a-f0-9-]{36}$/);
    const familyId = page.url().split("/").at(-1)!;
    const originalResponse = await page.request.get(`${apiBaseUrl}/api/ip/patents/families/${familyId}`, { headers });
    expect(originalResponse.status(), await originalResponse.text()).toBe(200);
    const original = await originalResponse.json();
    expect(original.facts.confidentiality).toBe("restricted");
    const access = await page.request.get(`${apiBaseUrl}/api/ip/dockets/${original.docket_id}/access`, { headers });
    expect(access.status(), await access.text()).toBe(200);
    const publication = await page.request.post(`${apiBaseUrl}/api/ip/dockets/${original.docket_id}/access/preview`, {
      headers, data: { action: "set_restricted", restricted: false,
        expected_access_policy_version: (await access.json()).access_policy_version,
        reason: "General visibility must not publish an invention disclosure." },
    });
    expect(publication.status(), await publication.text()).toBe(409);
    await page.getByRole("button", { name: "Edit disclosure" }).click();
    await page.getByLabel("Invention title", { exact: true }).fill(`Corrected substrate invention ${run}`);
    await page.getByLabel("Correction reason").fill("Correct inventor title transcription.");
    await page.getByRole("button", { name: "Save correction" }).click();
    await expect(page.getByRole("heading", { name: `Corrected substrate invention ${run}`, level: 1 })).toBeVisible();
    await page.reload();
    await expect(page.getByRole("heading", { name: `Corrected substrate invention ${run}`, level: 1 })).toBeVisible();
    await page.getByLabel("Version", { exact: true }).fill("1");
    await page.getByRole("button", { name: "Open version" }).click();
    await expect(page.getByRole("region", { name: "Disclosure facts" })).toContainText(`Restricted substrate invention ${run}`);
    await page.getByRole("button", { name: "Current version" }).click();
    const stale = await page.request.post(`${apiBaseUrl}/api/ip/patents/families/${familyId}/corrections`, {
      headers, data: { expected_version: original.version, expected_lifecycle_version: original.lifecycle_version,
        reason: "Deliberate stale-write regression.", facts: original.facts },
    });
    expect(stale.status(), await stale.text()).toBe(409);

    await page.getByRole("tab", { name: "Documents", exact: true }).click();
    const bytes = Buffer.from(`Original invention source with unpublished process steps. ${run} `.repeat(30));
    await page.getByLabel("Original file", { exact: true }).setInputFiles({
      name: "inventor-original.txt", mimeType: "text/plain", buffer: bytes,
    });
    await page.getByLabel("Title", { exact: true }).fill("Inventor original source");
    await page.getByLabel("Invention", { exact: true }).fill("Substrate");
    await expect(page.getByLabel("Confidentiality", { exact: true })).toHaveValue("restricted");
    await page.getByRole("button", { name: "Preview controlled name" }).click();
    await expect(page.getByText("Controlled name preview", { exact: true })).toBeVisible();
    await assertControlsFit(page);
    const uploadResult = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/ip/documents/upload" && response.request().method() === "POST");
    await page.getByRole("button", { name: "Upload reviewed document" }).click();
    const uploadedResponse = await uploadResult;
    expect(uploadedResponse.status(), await uploadedResponse.text()).toBe(200);
    const uploaded = await uploadedResponse.json();
    const document = uploaded.document;
    expect(uploaded.outcome).toBe("created");
    expect(document).not.toBeNull();
    expect(document.versions[0].display_name).toContain("Patent");
    expect(document.versions[0].display_name).not.toContain("Trademark");
    await page.getByRole("tab", { name: "Disclosure", exact: true }).click();
    await page.getByRole("button", { name: "Edit disclosure" }).click();
    await page.getByLabel("Source document version").selectOption(document.versions[0].id);
    await page.getByLabel("Correction reason").fill("Pin the original inventor document.");
    await page.getByRole("button", { name: "Save correction" }).click();
    await expect(page.getByRole("button", { name: "Download source version" })).toBeVisible();
    await page.reload();
    const downloaded = page.waitForEvent("download");
    await page.getByRole("button", { name: "Download source version" }).click();
    const download = await downloaded;
    const downloadPath = testInfo.outputPath("pinned-inventor-source.txt");
    await download.saveAs(downloadPath);
    expect(createHash("sha256").update(await readFile(downloadPath)).digest("hex"))
      .toBe(createHash("sha256").update(bytes).digest("hex"));
    await patentScreenshot(page, testInfo, `patent-disclosure-${width}.png`);
    await assertControlsFit(page);

    const listed = await page.request.get(`${apiBaseUrl}/api/ip/dockets`, { headers });
    expect(listed.status(), await listed.text()).toBe(200);
    expect((await listed.json()).dockets.some((row: { id: string }) => row.id === original.docket_id)).toBe(false);
    const legacy = await page.request.get(`${apiBaseUrl}/api/ip/dockets/${original.docket_id}`, { headers });
    expect(legacy.status()).toBe(409);
    const otherApi = await playwright.request.newContext({ extraHTTPHeaders: noPaidProviderHeaders });
    try {
      // Bootstrap issues cookies; another tenant must not replace the owner's browser session.
      const other = await bootstrapPatentTenant(otherApi, true);
      const denied = await otherApi.get(`${apiBaseUrl}/api/ip/patents/families/${familyId}`, {
        headers: { Authorization: `Bearer ${other.access_token}` },
      });
      expect(denied.status()).toBe(404);
    } finally {
      await otherApi.dispose();
    }
    await page.getByRole("tab", { name: "Lifecycle", exact: true }).click();
    await page.getByLabel("Effective date and time", { exact: true }).fill("2026-09-06T10:00");
    await page.getByLabel("Reason", { exact: true }).fill("Client withdrew this test disclosure instruction.");
    await page.getByLabel("Outcome", { exact: true }).fill("closed on client instruction");
    await page.getByLabel("Instruction or evidence reference", { exact: true }).fill("local-fixture:withdrawal");
    await page.getByRole("button", { name: "Preview lifecycle change" }).click();
    await expect(page.getByRole("button", { name: "Confirm lifecycle change" })).toBeDisabled();
    await page.getByLabel("I confirm this lifecycle change and its recorded impacts.").check();
    await assertControlsFit(page);
    await page.getByRole("button", { name: "Confirm lifecycle change" }).click();
    await expect(page.getByText("closed. Disclosure history and source documents are read-only.", { exact: false })).toBeVisible();
    await expect(page.getByRole("list", { name: "Lifecycle events" })).toContainText("local-fixture:withdrawal");
    await page.reload();
    await expect(page.getByRole("heading", { name: `Corrected substrate invention ${run}`, level: 1 })).toBeVisible();
    await expect(page.getByRole("button", { name: "Edit disclosure" })).toHaveCount(0);
    const retainedDownload = page.waitForEvent("download");
    await page.getByRole("button", { name: "Download source version" }).click();
    const retained = await retainedDownload;
    const retainedPath = testInfo.outputPath("closed-patent-source.txt");
    await retained.saveAs(retainedPath);
    expect(createHash("sha256").update(await readFile(retainedPath)).digest("hex"))
      .toBe(createHash("sha256").update(bytes).digest("hex"));
    await page.getByRole("tab", { name: "Documents", exact: true }).click();
    await expect(page.getByRole("button", { name: "Upload reviewed document" })).toHaveCount(0);
    await expect(page.getByText(document.versions[0].display_name, { exact: true }).first()).toBeVisible();
    const terminalWrite = await page.request.post(`${apiBaseUrl}/api/ip/patents/families/${familyId}/corrections`, {
      headers, data: { expected_version: 3, expected_lifecycle_version: 0,
        reason: "Terminal-write regression must reject.", facts: original.facts },
    });
    expect(terminalWrite.status()).toBe(404);
    await page.getByRole("link", { name: "Patent families", exact: true }).click();
    await expect(page.getByRole("link", { name: `Corrected substrate invention ${run}`, exact: true })).toHaveCount(0);
    await page.getByLabel("Lifecycle", { exact: true }).selectOption("terminal");
    await page.getByLabel("Family title", { exact: true }).fill(`Corrected substrate invention ${run}`);
    await page.getByRole("button", { name: "Search patent families", exact: true }).click();
    const terminalFamilyLink = page.getByRole("link", { name: `Corrected substrate invention ${run}`, exact: true });
    await expect(terminalFamilyLink).toBeVisible();
    await terminalFamilyLink.click();
    await page.getByRole("tab", { name: "Lifecycle", exact: true }).click();
    await page.getByLabel("Effective date and time", { exact: true }).fill("2026-09-06T10:01");
    await page.getByLabel("Reason", { exact: true }).fill("Client explicitly renewed the disclosure instruction.");
    await page.getByLabel("Outcome", { exact: true }).fill("intake resumed");
    await page.getByLabel("Instruction or evidence reference", { exact: true }).fill("local-fixture:explicit-reopen");
    await page.getByRole("button", { name: "Preview lifecycle change" }).click();
    await expect(page.getByText("Previously cancelled tasks, hearings and deadlines remain cancelled.")).toBeVisible();
    await page.getByLabel("I confirm this lifecycle change and its recorded impacts.").check();
    await page.getByRole("button", { name: "Confirm lifecycle change" }).click();
    await expect(page.getByRole("list", { name: "Lifecycle events" })).toContainText("local-fixture:explicit-reopen");
    await page.reload();
    await expect(page.getByRole("button", { name: "Edit disclosure" })).toBeVisible();
    const reopened = await page.request.get(`${apiBaseUrl}/api/ip/patents/families/${familyId}`, { headers });
    expect((await reopened.json()).lifecycle_status).toBe("ready");
    expect((await reopened.json()).lifecycle_version).toBe(2);
    await page.getByRole("tab", { name: "Lifecycle", exact: true }).click();
    await assertControlsFit(page);
    await patentScreenshot(page, testInfo, `patent-lifecycle-${width}.png`);
    await page.getByLabel("Effective date and time", { exact: true }).fill("2026-09-06T09:59");
    await page.getByLabel("Reason", { exact: true }).fill("Reviewed earlier effective time for the final same-day closure.");
    await page.getByLabel("Outcome", { exact: true }).fill("closed");
    await page.getByLabel("Instruction or evidence reference", { exact: true }).fill("local-fixture:final-closure");
    await page.getByRole("button", { name: "Preview lifecycle change" }).click();
    await page.getByLabel("I confirm this lifecycle change and its recorded impacts.").check();
    await expect(page.getByRole("button", { name: "Confirm lifecycle change" })).toBeDisabled();
    await page.getByLabel("Reviewed exception: backdated recalculation review required", { exact: true }).check();
    await page.getByLabel("I confirm this lifecycle change and its recorded impacts.").check();
    await assertControlsFit(page);
    await patentScreenshot(page, testInfo, `patent-backdated-review-${width}.png`);
    await page.getByRole("button", { name: "Confirm lifecycle change" }).click();
    await expect(page.getByRole("list", { name: "Lifecycle events" })).toContainText("local-fixture:final-closure");
    const finalHistory = await page.request.get(`${apiBaseUrl}/api/ip/patents/families/${familyId}/lifecycle-history`, { headers });
    expect((await finalHistory.json()).events.map((event: { to_status: string }) => event.to_status)).toEqual(["closed", "ready", "closed"]);
    await page.reload();
    await expect(page.getByRole("button", { name: "Edit disclosure" })).toHaveCount(0);
    const finalFamily = await page.request.get(`${apiBaseUrl}/api/ip/patents/families/${familyId}`, { headers });
    expect((await finalFamily.json()).lifecycle_version).toBe(3);
    expect((await finalFamily.json()).lifecycle_status).toBe("closed");
  });
}
