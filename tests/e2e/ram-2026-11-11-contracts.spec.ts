import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";

import { expect, test } from "@playwright/test";
import JSZip from "jszip";

import { expectNoPageOverflow, json, prepareTester } from "./support/ram-bugs4";
import { repoRoot } from "./support/env";
import { runId } from "./support/run-id";
import { verifyReportedContractControls } from "./support/bugs5_contract_reported_20261111";

test.use({ trace: "off", screenshot: "off", video: "off", storageState: { cookies: [], origins: [] } });

async function syntheticDocx() {
  const zip = new JSZip();
  zip.file("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>');
  zip.file("_rels/.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>');
  zip.file("word/document.xml", '<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Synthetic QA source, not a legal agreement. Effective on 15 November 2026. Expires on 14 November 2027. Renewal on 1 October 2027.</w:t></w:r></w:p><w:p><w:r><w:br w:type="page"/></w:r></w:p><w:p><w:r><w:t>Synthetic source page two.</w:t></w:r></w:p><w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440" w:bottom="1440" w:left="1440" w:right="1440"/></w:sectPr></w:body></w:document>');
  return zip.generateAsync({ type: "nodebuffer" });
}

for (const mobile of [false, true]) {
  test(`${mobile ? "[mobile] " : ""}B5-CON-005-006-009 metadata, private previews and reviewed terms persist`, {
    annotation: { type: "caseops-b5-proof", description: "workflow-outcome" },
  }, async ({ page, request, baseURL }, info) => {
    test.setTimeout(240_000);
    const rt = await prepareTester(page, request, baseURL, mobile ? { width: 393, height: 851 } : { width: 1366, height: 900 });
    await verifyReportedContractControls(page, request, rt, info);
    const title = `Synthetic contract B5 ${runId()}`;
    await page.goto(`${rt.web.origin}/app/contracts`);
    const repositoryHeader = page.getByRole("main").locator("header").filter({
      has: page.getByRole("heading", { name: "Contract repository", exact: true }),
    });
    await expect(repositoryHeader.getByTestId("new-contract-trigger")).toBeVisible();
    await repositoryHeader.getByTestId("new-contract-trigger").click();
    await page.getByLabel("Title", { exact: true }).fill(title);
    await page.getByLabel("Code", { exact: true }).fill(`B5-${runId()}`);
    await page.getByRole("button", { name: "Create contract", exact: true }).click();
    await page.waitForURL(/\/app\/contracts\/[^/]+\/?$/);
    const contractId = new URL(page.url()).pathname.split("/").filter(Boolean).at(-1)!;
    const apiPath = `${rt.api.origin}/api/contracts/${contractId}`;
    const details = { title: `${title} corrected`, counterparty_name: "Synthetic corrected supplier",
      contract_type: "Lease", contract_type_key: "lease", contract_type_notes: "Synthetic reviewed classification",
      effective_on: "2026-11-01", expires_on: "2027-10-31", renewal_on: "2027-09-01", auto_renewal: true,
      summary: "Synthetic corrected description, not legal advice." };
    try {
      await page.getByRole("button", { name: "Edit contract", exact: true }).click();
      for (const [label, value] of [["Contract title", details.title], ["Counterparty", details.counterparty_name],
        ["Legacy / other label", details.contract_type_notes], ["Effective date", details.effective_on],
        ["Expiry date", details.expires_on], ["Renewal date", details.renewal_on], ["Description", details.summary]]) {
        await page.getByLabel(label, { exact: true }).fill(value);
      }
      await page.getByLabel("Contract type", { exact: true }).selectOption("lease");
      await page.getByLabel("Auto-renewal", { exact: true }).check();
      const save = page.waitForResponse((r) => r.url() === `${apiPath}/metadata` && r.request().method() === "PATCH");
      await page.getByRole("button", { name: "Save contract", exact: true }).click();
      const saved = await json(await save, "Metadata save");
      expect(saved).toMatchObject(details);
      await page.reload();
      await expect(page.getByRole("heading", { name: details.title, exact: true })).toBeVisible();
      const stalePage = await page.context().newPage();
      await stalePage.setExtraHTTPHeaders({ "X-CaseOps-Automated-Test": "no-paid-providers" });
      try {
        await stalePage.goto(`${rt.web.origin}/app/contracts/${contractId}`);
        await stalePage.getByRole("button", { name: "Edit contract", exact: true }).click();
        await stalePage.getByLabel("Contract title", { exact: true }).fill("Synthetic stale title must not persist");
        await page.getByRole("button", { name: "Edit contract", exact: true }).click();
        await page.getByLabel("Description", { exact: true }).fill(`${details.summary} Reviewed.`);
        await page.getByRole("button", { name: "Save contract", exact: true }).click();
        await expect(page.getByRole("button", { name: "Edit contract", exact: true })).toBeVisible();
        const staleSave = stalePage.waitForResponse((r) => r.url() === `${apiPath}/metadata` && r.request().method() === "PATCH");
        await stalePage.getByRole("button", { name: "Save contract", exact: true }).click();
        expect((await staleSave).status()).toBe(409);
        await expect(stalePage.getByRole("region", { name: "Contract details", exact: true })
          .getByRole("alert")).toContainText("Reload before saving");
        await stalePage.getByRole("button", { name: "Reload contract", exact: true }).click();
        await expect(stalePage.getByRole("heading", { name: details.title, exact: true })).toBeVisible();
      } finally { await stalePage.close(); }
      await page.getByRole("tab", { name: "Terms", exact: true }).click();
      const terms = page.getByRole("tabpanel");
      await expect(terms.getByRole("heading", { name: "Canonical terms", exact: true })).toBeVisible();
      await expect(terms.getByText(details.effective_on, { exact: true })).toBeVisible();
      await expect(terms.getByRole("heading", { name: "Term suggestions (0)", exact: true })).toBeVisible();

      const sources = [
        { name: "synthetic-terms.docx", mimeType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document", buffer: await syntheticDocx() },
        { name: "public-source.pdf", mimeType: "application/pdf", buffer: await readFile(path.join(repoRoot, "tests/fixtures/statutes/official/contract-1872.pdf")) },
      ];
      let docxId = "";
      for (const source of sources) {
        await page.getByRole("tab", { name: /^Attachments/ }).click();
        const uploading = page.waitForResponse((r) => r.url() === `${apiPath}/attachments` && r.request().method() === "POST");
        await page.getByTestId("contract-attachment-input").setInputFiles(source);
        const attachment = await json(await uploading, "Private contract upload");
        if (source.name.endsWith(".docx")) docxId = attachment.id;
        const row = page.getByRole("listitem").filter({ hasText: source.name });
        await row.getByRole("link", { name: "View document", exact: true }).click();
        await expect(page.getByRole("heading", { name: source.name, exact: true })).toBeVisible();
        if (source.name.endsWith(".docx")) {
          await expect(page.frameLocator('[data-testid="docx-preview-frame"]').getByText(/Synthetic QA source, not a legal agreement/)).toBeVisible();
          await expect(page.frameLocator('[data-testid="docx-preview-frame"]').locator("section.docx")).toHaveCount(2);
        } else {
          await expect(page.getByTestId("pdf-open-original")).toHaveCount(0);
          await expect(page.getByTestId("pdf-download-original")).toHaveCount(0);
          const canvas = page.getByTestId("pdf-viewer").locator("canvas");
          await expect(canvas).toBeVisible();
          await expect.poll(() => canvas.evaluate((node: HTMLCanvasElement) => {
            const pixels = node.getContext("2d")!.getImageData(0, 0, node.width, node.height).data;
            let ink = 0;
            for (let i = 0; i < pixels.length; i += 4) if (pixels[i] < 180 && pixels[i + 1] < 180 && pixels[i + 2] < 180) ink += 1;
            return ink;
          })).toBeGreaterThan(100);
          await page.getByRole("button", { name: "Next page", exact: true }).click();
          await expect(page.getByRole("spinbutton", { name: "Page number" })).toHaveValue("2");
        }
        await page.getByRole("button", { name: "Zoom in", exact: true }).click();
        await page.getByRole("button", { name: "Zoom out", exact: true }).click();
        const downloading = page.waitForResponse((r) => r.url() === `${apiPath}/attachments/${attachment.id}/download`);
        const fileDownload = page.waitForEvent("download");
        await page.getByRole("button", { name: "Download original", exact: true }).click();
        const original = await downloading;
        expect(original.status()).toBe(200);
        expect(createHash("sha256").update(await original.body()).digest("hex")).toBe(createHash("sha256").update(source.buffer).digest("hex"));
        expect((await fileDownload).suggestedFilename()).toBe(source.name);
        await expectNoPageOverflow(page);
        await page.getByRole("link", { name: "Back to contract", exact: true }).click();
      }

      await page.getByRole("tab", { name: "Terms", exact: true }).click();
      await page.getByRole("button", { name: "Add term suggestion", exact: true }).click();
      await page.getByLabel("Suggested effective date", { exact: true }).fill("2026-11-15");
      await page.getByLabel("Suggested expiry date", { exact: true }).fill("2027-11-14");
      await page.getByLabel("Suggested renewal date", { exact: true }).fill("2027-10-01");
      await page.getByLabel("Suggested duration (months)", { exact: true }).fill("12");
      await page.getByLabel("Source document", { exact: true }).selectOption(docxId);
      await page.getByLabel("Source evidence", { exact: true }).fill("Effective on 15 November 2026. Expires on 14 November 2027. Renewal on 1 October 2027.");
      await page.getByRole("button", { name: "Save suggestion", exact: true }).click();
      await expect(page.getByRole("heading", { name: "Term suggestions (1)", exact: true })).toBeVisible();
      expect((await json(await request.get(apiPath, { headers: rt.headers }), "Canonical terms before acceptance")).effective_on).toBe(details.effective_on);
      const accepting = page.waitForResponse((r) => r.url().startsWith(`${apiPath}/term-suggestions/`) && r.url().endsWith("/accept") && r.request().method() === "POST");
      await page.getByRole("button", { name: "Accept", exact: true }).click();
      expect((await json(await accepting, "Review term suggestion")).status).toBe("accepted");
      await expect(page.getByRole("tabpanel").getByText("2026-11-15", { exact: true }).first()).toBeVisible();
      await page.reload();
      await page.getByRole("tab", { name: "Terms", exact: true }).click();
      expect(await json(await request.get(apiPath, { headers: rt.headers }), "Accepted term persistence")).toMatchObject({
        effective_on: "2026-11-15", expires_on: "2027-11-14", renewal_on: "2027-10-01", auto_renewal: true,
      });
      await page.getByRole("button", { name: "Add term suggestion", exact: true }).click();
      await page.getByLabel("Suggested renewal date", { exact: true }).fill("2028-10-01");
      await page.getByRole("button", { name: "Save suggestion", exact: true }).click();
      await expect(page.getByRole("heading", { name: "Term suggestions (2)", exact: true })).toBeVisible();
      const rejecting = page.waitForResponse((r) => r.url().startsWith(`${apiPath}/term-suggestions/`) && r.url().endsWith("/reject") && r.request().method() === "POST");
      await page.getByRole("button", { name: "Reject", exact: true }).click();
      expect((await json(await rejecting, "Reject ungrounded manual suggestion")).status).toBe("rejected");
      await page.reload();
      await page.getByRole("tab", { name: "Terms", exact: true }).click();
      expect((await json(await request.get(apiPath, { headers: rt.headers }), "Rejected term retains canonical renewal")).renewal_on).toBe("2027-10-01");
      await expectNoPageOverflow(page);
      if (rt.local) await page.screenshot({ path: info.outputPath(`contract-terms-${mobile ? "mobile" : "desktop"}.png`) });
      await rt.release();
    } finally {
      await json(await request.patch(apiPath, { headers: rt.headers, data: { status: "terminated" } }), "Retire only the new synthetic QA contract");
    }
  });
}
