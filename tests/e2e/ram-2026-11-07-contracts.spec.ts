import { createHash } from "node:crypto";

import { expect, test } from "@playwright/test";
import { loadJSZip } from "./support/external-journey-loaders";

import { expectNoPageOverflow, json, markPositive, prepareTester } from "./support/ram-bugs4";
import { runId } from "./support/run-id";

test.use({ trace: "off", screenshot: "off", video: "off", storageState: { cookies: [], origins: [] } });

async function trackedTable() {
  const zip = new (loadJSZip())();
  zip.file("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>');
  zip.file("_rels/.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>');
  zip.file("word/document.xml", `<?xml version="1.0"?>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:v="urn:schemas-microsoft-com:vml">
      <w:body>
        <w:p><w:r><w:t>Synthetic redline fixture. Not a legal agreement.</w:t></w:r></w:p>
        <w:tbl><w:tr>
          <w:tc><w:p>
            <w:ins w:id="1" w:author="Synthetic reviewer" w:date="2026-11-07T00:00:00Z">
              <w:r><w:t xml:space="preserve">Inserted table </w:t></w:r>
              <w:r><w:pict><v:shape><v:textbox><w:txbxContent><w:p>
                <w:r><w:t>Unchanged text box text</w:t></w:r>
                <w:del w:id="2" w:author="Text box reviewer" w:date="2026-11-07T01:00:00Z">
                  <w:r><w:delText>Deleted text box text</w:delText></w:r>
                </w:del>
              </w:p></w:txbxContent></v:textbox></v:shape></w:pict></w:r>
              <w:r><w:t>text</w:t></w:r>
            </w:ins>
          </w:p></w:tc>
          <w:tc><w:p>
            <w:del w:id="3" w:author="Synthetic reviewer" w:date="2026-11-07T00:00:00Z">
              <w:r><w:delText>Deleted table text</w:delText></w:r>
            </w:del>
          </w:p></w:tc>
        </w:tr></w:tbl>
        <w:sectPr/>
      </w:body>
    </w:document>`);
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
      const expectOriginalBytes = async () => {
        const download = await request.get(`${rt.api.origin}/api/contracts/${created.id}/attachments/${attachment.id}/download`, { headers: rt.headers });
        expect(download.status(), "Authorized original source bytes").toBe(200);
        expect(createHash("sha256").update(await download.body()).digest("hex")).toBe(digest);
      };
      await expectOriginalBytes();
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
        expect(parsed.paragraph_count).toBe(4);
        expect(parsed.insertion_count).toBe(1);
        expect(parsed.deletion_count).toBe(2);
        expect(parsed.author_counts).toEqual({ "Synthetic reviewer": 2, "Text box reviewer": 1 });
        expect(parsed.changes).toEqual([
          { index: 1, paragraph_index: 1, kind: "insertion", text: "Inserted table text", author: "Synthetic reviewer",
            timestamp: "2026-11-07T00:00:00+00:00", context_before: "", context_after: "" },
          { index: 2, paragraph_index: 2, kind: "deletion", text: "Deleted text box text", author: "Text box reviewer",
            timestamp: "2026-11-07T01:00:00+00:00", context_before: "", context_after: "" },
          { index: 3, paragraph_index: 3, kind: "deletion", text: "Deleted table text", author: "Synthetic reviewer",
            timestamp: "2026-11-07T00:00:00+00:00", context_before: "", context_after: "" },
        ]);
        if (attempt) expect(parsed).toEqual(first);
        else first = parsed;
        await page.getByRole("tab", { name: "Redline", exact: true }).click();
        const panel = page.getByRole("tabpanel", { name: "Redline" });
        const rows = panel.getByRole("listitem");
        await expect(rows).toHaveCount(3);
        for (const [i, text, author] of [
          [0, "Inserted table text", "Synthetic reviewer"],
          [1, "Deleted text box text", "Text box reviewer"],
          [2, "Deleted table text", "Synthetic reviewer"],
        ] as const) {
          await expect(rows.nth(i).getByText(text, { exact: true })).toBeVisible();
          await expect(rows.nth(i).getByText(`by ${author}`, { exact: true })).toBeVisible();
        }
        await expect(panel.getByText("Unchanged text box text")).toHaveCount(0);
        await expect(panel.getByText("Clean document", { exact: true })).toHaveCount(0);
        if (mobile) await expectNoPageOverflow(page);
      }
      await expectOriginalBytes();
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
