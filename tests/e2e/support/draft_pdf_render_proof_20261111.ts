import { expect, type Page } from "@playwright/test";

import { assessDraftPdf, collectDraftPdfPage, type DraftPdfPageProbe, type DraftPdfProfile, type DraftPdfSource } from "./draft_pdf_oracle_20261111";

export async function assertDraftPdfRender(page: Page, profile: DraftPdfProfile, source: DraftPdfSource) {
  await expect(page.getByTestId("draft-download-pdf")).toBeEnabled();
  await expect(page.locator("[data-testid=draft-pdf-preview] canvas")).toBeVisible();
  const pages = Number((await page.getByTestId("draft-pdf-pagination").innerText()).split(" of ")[1]);
  expect(Number.isInteger(pages) && pages >= 1 && pages <= 200, "Complete bounded PDF page inventory").toBe(true);
  const probes: DraftPdfPageProbe[] = [];
  for (let index = 1; index <= pages; index++) {
    await expect(page.getByTestId("draft-pdf-pagination")).toHaveText(`Page ${index} of ${pages}`);
    const region = page.getByRole("region", { name: "PDF page canvas" });
    await expect(region).toHaveAttribute("data-rendered-page", String(index));
    await expect(region).toHaveAttribute("data-text-page", String(index));
    await page.locator("[data-testid=draft-pdf-preview] canvas").scrollIntoViewIfNeeded();
    probes.push(await page.evaluate(collectDraftPdfPage));
    if (index < pages) await page.getByRole("button", { name: "Next PDF page" }).click();
  }
  const assessment = assessDraftPdf(probes, profile, source);
  // Boolean assertions keep private draft text out of test failure reports.
  expect(assessment.sourceComplete, "All persisted source text appears in order across printable pages").toBe(true);
  expect(assessment.titleComplete, "Persisted title appears in the PDF").toBe(true);
  expect(assessment.citationsComplete, "All recorded citation text appears after the source body").toBe(true);
  expect(assessment.pagination, "Every PDF page has the expected pagination").toBe(true);
  expect(assessment.paper && assessment.printableBounds, "Text stays within the selected preset's printable bounds").toBe(true);
  expect(assessment.contrast, "Every printable text run has visible high-contrast ink").toBe(true);
  return pages;
}
