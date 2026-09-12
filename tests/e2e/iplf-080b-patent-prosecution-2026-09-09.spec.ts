import { createHash, randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";
import { expect, test, type Page } from "@playwright/test";
import { noPaidProviderHeaders } from "./support/cost-controls";
import {
  apiBaseUrl, bootstrapPatentTenant, enablePatentWorkspace, patentRunId,
  patentScreenshot, signInPatentTenant,
} from "./support/patent-acceptance";
import { assertPatentControlsFit } from "./support/patent-layout";

test.use({ extraHTTPHeaders: noPaidProviderHeaders });

async function lifecycle(page: Page, reference: string, effective: string) {
  await page.getByRole("tab", { name: "Lifecycle", exact: true }).click();
  await page.getByLabel("Effective date and time", { exact: true }).fill(effective);
  await page.getByLabel("Reason", { exact: true }).fill("Explicit instruction for this isolated patent application.");
  await page.getByLabel("Outcome", { exact: true }).fill("client instruction recorded");
  await page.getByLabel("Instruction or evidence reference", { exact: true }).fill(reference);
  await page.getByRole("button", { name: "Preview lifecycle change" }).click();
  await expect(page.getByRole("button", { name: "Confirm lifecycle change" })).toBeDisabled();
  await page.getByLabel("I confirm this lifecycle change and its recorded impacts.").check();
  await page.getByRole("button", { name: "Confirm lifecycle change" }).click();
  await expect(page.getByRole("list", { name: "Lifecycle events" })).toContainText(reference);
}

// PAT-01/03/04 / UJ-39 / IPLF-080B: manual sourced prosecution, not legal automation.
for (const width of [393, 768, 1280]) {
  test(`IPLF-080 immutable patent package and prosecution lifecycle at ${width}px`, async ({ page, playwright }, testInfo) => {
    const run = patentRunId();
    const tenant = await bootstrapPatentTenant(page.request);
    const headers = { ...await enablePatentWorkspace(page.request, tenant), ...noPaidProviderHeaders };
    const client = await page.request.post(`${apiBaseUrl}/api/clients`, {
      headers, data: { name: `Prosecution client ${run}`, client_type: "corporate" },
    });
    expect(client.status(), await client.text()).toBe(200);
    const familyResponse = await page.request.post(`${apiBaseUrl}/api/ip/patents/families`, {
      headers: { ...headers, "Idempotency-Key": randomUUID() }, data: {
        title: `Prosecution family ${run}`, client_id: (await client.json()).id,
        disclosure_date: "2026-09-09", disclosure_narrative: "Synthetic unpublished invention fixture.",
      },
    });
    expect(familyResponse.status(), await familyResponse.text()).toBe(201);
    const family = await familyResponse.json();
    const taxonomy = await page.request.post(`${apiBaseUrl}/api/ip/document-taxonomy/seed`, { headers });
    expect(taxonomy.status(), await taxonomy.text()).toBe(200);
    const bytes = Buffer.from(`Synthetic patent claim and filing evidence, not official legal text. ${run} `.repeat(30));
    const upload = await page.request.post(`${apiBaseUrl}/api/ip/documents/upload`, {
      headers, multipart: {
        metadata_json: JSON.stringify({ taxonomy_key: "evidence", title: `Exact source ${run}`,
          confidentiality: "internal", is_privileged: false, client_code: "PATENT",
          asset_type: "Patent", mark: "Synthetic invention", jurisdiction: "IN", document_date: "2026-09-09",
          links: [{ target_type: "docket", target_id: family.docket_id }] }),
        upload: { name: `patent-source-${run}.txt`, mimeType: "text/plain", buffer: bytes },
      },
    });
    expect(upload.status(), await upload.text()).toBe(200);
    const uploaded = await upload.json();
    expect(uploaded.outcome).toBe("created");
    const document = uploaded.document;
    const source = { kind: "document_version", document_id: document.id,
      document_version_id: document.versions[0].id, content_sha256: document.versions[0].sha256_hex };
    const applicationResponse = await page.request.post(`${apiBaseUrl}/api/ip/patents/applications`, {
      headers: { ...headers, "Idempotency-Key": randomUUID() }, data: {
        family_id: family.id, expected_family_version: family.version,
        expected_family_lifecycle_version: family.lifecycle_version,
        facts: { title: `Sourced prosecution ${run}`, application_kind: "complete", jurisdiction: "IN",
          office: "IP India", filing_date: "2026-09-09", source_pending_identifier_allocation: true,
          identifiers: [], source },
      },
    });
    expect(applicationResponse.status(), await applicationResponse.text()).toBe(201);
    const application = await applicationResponse.json();
    const endpoint = `${apiBaseUrl}/api/ip/patents/applications/${application.id}`;
    await signInPatentTenant(page, tenant);
    await page.setViewportSize({ width, height: 900 });
    // The API returned the authoritative family identity. The bounded,
    // UUID-ordered list may not include a newly-created record on page one.
    await page.goto(`/app/ip/patents/${family.id}`);
    await page.getByRole("tab", { name: "Applications", exact: true }).click();
    await page.getByRole("link", { name: application.facts.title, exact: true }).click();
    await page.getByRole("tab", { name: "Work product", exact: true }).click();
    await page.getByRole("button", { name: "Prepare edition", exact: true }).click();
    const form = page.getByRole("form", { name: "Prepare patent edition" });
    await form.getByLabel("Source evidence", { exact: true }).selectOption(source.document_version_id);
    await form.getByLabel("Edition title", { exact: true }).fill(`Filed package ${run}`);
    await form.getByLabel("Exact version 1", { exact: true }).selectOption(source.document_version_id);
    await form.getByLabel("Reason", { exact: true }).fill("Freeze the exact synthetic claims for reviewed filing.");
    if (width === 1280) {
      for (const boundary of [639, 640, 641, 767, 768, 769, 1023, 1024, 1025]) {
        await page.setViewportSize({ width: boundary, height: 900 });
        await assertPatentControlsFit(page);
      }
      await page.setViewportSize({ width, height: 900 });
    }
    await assertPatentControlsFit(page);
    const saving = page.waitForResponse((response) => response.url() === `${endpoint}/evidence` && response.request().method() === "POST");
    await form.getByRole("button", { name: "Save edition" }).click();
    const savedResponse = await saving;
    expect(savedResponse.status(), await savedResponse.text()).toBe(201);
    const edition = await savedResponse.json();
    const savedCommand = savedResponse.request().postDataJSON();
    const savedKey = savedResponse.request().headers()["idempotency-key"];
    await expect(page.getByRole("region", { name: "Patent work product", exact: true }).getByRole("status")).toContainText("Patent evidence saved.");
    await expect(page.getByRole("main").getByRole("alert")).toHaveCount(0);
    await expect(page.getByRole("list", { name: "Patent document editions" })).toContainText(`Filed package ${run}`);
    const replay = await page.request.post(`${endpoint}/evidence`, {
      headers: { ...headers, "Idempotency-Key": savedKey }, data: savedCommand,
    });
    expect(replay.status(), await replay.text()).toBe(201);
    expect(await replay.json()).toEqual(edition);
    await page.getByRole("tab", { name: "Prosecution", exact: true }).click();
    await page.getByRole("button", { name: "Record event", exact: true }).click();
    const eventForm = page.getByRole("form", { name: "Record patent event" });
    await eventForm.getByLabel("Source evidence", { exact: true }).selectOption(source.document_version_id);
    await eventForm.getByLabel("Event", { exact: true }).selectOption("filing");
    await eventForm.getByLabel("Exact work product", { exact: true }).selectOption(edition.id);
    await eventForm.getByLabel("Received date", { exact: true }).fill("2026-09-09");
    await eventForm.getByLabel("Effective date", { exact: true }).fill("2026-09-09");
    await eventForm.getByLabel("Reason", { exact: true }).fill("Record reviewed filing evidence and the frozen package.");
    await eventForm.getByRole("button", { name: "Preview event" }).click();
    await expect(eventForm.getByRole("region", { name: "Prosecution impact" })).toContainText("disclosure to filed");
    await assertPatentControlsFit(page);
    const recording = page.waitForResponse((response) => response.url() === `${endpoint}/prosecution` && response.request().method() === "POST");
    await eventForm.getByRole("button", { name: "Record reviewed event" }).click();
    const recorded = await recording;
    expect(recorded.status(), await recorded.text()).toBe(201);
    const event = await recorded.json();
    expect(event.evidence_id).toBe(edition.id);
    expect(event.impact.changes_deadlines).toBe(false);
    await expect(page.getByRole("region", { name: "Patent prosecution", exact: true }).getByRole("status")).toContainText("Patent evidence saved.");
    await expect(page.getByRole("main").getByRole("alert")).toHaveCount(0);
    await expect(page.getByRole("region", { name: "Patent prosecution", exact: true })).toContainText("Current phase: filed");
    await page.reload();
    await page.getByRole("tab", { name: "Prosecution", exact: true }).click();
    await expect(page.getByRole("list", { name: "Patent prosecution history" })).toContainText("2026-09-09");
    await patentScreenshot(page, testInfo, `patent-prosecution-${width}.png`);
    await page.getByRole("tab", { name: "Work product", exact: true }).click();
    await page.getByRole("button", { name: "New edition", exact: true }).click();
    await page.getByLabel("Edition title", { exact: true }).fill(`Later package ${run}`);
    await page.getByRole("form", { name: "Prepare patent edition" }).getByLabel("Reason", { exact: true }).fill("Later edition must not change the already filed package.");
    await page.getByRole("button", { name: "Save edition", exact: true }).click();
    await expect(page.getByRole("list", { name: "Patent document editions" })).toContainText("Edition 2");
    expect(await (await page.request.get(`${endpoint}/prosecution/${event.id}`, { headers })).json()).toEqual(event);
    await lifecycle(page, "fixture:patent-work-close", "2026-09-09T10:00");
    await page.reload();
    await page.getByRole("tab", { name: "Work product", exact: true }).click();
    await expect(page.getByRole("button", { name: "Prepare edition" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "New edition" })).toHaveCount(0);
    const retained = page.getByRole("list", { name: "Patent document editions" }).getByRole("listitem").filter({ has: page.getByRole("heading", { name: `Filed package ${run}`, exact: true }) });
    const downloading = page.waitForEvent("download");
    await retained.getByRole("button", { name: "Download source version" }).click();
    const downloaded = await downloading;
    const downloadedPath = testInfo.outputPath("retained-patent-source.txt");
    await downloaded.saveAs(downloadedPath);
    expect(createHash("sha256").update(await readFile(downloadedPath)).digest("hex")).toBe(source.content_sha256);
    expect(createHash("sha256").update(bytes).digest("hex")).toBe(source.content_sha256);
    const denied = await page.request.post(`${endpoint}/evidence`, { headers: { ...headers, "Idempotency-Key": savedKey }, data: savedCommand });
    expect(denied.status()).toBe(404);
    await lifecycle(page, "fixture:patent-work-reopen", "2026-09-09T10:01");
    const staleReplay = await page.request.post(`${endpoint}/evidence`, { headers: { ...headers, "Idempotency-Key": savedKey }, data: savedCommand });
    expect(staleReplay.status()).toBe(409);
    await page.getByRole("tab", { name: "Work product", exact: true }).click();
    await expect(page.getByRole("button", { name: "Prepare edition" })).toBeVisible();
    await expect(page.getByRole("button", { name: "New edition" })).toHaveCount(0);
    await lifecycle(page, "fixture:patent-work-second-close", "2026-09-09T10:02");
    const otherApi = await playwright.request.newContext({ extraHTTPHeaders: noPaidProviderHeaders });
    try {
      const other = await bootstrapPatentTenant(otherApi, true);
      for (const suffix of [`/evidence/${edition.id}`, `/prosecution/${event.id}`, "/evidence", "/prosecution"]) {
        const response = await otherApi.get(endpoint + suffix, { headers: { Authorization: `Bearer ${other.access_token}` } });
        expect(response.status()).toBe(404);
      }
    } finally { await otherApi.dispose(); }
    await page.reload();
    await page.getByRole("tab", { name: "Work product", exact: true }).click();
    await expect(retained).toContainText("Edition 1");
    await expect(page.getByRole("button", { name: "Prepare edition" })).toHaveCount(0);
    expect(await (await page.request.get(`${endpoint}/prosecution/${event.id}`, { headers })).json()).toEqual(event);
    expect(await (await page.request.get(`${apiBaseUrl}/api/ip/patents/families/${family.id}`, { headers })).json()).toEqual(family);
    await assertPatentControlsFit(page);
    await patentScreenshot(page, testInfo, `patent-retained-work-${width}.png`);
  });
}
