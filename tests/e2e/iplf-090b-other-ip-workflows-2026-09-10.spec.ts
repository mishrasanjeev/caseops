import { createHash } from "node:crypto";
import { expect, test, type APIRequestContext, type Locator } from "@playwright/test";
import { noPaidProviderHeaders } from "./support/cost-controls";
import { apiBaseUrl, bootstrapPatentTenant, enablePatentWorkspace, existingPatentQa, patentRunId,
  patentScreenshot, signInPatentTenant } from "./support/patent-acceptance";
import { assertPatentControlsFit } from "./support/patent-layout";

test.use({ extraHTTPHeaders: noPaidProviderHeaders });

async function post(request: APIRequestContext, headers: Record<string, string>, path: string, data: unknown, status = 201) {
  const response = await request.post(`${apiBaseUrl}${path}`, { headers: { ...headers, "Idempotency-Key": crypto.randomUUID() }, data });
  expect(response.status(), await response.text()).toBe(status);
  return response.json();
}

async function chooseSource(form: Locator) {
  const source = form.getByLabel("Source document version", { exact: true });
  await expect(source.locator("option").nth(1)).toBeAttached();
  await source.selectOption({ index: 1 });
  await form.getByLabel("Page or locator", { exact: true }).fill("page 1");
}

for (const width of [393, 768, 1280]) {
  test(`IPLF-090B source-reported DES COPY LIC workflow subset at ${width}px`, async ({ page, request }, info) => {
    await page.setViewportSize({ width, height: 1000 });
    const tenant = await bootstrapPatentTenant(request);
    const headers = { ...await enablePatentWorkspace(request, tenant), ...noPaidProviderHeaders };
    if (!existingPatentQa) await post(request, headers, "/api/ip/document-taxonomy/seed", {}, 200);
    const contracts = await request.get(`${apiBaseUrl}/api/ip/specialist/contracts`, { headers });
    expect(contracts.status()).toBe(200);
    const definitions = await contracts.json();
    for (const domain of ["design", "copyright", "licensing"]) {
      const contract = definitions.find((row: { domain: string }) => row.domain === domain);
      expect(contract?.intake_available, domain).toBe(true);
      expect(contract.contract_version).toBe("OTHER-IP-2026-09-10.2");
    }
    const run = patentRunId();
    const client = await post(request, headers, "/api/clients", { name: `Other IP workflow ${run}`, client_type: "corporate" }, 200);
    await signInPatentTenant(page, tenant);
    for (const domain of ["design", "copyright", "licensing"]) {
      const details = domain === "design" ? { domain, applicant: "Applicant", article: "Casing" }
        : domain === "copyright" ? { domain, work_type_as_supplied: "Literary", author: "Author", claimant: "Claimant", ownership_claim: "Under review" }
          : { domain, grantor: "Owner", grantee: "Licensee", affected_rights_as_supplied: "Reproduction rights", territory: "As supplied" };
      const record = await post(request, headers, "/api/ip/specialist/records", { title: `${domain} ${run}`, client_id: client.id, jurisdiction_as_supplied: "As supplied", details });
      const content = Buffer.from(`Retained ${domain} source ${run}\n`.repeat(20));
      const uploaded = await request.post(`${apiBaseUrl}/api/ip/documents/upload`, { headers, multipart: {
        metadata_json: JSON.stringify({ taxonomy_key: "evidence", title: `${domain}-${run}.txt`, confidentiality: "restricted", asset_type: domain,
          links: [{ target_type: "docket", target_id: record.docket_id }] }),
        upload: { name: `${domain}-${run}.txt`, mimeType: "text/plain", buffer: content },
      } });
      expect(uploaded.status()).toBe(200);
      const upload = await uploaded.json();
      expect(upload.outcome).toBe("created");
      const pin = { document_id: upload.document.id, document_version_id: upload.document.versions[0].id,
        content_sha256: createHash("sha256").update(content).digest("hex"), locator: "page 1" };
      const base = `/api/ip/specialist/records/${record.id}/workflows`;
      const save = (facts: unknown, prior?: { id: string; version: number }) => post(request, headers, `${base}${prior ? `/${prior.id}/revisions` : ""}`, {
        expected_version: prior?.version ?? 0, expected_lifecycle_version: record.lifecycle_version, reason: "Retained source account", facts,
      }, prior ? 200 : 201);
      const set = await save({ kind: "source_set", purpose: domain === "design" ? "representations" : domain === "copyright" ? "deposit" : "instrument",
        title: `Source set ${run}`, members: [{ role: "Primary", source: pin }] });
      const common = { title: `Workflow ${domain} ${run}`, source_set: { id: set.id, version: set.version }, occurred_on: "2026-09-10", account: "Retained source account" };
      let workflow;
      if (domain === "licensing") {
        const facts = { ...common, kind: "licence", grantor: "Owner", grantee: "Licensee", transaction: "licence", exclusivity: "nonexclusive", rights: "Reproduction", territory: "As supplied",
          field_of_use: "Clause 1", sublicensing: "Clause 2", quality_control: "Clause 3", prosecution_control: "Clause 4", enforcement_control: "Clause 5", renewal_terms: "Clause 6", termination_terms: "Clause 7", notice_terms: "Clause 8", effective_from: "2026-01-01" };
        const draft = await save(facts);
        workflow = await save({ ...facts, status: "active", interpretation: "reviewed", review_reason: "Source clauses reviewed" }, draft);
      } else workflow = await save({ ...common, kind: domain === "design" ? "design_application" : "copyright_registration", registry: "Source registry", jurisdiction: "Source jurisdiction" });
      await page.goto(`/app/ip/specialist/${record.id}`);
      await page.getByRole("tab", { name: "workflows", exact: true }).click();
      await page.getByRole("list", { name: "Saved domain workflows" }).getByRole("listitem").filter({ hasText: common.title }).getByRole("button", { name: "Open", exact: true }).click();
      if (domain !== "licensing") {
        await page.getByLabel("identifier as supplied", { exact: true }).fill(`Application ${run}`);
        await page.getByLabel("stage", { exact: true }).selectOption("filed");
        await page.getByLabel("Revision reason").fill("Retained filing receipt");
        await page.getByRole("button", { name: "Save revision", exact: true }).click();
        await expect(page.getByRole("list", { name: "Saved domain workflows" })).toContainText("Version 2 / filed");
      } else {
        const obligation = page.getByRole("form", { name: "Contractual obligation", exact: true });
        await obligation.getByLabel("title", { exact: true }).fill(`Notice ${run}`);
        await obligation.getByLabel("Contractual due date as supplied").fill("2026-10-01");
        await chooseSource(obligation);
        await obligation.getByRole("button", { name: "Create obligation" }).click();
        await expect(page.getByRole("list", { name: "Saved obligations" })).toContainText(`Notice ${run}`);
        await page.getByRole("button", { name: "Performance history", exact: true }).click();
        const performance = page.getByRole("form", { name: "Record contract performance", exact: true });
        await performance.getByLabel("Performance date").fill("2026-09-10");
        await performance.getByLabel("Performance evidence account").fill(`Notice receipt ${run}`);
        await chooseSource(performance);
        await performance.getByRole("button", { name: "Record performance", exact: true }).click();
        await expect(page.getByRole("list", { name: "Saved obligations" })).toContainText("completed");
      }
      await expect(page.getByRole("main").getByRole("alert")).toHaveCount(0);
      await page.reload();
      await page.getByRole("tab", { name: "workflows", exact: true }).click();
      const savedRows = page.getByRole("list", { name: "Saved domain workflows" });
      await expect(savedRows).toContainText(common.title);
      if (domain === "licensing") {
        await savedRows.getByRole("listitem").filter({ hasText: common.title }).getByRole("button", { name: "Open", exact: true }).click();
        await expect(page.getByRole("list", { name: "Saved obligations" })).toContainText("2026-10-01 / completed");
        await page.getByRole("button", { name: "Performance history", exact: true }).click();
        await expect(page.getByRole("list", { name: "Performance evidence" })).toContainText(`Notice receipt ${run}`);
      } else await expect(savedRows).toContainText("Version 2 / filed");
      await assertPatentControlsFit(page);
      await expect(page.getByRole("main").getByRole("alert")).toHaveCount(0);
      await patentScreenshot(page, info, `workflow-${domain}-${width}.png`);
    }
  });
}
