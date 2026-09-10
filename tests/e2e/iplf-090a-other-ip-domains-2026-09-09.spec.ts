import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { expect, test, type Page } from "@playwright/test";
import { noPaidProviderHeaders } from "./support/cost-controls";
import { apiBaseUrl, bootstrapPatentTenant, enablePatentWorkspace, existingPatentQa, patentRunId,
  patentScreenshot, signInPatentTenant } from "./support/patent-acceptance";
import { assertPatentControlsFit } from "./support/patent-layout";

test.use({ extraHTTPHeaders: noPaidProviderHeaders });

const domains = ["design", "copyright", "domain_name", "licensing", "enforcement",
  "geographical_indication", "plant_variety", "semiconductor_layout", "trade_secret", "customs_enforcement"];
type Field = { key: string; label: string; kind: string; required: boolean };

async function lifecycle(page: Page, active: boolean, version: number) {
  await page.getByRole("tab", { name: "lifecycle", exact: true }).click();
  await page.getByLabel("Effective date and time").fill("2026-09-09T10:00");
  await page.getByLabel("Lifecycle reason", { exact: true }).fill(active
    ? "Client closed the specialist instruction." : "Client expressly instructed a controlled reopening.");
  await page.getByLabel("Instruction or evidence reference").fill("qa:retained-specialist-instruction");
  await page.getByRole("button", { name: active ? "Preview closure" : "Preview reopening", exact: true }).click();
  const confirmation = page.getByLabel("I confirm this lifecycle change and its recorded impacts.");
  await expect(confirmation).toBeVisible();
  for (const checkbox of await page.getByLabel(/^Reviewed exception:/).all()) await checkbox.check();
  await confirmation.check();
  await assertPatentControlsFit(page);
  await page.getByRole("button", { name: "Confirm lifecycle change", exact: true }).click();
  await expect(page.getByText(`${active ? "closed" : "ready"} / Lifecycle version ${version}`, { exact: true })).toBeVisible();
  await expect(page.getByRole("alert")).toHaveCount(0);
}

for (const width of [393, 768, 1280]) {
  test(`OTHER-IP-090-091 independent source journeys at ${width}px`, async ({ page, request }, info) => {
    await page.setViewportSize({ width, height: 1000 });
    const tenant = await bootstrapPatentTenant(request);
    const headers = { ...await enablePatentWorkspace(request, tenant), ...noPaidProviderHeaders };
    if (!existingPatentQa) {
      const taxonomySeed = await request.post(`${apiBaseUrl}/api/ip/document-taxonomy/seed`, { headers });
      expect(taxonomySeed.status()).toBe(200);
    }
    const runId = patentRunId();
    const clientResponse = await request.post(`${apiBaseUrl}/api/clients`, {
      headers, data: { name: `Specialist acceptance ${runId}`, client_type: "corporate" },
    });
    expect(clientResponse.status()).toBe(200);
    const client = await clientResponse.json();
    const contractResponse = await request.get(`${apiBaseUrl}/api/ip/specialist/contracts`, { headers });
    expect(contractResponse.status()).toBe(200);
    const contracts = await contractResponse.json();
    expect(contracts.map((row: { domain: string }) => row.domain).sort()).toEqual([...domains].sort());
    // This gate must fail when parent registration is absent; no availability skip.
    for (const contract of contracts) expect(contract.intake_available, contract.domain).toBe(true);
    await signInPatentTenant(page, tenant);

    for (const domain of domains) {
      const contract = contracts.find((row: { domain: string }) => row.domain === domain);
      const title = `${contract.label} ${runId}`;
      await page.goto("/app/ip");
      await page.getByRole("link", { name: "Specialist IP intake", exact: true }).click();
      await page.getByLabel("Domain", { exact: true }).selectOption(domain);
      await page.getByRole("button", { name: "New intake", exact: true }).click();
      await page.getByLabel("Title", { exact: true }).fill(title);
      await page.getByLabel("Client", { exact: true }).selectOption(client.id);
      await page.getByLabel("Jurisdiction as supplied").fill("India - user supplied, unreviewed");
      for (const field of contract.fields as Field[]) {
        if (field.required && ["text", "textarea"].includes(field.kind)) {
          await page.locator(`#specialist-${field.key}`).fill(`${field.label} retained instruction ${runId}`);
        }
      }
      await assertPatentControlsFit(page);
      const savedResponse = page.waitForResponse((response) => response.url().endsWith("/api/ip/specialist/records") && response.request().method() === "POST");
      await page.getByRole("button", { name: "Save intake", exact: true }).click();
      const response = await savedResponse;
      expect(response.status()).toBe(201);
      const record = await response.json();
      expect(record.facts.details.domain).toBe(domain);
      await expect(page.getByRole("heading", { name: title, exact: true })).toBeVisible();
      await expect(page.getByRole("alert")).toHaveCount(0);
      await page.reload();
      await expect(page.getByRole("heading", { name: title, exact: true })).toBeVisible();
      await expect(page.getByLabel("Saved intake facts")).toContainText("India - user supplied, unreviewed");
      await assertPatentControlsFit(page);
      await patentScreenshot(page, info, `${domain}-${width}.png`);

      if (domain !== "design") continue;
      await page.getByRole("tab", { name: "evidence", exact: true }).click();
      const bytes = Buffer.from(`Private acceptance source ${runId}. No legal determination.\n`.repeat(20));
      await page.getByLabel("Evidence file", { exact: true }).setInputFiles({ name: `${runId}.txt`, mimeType: "text/plain", buffer: bytes });
      const taxonomy = page.getByLabel("Document type", { exact: true });
      await expect(taxonomy.locator("option").nth(1)).toBeAttached();
      await taxonomy.selectOption({ index: 1 });
      await page.getByRole("button", { name: "Upload evidence", exact: true }).click();
      const source = page.getByLabel("Source version", { exact: true });
      await expect(source.locator("option").nth(1)).toBeAttached();
      await source.selectOption({ index: 1 });
      await page.getByLabel("Observation type").selectOption(contract.observation_kinds[0]);
      await page.getByLabel("Event date as recorded").fill("2026-09-09");
      await page.getByLabel("Source page or locator").fill("page 1");
      const account = `Source-backed instruction ${runId}`;
      await page.getByLabel("Source account").fill(account);
      await page.getByRole("button", { name: "Record observation", exact: true }).click();
      await expect(page.getByLabel("Specialist source history")).toContainText(account);
      await expect(page.getByRole("alert")).toHaveCount(0);
      await page.reload();
      await page.getByRole("tab", { name: "evidence", exact: true }).click();
      await expect(page.getByLabel("Specialist source history")).toContainText("Legal effect not determined");
      await lifecycle(page, true, 1);
      await lifecycle(page, false, 2);
      await lifecycle(page, true, 3);
      await page.reload();
      await page.getByRole("tab", { name: "evidence", exact: true }).click();
      await expect(page.getByRole("form", { name: "Record source observation" })).toHaveCount(0);
      await expect(page.getByRole("button", { name: "Upload evidence" })).toHaveCount(0);
      await expect(page.getByLabel("Specialist source history")).toContainText(account);
      const downloaded = page.waitForEvent("download");
      await page.getByRole("button", { name: "Source version", exact: true }).click();
      const download = await downloaded;
      const path = await download.path();
      expect(path).not.toBeNull();
      expect(createHash("sha256").update(await readFile(path!)).digest("hex"))
        .toBe(createHash("sha256").update(bytes).digest("hex"));
      await expect(page.getByRole("alert")).toHaveCount(0);
      await assertPatentControlsFit(page);
      await patentScreenshot(page, info, `design-closed-source-${width}.png`);
    }
  });
}
