/**
 * Hari 2026-07-02 production regression.
 *
 * Runs against the deployed site using the dedicated QA tenant from
 * playwright.prod-ram.config.ts. The manual release check for this work used
 * the tester-provided Hari account; this committed spec stays on the QA tenant
 * so GitHub Actions can run it without storing tester credentials in code.
 */
import { expect, test } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import type { Page } from "@playwright/test";

const PROD_BASE_URL =
  (process.env.PROD_BASE_URL ?? "").trim() || "https://caseops.ai";
const PROD_API_BASE_URL =
  (process.env.PROD_API_BASE_URL ?? "").trim() || "https://api.caseops.ai";

async function authHeaders(page: Page): Promise<Record<string, string>> {
  const cookies = await page.context().cookies([PROD_BASE_URL, PROD_API_BASE_URL]);
  const cookieHeader = cookies
    .filter((cookie) => cookie.domain.includes("caseops.ai"))
    .map((cookie) => `${cookie.name}=${cookie.value}`)
    .join("; ");
  const csrf =
    cookies.find((cookie) => cookie.name === "caseops_csrf")?.value ?? "";
  return {
    Accept: "application/json",
    Cookie: cookieHeader,
    "Content-Type": "application/json",
    "X-CSRF-Token": csrf,
  };
}

async function createMatter(
  page: Page,
): Promise<{ matterId: string; matterCode: string }> {
  const matterCode = `H702-PROD-${Date.now().toString().slice(-8)}`;
  const response = await page.context().request.post(
    `${PROD_API_BASE_URL}/api/matters/`,
    {
      headers: await authHeaders(page),
      data: {
        title: `Hari 2026-07-02 prod notice probe ${matterCode}`,
        matter_code: matterCode,
        practice_area: "criminal",
        forum_level: "high_court",
        status: "intake",
        court_name: "Delhi High Court",
      },
    },
  );
  expect(
    response.status(),
    `matter create expected 200, got ${response.status()} ${await response.text()}`,
  ).toBe(200);
  const payload = (await response.json()) as { id?: string };
  expect(payload.id).toBeTruthy();
  return { matterId: payload.id!, matterCode };
}

test.describe("Hari 2026-07-02 deployed fixes", () => {
  test("BUG-001: corrupted authority OCR is omitted from deployed Research", async ({
    page,
  }) => {
    const garbledSnippet =
      "[2003] 3 -- f.t 'II'. 178, ; 3ffillllll mi aRT 'A III' 1Tfffi " +
      ".mi -- aRT .. 12 -- d, 2002. lila l?1t. tt. 1950, 27 3TR 28 " +
      "JTR. SIftIII'l cff. fcIrlTT ;ifo1l. C1>lx mt fl 4<1i fclr " +
      "q1fiun'l llC1>lll1a fcIrq -- fl .wf. fcIrnl -- <ITT -j+t H.";

    await page.route(/.*\/api\/authorities\/search.*/, async (route) => {
      if (route.request().method() !== "POST") {
        await route.continue();
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          query: "cheque notice delay",
          provider: "caseops-prod-regression",
          generated_at: new Date().toISOString(),
          results: [
            {
              authority_document_id: "hari-2026-07-02-garbled-prod",
              title: "[2003] 3 -- f.t 'II'. 178",
              court_name: "Supreme Court of India",
              forum_level: "supreme_court",
              document_type: "judgment",
              decision_date: "2003-01-01",
              case_reference: "TEST/2003",
              bench_name: null,
              summary: garbledSnippet,
              source: "synthetic",
              source_reference: null,
              snippet: garbledSnippet,
              score: 0.99,
              matched_terms: [],
            },
          ],
          coverage_notice: null,
          contextual_plan: null,
          total_after_filter: 1,
        }),
      });
    });
    await page.route(/.*\/api\/authorities\/stats(\?|$)/, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          document_count: 1,
          chunk_count: 1,
          embedded_chunk_count: 1,
          forum_counts: { supreme_court: 1 },
          last_ingested_at: new Date().toISOString(),
        }),
      });
    });

    await page.goto(`${PROD_BASE_URL}/app/research`, { waitUntil: "networkidle" });
    await page.getByTestId("research-mode-contextual").click();
    await page
      .getByTestId("research-query-input")
      .fill("Cheque bounced due to insufficient funds and notice was sent after 35 days");
    await page.getByTestId("research-query-submit").click();

    await expect(page.getByText(/not readable enough to preview/i)).toBeVisible();
    await expect(page.getByTestId("research-result-garbled")).toHaveCount(0);
    await expect(page.locator("body")).not.toContainText(
      /\[2003\]\s*3\s*--\s*f\.t|3ffillllll|fcIrlTT|llC1>lll1a/i,
    );
  });

  test("BUG-00X: Matter cockpit Notices tab uploads notice attachments", async ({
    page,
  }) => {
    const { matterId, matterCode } = await createMatter(page);

    await page.goto(`${PROD_BASE_URL}/app/matters/${matterId}`);
    const cockpitTabs = page.getByRole("navigation", {
      name: /Matter cockpit tabs/i,
    });
    await expect(
      cockpitTabs.getByRole("link", { name: "Notices", exact: true }),
    ).toBeVisible();
    await cockpitTabs.getByRole("link", { name: "Notices", exact: true }).click();
    await page.waitForURL(/\/notices$/);
    await expect(
      page.getByRole("heading", { name: "Notices", exact: true }),
    ).toBeVisible();

    const fixtureDir = path.join(process.cwd(), ".e2e", "prod-upload-fixtures");
    fs.mkdirSync(fixtureDir, { recursive: true });
    const filename = `${matterCode.toLowerCase()}-demand-notice.txt`;
    const filePath = path.join(fixtureDir, filename);
    fs.writeFileSync(
      filePath,
      `Demand notice under Section 138 for production regression ${matterCode}.`,
      "utf8",
    );

    const uploadResponse = page.waitForResponse(
      (response) =>
        response.url().includes(`/api/matters/${matterId}/attachments`) &&
        response.request().method() === "POST",
      { timeout: 90_000 },
    );
    await page.setInputFiles('[data-testid="matter-notice-file-input"]', filePath);
    const response = await uploadResponse;
    expect(
      response.status(),
      `notice upload expected 2xx, got ${response.status()} ${await response.text()}`,
    ).toBeGreaterThanOrEqual(200);
    expect(response.status()).toBeLessThan(300);

    const noticeRow = page.getByTestId("matter-notice-row");
    await expect(noticeRow).toContainText(filename, { timeout: 45_000 });
    await expect(noticeRow).toContainText(/pending|indexed|needs_ocr/i);

    await page.goto(`${PROD_BASE_URL}/app/matters/${matterId}/documents`);
    await expect(page.getByText(filename).first()).toBeVisible({
      timeout: 45_000,
    });
    await expect(page.getByText("Notice").first()).toBeVisible();
  });
});
