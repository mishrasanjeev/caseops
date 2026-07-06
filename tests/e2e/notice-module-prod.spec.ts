import fs from "node:fs";
import path from "node:path";

import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

const env = (key: string, fallback: string): string => {
  const value = (process.env[key] ?? "").trim();
  return value.length > 0 ? value : fallback;
};

const PROD_BASE_URL = env("PROD_BASE_URL", "https://caseops.ai");
const PROD_API_BASE_URL = env("PROD_API_BASE_URL", "https://api.caseops.ai");

function dateOffset(days: number): string {
  const value = new Date();
  value.setDate(value.getDate() + days);
  return value.toISOString().slice(0, 10);
}

async function authHeaders(page: Page): Promise<Record<string, string>> {
  const cookies = await page.context().cookies([PROD_BASE_URL, PROD_API_BASE_URL]);
  const cookieHeader = cookies
    .filter((cookie) => cookie.domain.includes("caseops.ai"))
    .map((cookie) => `${cookie.name}=${cookie.value}`)
    .join("; ");
  const csrf = cookies.find((cookie) => cookie.name === "caseops_csrf")?.value ?? "";
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
  const matterCode = `NOTICE-PROD-${Date.now().toString().slice(-8)}`;
  const response = await page.context().request.post(
    `${PROD_API_BASE_URL}/api/matters/`,
    {
      headers: await authHeaders(page),
      data: {
        title: `Notice module production probe ${matterCode}`,
        matter_code: matterCode,
        client_name: "CaseOps QA",
        opposing_party: "GST Department",
        practice_area: "Tax Litigation",
        forum_level: "tribunal",
        status: "intake",
        court_name: "GST Appellate Tribunal",
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

function prodFixture(filename: string, contents: string): string {
  const fixtureDir = path.join(process.cwd(), ".e2e", "prod-upload-fixtures");
  fs.mkdirSync(fixtureDir, { recursive: true });
  const filePath = path.join(fixtureDir, filename);
  fs.writeFileSync(filePath, contents, "utf8");
  return filePath;
}

test.describe("Notice module production workflows", () => {
  test.setTimeout(180_000);

  test("QA tenant can upload received notices, reply documents, sent notices, and filter them", async ({
    page,
  }) => {
    const { matterId, matterCode } = await createMatter(page);

    await page.goto(`${PROD_BASE_URL}/app/matters/${matterId}/notices`, {
      waitUntil: "networkidle",
    });
    await expect(
      page.getByRole("heading", { name: "Notices", exact: true }),
    ).toBeVisible();

    await page.getByTestId("matter-notice-type").fill("GST demand");
    await page.getByTestId("matter-notice-department").fill("Finance");
    await page.getByTestId("matter-notice-subject").fill("GST demand notice");
    await page.getByTestId("matter-notice-authority").fill("GST Department");
    await page.getByTestId("matter-notice-internal-spoc").fill("QA Bot");
    await page.getByTestId("matter-notice-received-on").fill(dateOffset(-3));
    await page.getByTestId("matter-notice-mode").fill("Email");
    await page.getByTestId("matter-notice-source").fill("Assistant Commissioner");
    await page.getByTestId("matter-notice-amount").fill("12500");
    await page.getByTestId("matter-notice-reply-due-on").fill(dateOffset(-1));
    await page
      .getByTestId("matter-notice-summary")
      .fill("Production smoke demand notice summary.");
    await page
      .getByTestId("matter-notice-response")
      .fill("Production smoke reply plan with challan reconciliation.");

    const receivedNoticePath = prodFixture(
      `${matterCode.toLowerCase()}-gst-demand-notice.txt`,
      "Production GST demand notice.",
    );
    const receivedUploadResponse = page.waitForResponse(
      (response) =>
        response.url().includes(`/api/matters/${matterId}/attachments`) &&
        response.request().method() === "POST",
      { timeout: 90_000 },
    );
    await page.setInputFiles('[data-testid="matter-notice-file-input"]', receivedNoticePath);
    const receivedResponse = await receivedUploadResponse;
    expect(receivedResponse.status()).toBeGreaterThanOrEqual(200);
    expect(receivedResponse.status()).toBeLessThan(300);

    const receivedRow = page.getByTestId("matter-notice-row");
    await expect(receivedRow).toContainText("GST demand notice", { timeout: 45_000 });
    await expect(receivedRow).toContainText("Reply Overdue");
    await expect(receivedRow).toContainText("Assistant Commissioner");
    await expect(receivedRow).toContainText("Production smoke reply plan");

    const replyPath = prodFixture(
      `${matterCode.toLowerCase()}-gst-demand-reply.txt`,
      "Production reply to GST demand notice.",
    );
    const replyUploadResponse = page.waitForResponse(
      (response) =>
        response.url().includes(`/api/matters/${matterId}/attachments`) &&
        response.request().method() === "POST",
      { timeout: 90_000 },
    );
    await page.getByRole("button", { name: /Reply document/i }).click();
    await page.setInputFiles(
      '[data-testid="matter-notice-related-file-input"]',
      replyPath,
    );
    const replyResponse = await replyUploadResponse;
    expect(replyResponse.status()).toBeGreaterThanOrEqual(200);
    expect(replyResponse.status()).toBeLessThan(300);
    await expect(receivedRow).toContainText("Reply Sent", { timeout: 45_000 });
    await expect(receivedRow).toContainText(path.basename(replyPath));

    await page.getByTestId("notice-sent-tab").click();
    await page.getByTestId("matter-notice-sent-on").fill(dateOffset(0));
    await page.getByTestId("matter-notice-type").fill("Recovery notice");
    await page.getByTestId("matter-notice-status").fill("Dispatched");
    await page.getByTestId("matter-notice-department").fill("Legal");
    await page.getByTestId("matter-notice-subject").fill("Payment recovery notice");
    await page.getByTestId("matter-notice-authority").fill("Client instruction");
    await page.getByTestId("matter-notice-counsel").fill("QA Counsel");
    await page.getByTestId("matter-notice-dispute-amount").fill("15000");
    await page.getByTestId("matter-notice-recovered-amount").fill("2500");
    await page
      .getByTestId("matter-notice-summary")
      .fill("Production smoke sent-notice summary.");

    const sentNoticePath = prodFixture(
      `${matterCode.toLowerCase()}-payment-recovery-notice.txt`,
      "Production sent recovery notice.",
    );
    const sentUploadResponse = page.waitForResponse(
      (response) =>
        response.url().includes(`/api/matters/${matterId}/attachments`) &&
        response.request().method() === "POST",
      { timeout: 90_000 },
    );
    await page.setInputFiles('[data-testid="matter-notice-file-input"]', sentNoticePath);
    const sentResponse = await sentUploadResponse;
    expect(sentResponse.status()).toBeGreaterThanOrEqual(200);
    expect(sentResponse.status()).toBeLessThan(300);

    await expect(page.getByTestId("matter-notice-row")).toContainText(
      "Payment recovery notice",
      { timeout: 45_000 },
    );
    await expect(page.getByTestId("matter-notice-row")).toContainText("QA Counsel");

    await page.getByTestId("notice-received-tab").click();
    await page.getByTestId("notice-filter-query").fill("GST");
    await page.getByTestId("notice-filter-reply-status").selectOption("reply_sent");
    await expect(page.getByTestId("matter-notice-row")).toHaveCount(1);
    await expect(page.getByTestId("matter-notice-row")).toContainText("GST demand notice");
  });
});
