import { createHash, randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";
import { expect, test } from "@playwright/test";
import { apiBaseUrl, patentRunId, patentScreenshot } from "./support/patent-acceptance";
import { noPaidProviderHeaders } from "./support/cost-controls";
import {
  bootstrapPatentTenant, enablePatentWorkspace,
  signInPatentTenant,
} from "./support/patent-acceptance";

test.use({ extraHTTPHeaders: noPaidProviderHeaders });

// PAT-01 / IPLF-080-ACCESS: a source pin must own a canonical restricted document link.
test("IPLF-080 source pin creates its governed document scope without changing the trademark", async ({ page }, testInfo) => {
  const run = patentRunId();
  const tenant = await bootstrapPatentTenant(page.request);
  const headers = { ...await enablePatentWorkspace(page.request, tenant), ...noPaidProviderHeaders };
  const clientResponse = await page.request.post(`${apiBaseUrl}/api/clients`, {
    headers, data: { name: `Source scope client ${run}`, client_type: "corporate" },
  });
  expect(clientResponse.status(), await clientResponse.text()).toBe(200);
  const trademarkResponse = await page.request.post(`${apiBaseUrl}/api/ip/dockets`, {
    headers, data: {
      title: `Existing trademark ${run}`, restricted: false,
      particulars: {
        form_key: "TM-A", form_version: "2026.1", mark_kind: "word",
        representation: { text: "EXISTING", evidence_reference: "fixture:existing" },
        classes: [{ class_number: 9, specification: "Software" }],
        parties: [{ role: "applicant", name: `Source scope client ${run}` }],
        use_priority: null, agent: null,
        filing_manifest: [{ key: "representation", label: "Mark representation", required: true,
          evidence_reference: "fixture:existing" }],
      },
    },
  });
  expect(trademarkResponse.status(), await trademarkResponse.text()).toBe(201);
  const trademark = await trademarkResponse.json();
  const taxonomy = await page.request.post(`${apiBaseUrl}/api/ip/document-taxonomy/seed`, { headers });
  expect(taxonomy.status(), await taxonomy.text()).toBe(200);
  const upload = await page.request.post(`${apiBaseUrl}/api/ip/documents/upload`, {
    headers, multipart: {
      metadata_json: JSON.stringify({ taxonomy_key: "evidence", title: "Imported inventor source",
        confidentiality: "internal", is_privileged: false, client_code: "SCOPE",
        asset_type: "Trademark", mark: "EXISTING", jurisdiction: "IN", document_date: "2026-09-05",
        links: [{ target_type: "docket", target_id: trademark.id }] }),
      upload: { name: "inventor-source.txt", mimeType: "text/plain",
        buffer: Buffer.from(`Synthetic unpublished invention source. ${run} `.repeat(25)) },
    },
  });
  expect(upload.status(), await upload.text()).toBe(200);
  const uploaded = await upload.json();
  expect(uploaded.outcome).toBe("created");
  const document = uploaded.document;
  expect(document).not.toBeNull();
  const sourceVersion = document.versions[0];
  const key = randomUUID();
  const facts = {
    title: `Source-scoped disclosure ${run}`, client_id: (await clientResponse.json()).id,
    disclosure_date: "2026-09-05", disclosure_narrative: "Restricted inventor disclosure.",
    source: { kind: "document_version", document_id: document.id,
      document_version_id: sourceVersion.id, content_sha256: sourceVersion.sha256_hex },
  };
  const created = await page.request.post(`${apiBaseUrl}/api/ip/patents/families`, {
    headers: { ...headers, "Idempotency-Key": key }, data: facts,
  });
  expect(created.status(), await created.text()).toBe(201);
  const family = await created.json();
  const replay = await page.request.post(`${apiBaseUrl}/api/ip/patents/families`, {
    headers: { ...headers, "Idempotency-Key": key }, data: facts,
  });
  expect(replay.status(), await replay.text()).toBe(201);
  expect((await replay.json()).id).toBe(family.id);
  const linked = await page.request.get(`${apiBaseUrl}/api/ip/documents/${document.id}`, { headers });
  expect(linked.status(), await linked.text()).toBe(200);
  const links = (await linked.json()).links;
  expect(links.filter((link: { target_id: string }) => link.target_id === family.docket_id)).toHaveLength(1);
  expect(links.some((link: { target_id: string }) => link.target_id === trademark.id)).toBe(true);
  const retained = await page.request.get(`${apiBaseUrl}/api/ip/dockets/${trademark.id}`, { headers });
  expect(retained.status(), await retained.text()).toBe(200);
  expect(trademark.current_particulars).toBeTruthy();
  expect((await retained.json()).current_particulars).toEqual(trademark.current_particulars);
  await signInPatentTenant(page, tenant);
  await page.setViewportSize({ width: 393, height: 900 });
  await page.goto(`/app/ip/patents/${family.id}`);
  await expect(page.getByRole("heading", { level: 1, name: `Source-scoped disclosure ${run}` })).toBeVisible();
  await expect(page.getByRole("button", { name: "Download source version" })).toBeVisible();
  await page.getByRole("tab", { name: "Documents", exact: true }).click();
  expect(sourceVersion.display_name).toBeTruthy();
  const sourceCard = page.getByRole("article").filter({ hasText: sourceVersion.display_name });
  await expect(sourceCard.getByText(sourceVersion.display_name, { exact: true })).toBeVisible();
  await sourceCard.scrollIntoViewIfNeeded();
  const downloadButton = sourceCard.getByRole("button", { name: "Download original" });
  await expect(downloadButton).toBeInViewport({ ratio: 1 });
  const downloading = page.waitForEvent("download");
  await downloadButton.click();
  const download = await downloading;
  const file = await download.path();
  expect(file).toBeTruthy();
  expect(createHash("sha256").update(await readFile(file!)).digest("hex")).toBe(sourceVersion.sha256_hex);
  await patentScreenshot(page, testInfo, "patent-source-scope-393.png");
  await page.reload();
  await expect(page.getByRole("button", { name: "Download source version" })).toBeVisible();
});
