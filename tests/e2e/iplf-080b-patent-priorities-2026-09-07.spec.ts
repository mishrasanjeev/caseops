import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { expect, test } from "@playwright/test";
import type { PatentApplication, PatentPriority, PatentPriorityPage } from "../../apps/web/lib/api/ip-patents";
import { apiBaseUrl, patentRunId, patentScreenshot } from "./support/patent-acceptance";
import { noPaidProviderHeaders } from "./support/cost-controls";
import { assertPatentControlsFit } from "./support/patent-layout";
import { bootstrapPatentTenant, enablePatentWorkspace, signInPatentTenant } from "./support/patent-acceptance";

test.use({ extraHTTPHeaders: noPaidProviderHeaders });

// UJ-29 / PAT-01 / IPLF-080-PRIO-12: sourced graph records, never legal entitlement.
for (const width of [393, 768, 1280]) {
  test(`IPLF-080 patent priorities preserve cross-family sources, corrections, withdrawal and lifecycle at ${width}px`, async ({ page }, testInfo) => {
    const run = patentRunId();
    const tenant = await bootstrapPatentTenant(page.request);
    const headers = { ...await enablePatentWorkspace(page.request, tenant), ...noPaidProviderHeaders };
    const clientResponse = await page.request.post(`${apiBaseUrl}/api/clients`, { headers,
      data: { name: `Priority journey client ${run}`, client_type: "corporate" } });
    expect(clientResponse.status(), await clientResponse.text()).toBe(200);
    const clientId = (await clientResponse.json()).id;
    const families = [];
    for (const title of ["Priority child family", "Separate parent family"]) {
      const response = await page.request.post(`${apiBaseUrl}/api/ip/patents/families`, {
        headers: { ...headers, "Idempotency-Key": crypto.randomUUID() }, data: {
          title: `${title} ${run}`, client_id: clientId, disclosure_date: "2026-09-05", disclosure_narrative: "Private synthetic priority source evidence.",
        },
      });
      expect(response.status(), await response.text()).toBe(201);
      families.push(await response.json());
    }
    const [family, parentFamily] = families;
    const taxonomy = await page.request.post(`${apiBaseUrl}/api/ip/document-taxonomy/seed`, { headers });
    expect(taxonomy.status(), await taxonomy.text()).toBe(200);
    const bytes = Buffer.from(`Synthetic filed parent and priority evidence, including a sourced correction and withdrawal. ${run} `.repeat(30));
    const upload = await page.request.post(`${apiBaseUrl}/api/ip/documents/upload`, { headers, multipart: {
      metadata_json: JSON.stringify({ taxonomy_key: "evidence", title: "Filed priority source", confidentiality: "restricted",
        is_privileged: true, client_code: "PRIORITY", asset_type: "Patent", mark: "Substrate", jurisdiction: "IN",
        document_date: "2026-09-05", links: [{ target_type: "docket", target_id: family.docket_id }] }),
      upload: { name: "filed-priority-source.txt", mimeType: "text/plain", buffer: bytes },
    } });
    expect(upload.status(), await upload.text()).toBe(200);
    const uploaded = await upload.json();
    expect(uploaded.outcome).toBe("created");
    const document = uploaded.document;
    expect(document).not.toBeNull();
    const source = { kind: "document_version", document_id: document.id,
      document_version_id: document.versions[0].id, content_sha256: document.versions[0].sha256_hex };
    async function application(title: string, kind: string, targetFamily = family): Promise<PatentApplication> {
      const response = await page.request.post(`${apiBaseUrl}/api/ip/patents/applications`, {
        headers: { ...headers, "Idempotency-Key": crypto.randomUUID() }, data: {
          family_id: targetFamily.id, expected_family_version: targetFamily.version, expected_family_lifecycle_version: 0,
          facts: { title: `${title} ${run}`, application_kind: kind, jurisdiction: "IN", office: "IP India", filing_date: "2026-09-05",
            source, identifiers: [], source_pending_identifier_allocation: true },
        },
      });
      expect(response.status(), await response.text()).toBe(201);
      return response.json();
    }
    const parent = await application("Cross-family complete parent", "complete", parentFamily);
    const pct = await application("PCT international parent", "pct_international", parentFamily);
    const children = [];
    for (const [kind, relation] of [["complete", "priority"], ["divisional", "divisional_parent"],
      ["patent_of_addition", "addition_parent"], ["national_phase", "national_phase_parent"]]) {
      children.push({ record: await application(`Sourced ${kind} child`, kind), relation, parent: relation === "national_phase_parent" ? pct : parent });
    }
    await signInPatentTenant(page, tenant);
    await page.setViewportSize({ width, height: 900 });
    const saved: PatentPriority[] = [];
    for (const item of children) {
      await page.goto(`/app/ip/patents/applications/${item.record.id}`);
      await expect(page.getByRole("heading", { level: 1, name: item.record.facts.title, exact: true })).toBeVisible();
      const menu = page.getByRole("button", { name: "Open navigation menu", exact: true });
      if (width < 768) await menu.click();
      const navigation = width < 768
        ? page.getByRole("dialog", { name: "Workspace navigation" })
        : page.getByRole("complementary", { name: "Primary navigation" });
      const currentLink = navigation.locator('a[aria-current="page"]');
      await expect(currentLink).toHaveCount(1);
      await expect(currentLink).toHaveAccessibleName("Patent intake");
      if (width < 768) await page.keyboard.press("Escape");
      await page.getByRole("tab", { name: "Priorities", exact: true }).click();
      await page.getByRole("button", { name: "Add relationship", exact: true }).click();
      const form = page.getByRole("form", { name: "Add patent relationship", exact: true });
      await form.getByLabel("Parent title or exact identifier", { exact: true }).fill(item.parent.facts.title);
      await form.getByRole("button", { name: "Search parent applications" }).click();
      await form.getByLabel("Parent application", { exact: true }).selectOption(item.parent.id);
      await form.getByLabel("Relationship type", { exact: true }).selectOption(item.relation);
      await form.getByLabel("Recorded priority date", { exact: true }).fill("2026-09-05");
      await form.getByLabel("Relationship source version", { exact: true }).selectOption(source.document_version_id);
      await form.getByLabel("Relationship change reason", { exact: true }).fill(`Record exact ${item.relation} source facts.`);
      await assertPatentControlsFit(page);
      await form.getByRole("button", { name: "Save relationship", exact: true }).click();
      const list = page.getByRole("list", { name: "Recorded patent relationships", exact: true });
      await expect(list.getByRole("link", { name: item.parent.facts.title, exact: true })).toBeVisible();
      await assertPatentControlsFit(page);
      const response = await page.request.get(`${apiBaseUrl}/api/ip/patents/applications/${item.record.id}/priorities`, { headers });
      expect(response.status(), await response.text()).toBe(200);
      const records: PatentPriorityPage = await response.json();
      expect(records.priorities).toHaveLength(1);
      expect(records.priorities[0]).toMatchObject({ application_id: item.record.id, parent_application_id: item.parent.id,
        application_version: 1, parent_version: 1, lifecycle_version: 0, parent_lifecycle_version: 0,
        relation_kind: item.relation, priority_date: "2026-09-05", source, is_current: true, withdrawn: false, review_flags: [] });
      saved.push(records.priorities[0]);
      await page.reload();
      await page.getByRole("tab", { name: "Priorities", exact: true }).click();
      await expect(list.getByRole("listitem")).toHaveCount(1);
    }
    await page.goto(`/app/ip/patents/${family.id}`);
    await expect(page.getByRole("heading", { level: 1, name: family.facts.title, exact: true })).toBeVisible();
    await page.getByRole("tab", { name: "Relationships", exact: true }).click();
    await expect(page.getByRole("list", { name: "Family graph links", exact: true }).getByRole("listitem")).toHaveCount(4);
    await expect(page.getByRole("list", { name: "Family graph applications", exact: true }).getByRole("listitem")).toHaveCount(4);
    await assertPatentControlsFit(page);
    await patentScreenshot(page, testInfo, `priority-family-graph-${width}.png`);

    const child = children[0].record;
    await page.goto(`/app/ip/patents/applications/${parent.id}`);
    await page.getByRole("tab", { name: "Priorities", exact: true }).click();
    await page.getByRole("button", { name: "Add relationship", exact: true }).click();
    const cycle = page.getByRole("form", { name: "Add patent relationship", exact: true });
    await cycle.getByLabel("Parent application", { exact: true }).selectOption(child.id);
    await cycle.getByLabel("Recorded priority date", { exact: true }).fill("2026-09-05");
    await cycle.getByLabel("Relationship change reason", { exact: true }).fill("This reverse relationship must not form a cycle.");
    await cycle.getByRole("button", { name: "Save relationship", exact: true }).click();
    await expect(cycle.getByRole("alert")).toContainText("cycle");
    await expect(cycle.getByLabel("Recorded priority date", { exact: true })).toHaveValue("2026-09-05");
    await cycle.getByRole("button", { name: "Cancel", exact: true }).click();
    await page.getByRole("tab", { name: "Lifecycle", exact: true }).click();
    await page.getByLabel("Effective date and time", { exact: true }).fill("2026-09-07T10:00");
    await page.getByLabel("Reason", { exact: true }).fill("Close the parent while retaining historical priority evidence.");
    await page.getByLabel("Outcome", { exact: true }).fill("closed");
    await page.getByLabel("Instruction or evidence reference", { exact: true }).fill("local-fixture:priority-parent-close");
    await page.getByRole("button", { name: "Preview lifecycle change" }).click();
    await page.getByLabel("I confirm this lifecycle change and its recorded impacts.").check();
    await page.getByRole("button", { name: "Confirm lifecycle change" }).click();
    await expect(page.getByRole("list", { name: "Lifecycle events" })).toContainText("local-fixture:priority-parent-close");

    await page.goto(`/app/ip/patents/applications/${child.id}`);
    await page.getByRole("tab", { name: "Priorities", exact: true }).click();
    const correctedUpload = await page.request.post(`${apiBaseUrl}/api/ip/documents/upload`, { headers, multipart: {
      metadata_json: JSON.stringify({ taxonomy_key: "evidence", title: "Corrected priority source", confidentiality: "restricted",
        is_privileged: true, client_code: "PRIORITY", asset_type: "Patent", mark: "Substrate", jurisdiction: "IN",
        document_date: "2026-09-07", links: [{ target_type: "docket", target_id: child.docket_id }] }),
      upload: { name: "corrected-priority-source.txt", mimeType: "text/plain", buffer: Buffer.from(`Corrected synthetic priority evidence. ${run} `.repeat(30)) },
    } });
    expect(correctedUpload.status(), await correctedUpload.text()).toBe(200);
    const corrected = await correctedUpload.json();
    expect(corrected.outcome).toBe("created");
    const correctedDocument = corrected.document;
    expect(correctedDocument).not.toBeNull();
    const correctedSource = { kind: "document_version", document_id: correctedDocument.id,
      document_version_id: correctedDocument.versions[0].id, content_sha256: correctedDocument.versions[0].sha256_hex };
    await page.getByRole("button", { name: "Correct relationship", exact: true }).click();
    const correction = page.getByRole("form", { name: "Correct patent relationship", exact: true });
    await expect(correction.getByLabel("Parent application", { exact: true })).toHaveValue(parent.id);
    await expect(correction.getByLabel("Recorded priority date", { exact: true })).toHaveValue("2026-09-05");
    await correction.getByLabel("Relationship source version", { exact: true }).selectOption(correctedSource.document_version_id);
    await correction.getByLabel("Relationship change reason", { exact: true }).fill("Correct the evidence explanation without changing the closed parent.");
    await assertPatentControlsFit(page);
    if (width === 1280) {
      for (const boundary of [639, 640, 641, 767, 768, 769, 1023, 1024, 1025]) {
        await page.setViewportSize({ width: boundary, height: 900 });
        await assertPatentControlsFit(page);
      }
      await page.setViewportSize({ width, height: 900 });
    }
    await patentScreenshot(page, testInfo, `priority-correction-${width}.png`);
    await correction.getByRole("button", { name: "Save relationship", exact: true }).click();
    await expect(correction).toHaveCount(0);
    const correctedList = await page.request.get(`${apiBaseUrl}/api/ip/patents/applications/${child.id}/priorities`, { headers });
    expect(correctedList.status(), await correctedList.text()).toBe(200);
    const correctedRecord = (await correctedList.json()).priorities[0];
    expect(correctedRecord.source).toEqual(correctedSource);
    expect(correctedRecord.canonical_relationship_id).toBe(saved[0].canonical_relationship_id);
    await page.getByLabel("Include relationship history", { exact: true }).check();
    const list = page.getByRole("list", { name: "Recorded patent relationships", exact: true });
    await expect(list.getByRole("listitem")).toHaveCount(2);
    const historical = list.getByRole("listitem").filter({ hasText: "Superseded" });
    const downloading = page.waitForEvent("download");
    await historical.getByRole("button", { name: "Download source version", exact: true }).click();
    const path = testInfo.outputPath("retained-priority-source.txt");
    await (await downloading).saveAs(path);
    expect(createHash("sha256").update(await readFile(path)).digest("hex")).toBe(source.content_sha256);
    expect(createHash("sha256").update(bytes).digest("hex")).toBe(source.content_sha256);
    const retained = await page.request.get(`${apiBaseUrl}/api/ip/patents/applications/${child.id}/priorities/${saved[0].id}`, { headers });
    expect(retained.status(), await retained.text()).toBe(200);
    expect(await retained.json()).toEqual({ ...saved[0], is_current: false });
    await page.getByLabel("Include relationship history", { exact: true }).uncheck();
    await page.getByRole("button", { name: "Withdraw record", exact: true }).click();
    const withdrawal = page.getByRole("form", { name: "Withdraw patent relationship", exact: true });
    await expect(withdrawal.getByLabel("Recorded priority date", { exact: true })).toBeDisabled();
    await withdrawal.getByLabel("Relationship change reason", { exact: true }).fill("Withdraw this recorded link based on the retained evidence.");
    await withdrawal.getByRole("button", { name: "Save withdrawal record", exact: true }).click();
    await expect(list.getByRole("listitem")).toHaveCount(0);
    await page.reload();
    await page.getByRole("tab", { name: "Priorities", exact: true }).click();
    await page.getByLabel("Include relationship history", { exact: true }).check();
    await expect(list.getByRole("listitem")).toHaveCount(3);
    await expect(list).toContainText("Withdrawn record");
    await expect(list.getByRole("button", { name: "Correct relationship", exact: true })).toHaveCount(0);
    await assertPatentControlsFit(page);
    await patentScreenshot(page, testInfo, `priority-withdrawal-history-${width}.png`);
    const parentState = await page.request.get(`${apiBaseUrl}/api/ip/patents/applications/${parent.id}`, { headers });
    expect((await parentState.json()).is_active).toBe(false);
    const childState = await page.request.get(`${apiBaseUrl}/api/ip/patents/applications/${child.id}`, { headers });
    expect(await childState.json()).toEqual(child);
    for (const unchanged of families) {
      const response = await page.request.get(`${apiBaseUrl}/api/ip/patents/families/${unchanged.id}`, { headers });
      expect(await response.json()).toEqual(unchanged);
    }
  });
}
