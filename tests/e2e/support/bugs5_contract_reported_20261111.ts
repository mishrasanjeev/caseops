import { createHash } from "node:crypto";

import { expect, type APIRequestContext, type Page, type TestInfo } from "@playwright/test";

import type { components } from "../../../apps/web/lib/api/openapi-types";
import type { TesterRuntime } from "./ram-bugs4";

const reportedId = "a8220330-c668-4d51-b245-3468cd259cde";
type Workspace = components["schemas"]["ContractWorkspaceResponse"];

/** Production original-record proof is read-only; all writes use the run's separate fixture. */
export async function verifyReportedContractControls(
  page: Page, request: APIRequestContext, rt: TesterRuntime, info: TestInfo,
) {
  if (rt.local) return;
  let stage = "identity", mutations = 0;
  const prefix = `/api/contracts/${reportedId}`;
  const matcher = (url: URL) => url.origin === rt.api.origin
    && (url.pathname === prefix || url.pathname.startsWith(`${prefix}/`));
  const guard: Parameters<Page["route"]>[1] = async route => {
    if (route.request().method() !== "GET") {
      mutations++;
      await route.abort("blockedbyclient");
    } else await route.continue();
  };
  const read = async () => {
    const response = await request.get(`${rt.api.origin}${prefix}/workspace`, {
      headers: rt.headers, maxRetries: 0, maxRedirects: 0,
    });
    expect(response.status(), "Reported contract workspace read").toBe(200);
    return await response.json() as Workspace;
  };
  const snapshot = (workspace: Workspace) => JSON.stringify({
    contract: workspace.contract,
    attachments: workspace.attachments.map(row => ({ id: row.id, size: row.size_bytes, hash: row.sha256_hex,
      mime: row.content_type, status: row.processing_status })),
    terms: workspace.term_suggestions,
  });
  await page.route(matcher, guard);
  try {
    expect(rt.web.origin === "https://caseops.ai" && rt.api.origin === "https://api.caseops.ai"
      && rt.credentials.slug === "test-legal" && rt.credentials.email.toLowerCase() === "ram@testfirm.com",
    "Exact authorized reporting tenant and production origins").toBe(true);
    await rt.release();
    const before = await read();
    expect(before.contract.id === reportedId && before.contract.company_id === rt.actor.company.id,
      "Reported contract belongs to the reporting tenant").toBe(true);
    stage = "original-metadata-controls";
    await page.goto(`${rt.web.origin}/app/contracts/${reportedId}`);
    await page.getByRole("button", { name: "Edit contract", exact: true }).click();
    for (const [label, value] of [
      ["Contract title", before.contract.title], ["Counterparty", before.contract.counterparty_name],
      ["Legacy / other label", before.contract.contract_type_notes], ["Effective date", before.contract.effective_on],
      ["Expiry date", before.contract.expires_on], ["Renewal date", before.contract.renewal_on],
      ["Description", before.contract.summary],
    ] as const) {
      const control = page.getByLabel(label, { exact: true });
      await expect(control).toBeVisible();
      expect(await control.inputValue() === (value ?? ""), "Retained metadata populates the editor").toBe(true);
    }
    expect(await page.getByLabel("Contract type", { exact: true }).inputValue()
      === (before.contract.contract_type_key ?? "other"), "Retained canonical type populates the editor").toBe(true);
    expect(await page.getByLabel("Auto-renewal", { exact: true }).isChecked()
      === before.contract.auto_renewal, "Retained renewal policy populates the editor").toBe(true);
    await expect(page.getByRole("button", { name: "Save contract", exact: true })).toBeDisabled();
    await page.getByRole("button", { name: "Cancel", exact: true }).click();

    stage = "original-indexed-pdf-preview";
    const attachment = before.attachments.find(row => row.processing_status === "indexed"
      && row.original_filename.toLowerCase().endsWith(".pdf")
      && row.content_type?.split(";", 1)[0].trim().toLowerCase() === "application/pdf");
    if (!attachment || !/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(attachment.id)) {
      throw new Error("Reported contract lacks its indexed source identity.");
    }
    await page.getByRole("tab", { name: /^Attachments/ }).click();
    const rows = page.getByRole("tabpanel").getByRole("listitem");
    await expect(rows).toHaveCount(before.attachments.length);
    const href = `/app/contracts/${reportedId}/attachments/${attachment.id}/view`;
    const view = page.getByRole("tabpanel").getByRole("link", { name: "View document", exact: true })
      .and(page.locator(`a[href="${href}"]`));
    await expect(view).toHaveCount(1);
    expect(await view.getAttribute("href") === href,
      "Visible source action is bound to the exact attachment").toBe(true);
    const preview = page.waitForResponse(response => new URL(response.url()).origin === rt.api.origin
      && new URL(response.url()).pathname === `${prefix}/attachments/${attachment.id}/preview`
      && response.request().method() === "GET");
    await view.click();
    const response = await preview;
    expect(response.status(), "Original source preview admission").toBe(200);
    expect(response.request().headers()["x-caseops-automated-test"]).toBe("no-paid-providers");
    const bytes = await response.body();
    expect(bytes.length === attachment.size_bytes
      && createHash("sha256").update(bytes).digest("hex") === attachment.sha256_hex,
    "Original preview is the retained source, without writing private bytes to evidence").toBe(true);
    const canvas = page.getByTestId("pdf-viewer").locator("canvas");
    await expect(canvas).toBeVisible();
    await expect.poll(() => canvas.evaluate((element: HTMLCanvasElement) => {
      const pixels = element.getContext("2d")!.getImageData(0, 0, element.width, element.height).data;
      let ink = 0;
      for (let i = 0; i < pixels.length; i += 4) if (pixels[i] < 180 && pixels[i + 1] < 180 && pixels[i + 2] < 180) ink++;
      return ink;
    }), { message: "Original indexed source visibly renders" }).toBeGreaterThan(100);

    stage = "original-manual-term-controls";
    await page.goto(`${rt.web.origin}/app/contracts/${reportedId}`);
    await page.getByRole("tab", { name: "Terms", exact: true }).click();
    const terms = page.getByRole("tabpanel");
    await terms.getByRole("button", { name: "Add term suggestion", exact: true }).click();
    for (const label of ["Suggested effective date", "Suggested expiry date", "Suggested renewal date",
      "Suggested duration (months)", "Source document", "Source evidence"]) {
      await expect(terms.getByLabel(label, { exact: true })).toBeVisible();
    }
    await expect(terms.getByRole("button", { name: "Save suggestion", exact: true })).toBeDisabled();
    await terms.getByRole("button", { name: "Cancel", exact: true }).click();
    stage = "unchanged-source";
    expect(snapshot(await read()) === snapshot(before), "Original contract, source and terms remain unchanged").toBe(true);
    expect(mutations, "No reported-record mutation was attempted").toBe(0);
    await rt.release();
    info.annotations.push({ type: "caseops-b5-reported-record", description: "original-contract-readonly-controls-and-pdf; no record changes or retained private media" });
  } catch {
    throw new Error(`B5 original-contract read-only acceptance failed at ${stage}; private values omitted.`);
  } finally {
    await page.unroute(matcher, guard);
  }
}
