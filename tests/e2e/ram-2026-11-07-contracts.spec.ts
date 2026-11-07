import { createHash } from "node:crypto";

import { expect, test } from "@playwright/test";
import JSZip from "jszip";

import { expectNoPageOverflow, json, markPositive, prepareTester } from "./support/ram-bugs4";
import { runId } from "./support/run-id";

test.use({ trace: "off", screenshot: "off", video: "off", storageState: { cookies: [], origins: [] } });

async function trackedTable() {
  const zip = new JSZip();
  zip.file("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>');
  zip.file("_rels/.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>');
  zip.file("word/document.xml", '<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Synthetic redline fixture. Not a legal agreement.</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:ins w:id="1" w:author="Synthetic reviewer" w:date="2026-11-07T00:00:00Z"><w:r><w:t>Inserted table text</w:t></w:r></w:ins></w:p></w:tc><w:tc><w:p><w:del w:id="2" w:author="Synthetic reviewer" w:date="2026-11-07T00:00:00Z"><w:r><w:delText>Deleted table text</w:delText></w:r></w:del></w:p></w:tc></w:tr></w:tbl><w:sectPr/></w:body></w:document>');
  return zip.generateAsync({ type: "nodebuffer" });
}

for (const mobile of [false, true]) {
  test(`${mobile ? "[mobile] " : ""}AI-CON-01 table-cell tracked changes retain source bytes and survive workspace reload`, async ({ page, request, baseURL }, info) => {
    const rt = await prepareTester(page, request, baseURL,
      mobile ? { width: 393, height: 851 } : { width: 1280, height: 900 });
    const run = runId();
    const title = `Synthetic redline QA ${run}`;
    const bytes = await trackedTable();
    const digest = createHash("sha256").update(bytes).digest("hex");
    const created = await json(await request.post(`${rt.api.origin}/api/contracts/`, {
      headers: rt.headers,
      data: { contract_code: `AI-CON-${run}`, title, counterparty_name: "Synthetic QA only",
        contract_type: "msa", status: "under_review" },
    }), "Fresh synthetic contract prerequisite");
    try {
      const attachment = await json(await request.post(`${rt.api.origin}/api/contracts/${created.id}/attachments`, {
        headers: rt.headers,
        multipart: { file: { name: `table-redline-${run}.docx`,
          mimeType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document", buffer: bytes } },
      }), "Retain the synthetic table DOCX");
      const download = await request.get(`${rt.api.origin}/api/contracts/${created.id}/attachments/${attachment.id}/download`, { headers: rt.headers });
      expect(download.status(), "Authorized original source bytes").toBe(200);
      expect(createHash("sha256").update(await download.body()).digest("hex")).toBe(digest);
      await page.goto(`${rt.web.origin}/app/contracts/${created.id}`);
      await expect(page.getByRole("heading", { name: title, exact: true })).toBeVisible();
      let first: unknown;
      for (let attempt = 0; attempt < 2; attempt += 1) {
        if (attempt) await page.reload();
        await page.getByRole("tab", { name: /^Attachments/ }).click();
        const open = page.waitForResponse(response =>
          new URL(response.url()).pathname === `/api/contracts/${created.id}/attachments/${attachment.id}/redline`);
        await page.getByTestId(`contract-attachment-redline-${attachment.id}`).click();
        const response = await open;
        expect(response.request().headers()["x-caseops-automated-test"]).toBe("no-paid-providers");
        const parsed = await json(response, "Real source-table redline parse");
        expect(parsed.insertion_count).toBe(1);
        expect(parsed.deletion_count).toBe(1);
        expect(parsed.changes.map((change: { text: string }) => change.text)).toEqual(["Inserted table text", "Deleted table text"]);
        expect(parsed.changes.every((change: { author: string }) => change.author === "Synthetic reviewer")).toBe(true);
        if (attempt) expect(parsed).toEqual(first);
        else first = parsed;
        await page.getByRole("tab", { name: "Redline", exact: true }).click();
        await expect(page.getByText("Inserted table text", { exact: true })).toBeVisible();
        await expect(page.getByText("Deleted table text", { exact: true })).toBeVisible();
        await expect(page.getByText("Clean document", { exact: true })).toHaveCount(0);
        if (mobile) await expectNoPageOverflow(page);
      }
      await rt.release();
      await markPositive(info, mobile ? "ai-b02-table-redline-mobile" : "ai-b02-table-redline", {
        local: rt.local, attachment_id: attachment.id, source_sha256: digest, reloaded: true,
      });
    } finally {
      await json(await request.patch(`${rt.api.origin}/api/contracts/${created.id}`, {
        headers: rt.headers, data: { status: "terminated" },
      }), "Retire only this journey's synthetic contract");
    }
  });
}
