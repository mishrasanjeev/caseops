import { createHash, randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";
import { expect, test } from "@playwright/test";

import { noPaidProviderHeaders } from "./support/cost-controls";
import { apiBaseUrl, bootstrapPatentTenant, enablePatentWorkspace, patentRunId, patentScreenshot, signInPatentTenant } from "./support/patent-acceptance";
import { assertPatentControlsFit } from "./support/patent-layout";

test.use({ extraHTTPHeaders: noPaidProviderHeaders });

// PAT-03 / UJ-39-EXC-03: an actual separate proceeding, never a prosecution event.
for (const width of [393, 768, 1280]) {
  test(`IPLF-080B pre-grant notice to decision with retained lifecycle evidence at ${width}px`, async ({ page, playwright }, info) => {
    const run = patentRunId();
    const tenant = await bootstrapPatentTenant(page.request);
    const headers = { ...await enablePatentWorkspace(page.request, tenant), ...noPaidProviderHeaders };
    const clientResponse = await page.request.post(`${apiBaseUrl}/api/clients`, { headers, data: { name: `Pre-grant client ${run}`, client_type: "corporate" } });
    expect(clientResponse.status(), await clientResponse.text()).toBe(200);
    const familyResponse = await page.request.post(`${apiBaseUrl}/api/ip/patents/families`, {
      headers: { ...headers, "Idempotency-Key": randomUUID() }, data: {
        title: `Pre-grant family ${run}`, client_id: (await clientResponse.json()).id,
        disclosure_date: "2026-09-10", disclosure_narrative: "Synthetic source-bounded patent proceeding fixture.",
      },
    });
    expect(familyResponse.status(), await familyResponse.text()).toBe(201);
    const family = await familyResponse.json();
    expect((await page.request.post(`${apiBaseUrl}/api/ip/document-taxonomy/seed`, { headers })).status()).toBe(200);
    const bytes = Buffer.from(`Synthetic opposition notice, response and decision evidence ${run}; not official legal text. `.repeat(30));
    const upload = await page.request.post(`${apiBaseUrl}/api/ip/documents/upload`, { headers, multipart: {
      metadata_json: JSON.stringify({ taxonomy_key: "evidence", title: `Opposition source ${run}`, confidentiality: "internal",
        is_privileged: false, client_code: "PATENT", asset_type: "Patent", mark: "Synthetic invention", jurisdiction: "IN",
        document_date: "2026-09-10", links: [{ target_type: "docket", target_id: family.docket_id }] }),
      upload: { name: `opposition-${run}.txt`, mimeType: "text/plain", buffer: bytes },
    } });
    expect(upload.status(), await upload.text()).toBe(200);
    const uploaded = await upload.json(); expect(uploaded.outcome).toBe("created");
    const doc = uploaded.document;
    const source = { kind: "document_version", document_id: doc.id, document_version_id: doc.versions[0].id, content_sha256: doc.versions[0].sha256_hex };
    const applicationInput = { family_id: family.id, expected_family_version: family.version,
      expected_family_lifecycle_version: family.lifecycle_version, facts: { title: `Pre-grant application ${run}`,
        application_kind: "complete", jurisdiction: "IN", office: "IP India", filing_date: "2026-09-10",
        source_pending_identifier_allocation: true, identifiers: [], source } };
    const created = await page.request.post(`${apiBaseUrl}/api/ip/patents/applications`, { headers: { ...headers, "Idempotency-Key": randomUUID() }, data: applicationInput });
    expect(created.status(), await created.text()).toBe(201); const application = await created.json();
    const endpoint = `${apiBaseUrl}/api/ip/patents/applications/${application.id}`;
    const siblingResponse = await page.request.post(`${apiBaseUrl}/api/ip/patents/applications`, {
      headers: { ...headers, "Idempotency-Key": randomUUID() }, data: { ...applicationInput,
        facts: { ...applicationInput.facts, title: `Unaffected sibling ${run}`, office: "USPTO" } },
    });
    expect(siblingResponse.status(), await siblingResponse.text()).toBe(201); const sibling = await siblingResponse.json();
    const manifestResponse = await page.request.post(`${endpoint}/evidence`, { headers: { ...headers, "Idempotency-Key": randomUUID() }, data: {
      expected_version: 1, expected_lifecycle_version: 0, expected_work_sequence: 0,
      title: `Response package ${run}`, document_kind: "response", source,
      documents: [{ document_kind: "response", source }], reason: "Freeze the reviewed synthetic response document.",
    } });
    expect(manifestResponse.status(), await manifestResponse.text()).toBe(201); const manifest = await manifestResponse.json();
    await signInPatentTenant(page, tenant);
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/app/ip/patents");
    await page.getByRole("link", { name: family.facts.title, exact: true }).click();
    await page.getByRole("tab", { name: "Applications", exact: true }).click();
    await page.getByRole("link", { name: application.facts.title, exact: true }).click();
    await page.getByRole("tab", { name: "Proceedings", exact: true }).click();
    const region = page.getByRole("region", { name: "Patent proceedings", exact: true });
    await region.getByRole("button", { name: "New pre-grant opposition" }).click();
    const intake = page.getByRole("form", { name: "New patent proceeding" });
    await intake.getByLabel("Proceeding title", { exact: true }).fill(`Pre-grant opposition ${run}`);
    await intake.getByLabel("Counterparty", { exact: true }).fill(`Example Research ${run}`);
    await intake.getByLabel("Proceeding source", { exact: true }).selectOption(source.document_version_id);
    await intake.getByLabel("Received date", { exact: true }).fill("2026-09-10");
    await intake.getByLabel("Effective date", { exact: true }).fill("2026-09-10");
    await intake.getByLabel("Reason", { exact: true }).fill("Record the independently received opposition notice.");
    await assertPatentControlsFit(page);
    await patentScreenshot(page, info, `pregrant-intake-${width}.png`);
    const saving = page.waitForResponse((response) => response.url() === `${endpoint}/proceedings` && response.request().method() === "POST");
    await intake.getByRole("button", { name: "Save proceeding" }).click();
    const saved = await saving; expect(saved.status(), await saved.text()).toBe(201);
    let record = await saved.json();
    const initialCommand = saved.request().postDataJSON(); const initialKey = saved.request().headers()["idempotency-key"];
    const proceedingUrl = `${endpoint}/proceedings/${record.id}`;
    expect(record.id).not.toBe(application.id); expect(record.latest.source).toEqual(source);
    await expect(region.getByRole("status")).toHaveText("Patent proceeding saved.");
    await expect(page.getByRole("main").getByRole("alert")).toHaveCount(0);
    const replay = await page.request.post(`${endpoint}/proceedings`, { headers: { ...headers, "Idempotency-Key": initialKey }, data: initialCommand });
    expect(replay.status(), await replay.text()).toBe(201); expect(await replay.json()).toEqual(record);
    const stages = ["response_preparation", "response_filed", "hearing_recorded", "decided"];
    for (const stage of stages) {
      await region.getByRole("button", { name: "Update proceeding" }).click();
      const form = page.getByRole("form", { name: "Update patent proceeding" });
      await form.getByLabel("Proceeding stage", { exact: true }).selectOption(stage);
      await form.getByLabel("Proceeding source", { exact: true }).selectOption(source.document_version_id);
      await form.getByLabel("Received date", { exact: true }).fill("2026-09-10");
      await form.getByLabel("Effective date", { exact: true }).fill("2026-09-10");
      await form.getByLabel("Reason", { exact: true }).fill(`Record sourced ${stage} without changing prosecution phase.`);
      if (stage === "response_preparation") await form.getByLabel("Proceeding number", { exact: true }).fill(`SYN-PGO-${run}`);
      if (stage === "response_filed") await form.getByLabel("Exact response manifest", { exact: true }).selectOption(manifest.id);
      if (stage === "decided") await form.getByLabel("Outcome", { exact: true }).fill("Opposition rejected in the synthetic source decision.");
      if (width === 1280 && stage === "response_filed") {
        for (const boundary of [639, 640, 641, 767, 768, 769, 1023, 1024, 1025]) {
          await page.setViewportSize({ width: boundary, height: 900 }); await assertPatentControlsFit(page);
        }
        await page.setViewportSize({ width, height: 900 });
      }
      await form.getByRole("button", { name: "Preview stage" }).click();
      await expect(form.getByRole("region", { name: "Proceeding impact" })).toContainText(stage.replaceAll("_", " "));
      const committing = page.waitForResponse((response) => response.url() === `${proceedingUrl}/transitions` && response.request().method() === "POST");
      await form.getByRole("button", { name: "Record reviewed stage" }).click();
      const result = await committing; expect(result.status(), await result.text()).toBe(201); record = await result.json();
      expect(record.stage).toBe(stage); expect(record.latest.proceeding_number).toBe(`SYN-PGO-${run}`);
      expect(record.latest.impact.changes_application_phase).toBe(false); expect(record.latest.impact.changes_deadlines).toBe(false);
      if (stage === "response_filed") expect(record.latest.evidence_id).toBe(manifest.id);
      await expect(region.getByRole("status")).toHaveText("Patent proceeding saved.");
      await expect(page.getByRole("main").getByRole("alert")).toHaveCount(0);
    }
    expect(record.operational).toBe(false);
    await expect(region.getByRole("button", { name: "Update proceeding" })).toHaveCount(0);
    const retained = await (await page.request.get(proceedingUrl, { headers })).json();
    expect(retained.events).toHaveLength(5); expect(retained.events[0].proceeding_number).toBeNull();
    expect(retained.events[2].evidence_id).toBe(manifest.id);
    expect((await (await page.request.get(endpoint, { headers })).json()).prosecution_phase).toBe(application.prosecution_phase);
    expect(await (await page.request.get(`${apiBaseUrl}/api/ip/patents/applications/${sibling.id}`, { headers })).json()).toEqual(sibling);
    const stillOpen = await page.request.post(`${endpoint}/proceedings`, { headers: { ...headers, "Idempotency-Key": randomUUID() }, data: {
      ...initialCommand, expected_work_sequence: record.latest.sequence, title: `Separate open opposition ${run}`,
    } });
    expect(stillOpen.status(), await stillOpen.text()).toBe(201); const openRecord = await stillOpen.json();
    for (const [version, status] of [[0, "closed"], [1, "ready"], [2, "closed"]] as const) {
      const lifecycle = await page.request.post(`${apiBaseUrl}/api/ip/dockets/${application.docket_id}/lifecycle`, { headers, data: {
        expected_lifecycle_version: version, to_status: status, effective_at: new Date().toISOString(),
        reason: "Explicit isolated patent lifecycle instruction.", outcome: status, source: "lawyer_review",
        evidence_ref: `fixture:pregrant-lifecycle-${version}`, linked_matter_handling: "reviewed",
      } });
      expect(lifecycle.status(), await lifecycle.text()).toBe(200);
      const historical = await page.request.get(proceedingUrl, { headers }); expect(historical.status()).toBe(200);
      expect((await historical.json()).events).toEqual(retained.events);
      const neutralized = await page.request.get(`${endpoint}/proceedings/${openRecord.id}`, { headers });
      expect((await neutralized.json()).proceeding.operational).toBe(false);
      const denied = await page.request.post(`${endpoint}/proceedings`, { headers: { ...headers, "Idempotency-Key": initialKey }, data: initialCommand });
      expect(denied.status()).toBe(status === "ready" ? 409 : 404);
    }
    await page.reload(); await page.getByRole("tab", { name: "Proceedings", exact: true }).click();
    await region.getByRole("button", { name: new RegExp(`Pre-grant opposition ${run}`) }).click();
    await expect(region.getByText("Read-only proceeding", { exact: true })).toBeVisible();
    const historyList = page.getByRole("list", { name: "Proceeding stage history" });
    await expect(historyList.getByRole("listitem")).toHaveCount(5);
    const downloadPromise = page.waitForEvent("download");
    await historyList.getByRole("button", { name: "Download source version" }).first().click();
    const download = await downloadPromise; const output = info.outputPath("retained-opposition-source.txt");
    await download.saveAs(output);
    expect(createHash("sha256").update(await readFile(output)).digest("hex")).toBe(source.content_sha256);
    expect(createHash("sha256").update(bytes).digest("hex")).toBe(source.content_sha256);
    await assertPatentControlsFit(page); await patentScreenshot(page, info, `pregrant-retained-${width}.png`);
    if (width === 1280) {
      const otherApi = await playwright.request.newContext({ extraHTTPHeaders: noPaidProviderHeaders });
      try {
        const other = await bootstrapPatentTenant(otherApi, true);
        const denied = await otherApi.get(proceedingUrl, { headers: { ...noPaidProviderHeaders, Authorization: `Bearer ${other.access_token}` } });
        expect(denied.status()).toBe(404);
      } finally { await otherApi.dispose(); }
    }
  });
}
