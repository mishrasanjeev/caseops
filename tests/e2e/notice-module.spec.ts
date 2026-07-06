import path from "node:path";

import { expect, request, test } from "@playwright/test";
import type { APIRequestContext, Page } from "@playwright/test";

import { apiBaseUrl } from "./support/env";
import { makeUploadFixture } from "./support/helpers";

const PASSWORD = "NoticeModuleE2E!";

function unique(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random()
    .toString(36)
    .slice(2, 8)}`;
}

function dateOffset(days: number): string {
  const value = new Date();
  value.setDate(value.getDate() + days);
  return value.toISOString().slice(0, 10);
}

async function bootstrap(
  api: APIRequestContext,
  slug: string,
): Promise<{ token: string; ownerEmail: string }> {
  const ownerEmail = `owner-${slug}@example.com`;
  const resp = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "Notice Module E2E LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Notice Module Owner",
      owner_email: ownerEmail,
      owner_password: PASSWORD,
    },
  });
  expect(resp.status(), await resp.text()).toBe(200);
  return { token: (await resp.json()).access_token as string, ownerEmail };
}

async function signIn(page: Page, slug: string, email: string): Promise<void> {
  await page.goto("/sign-in");
  await page.locator("#company-slug").fill(slug);
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(PASSWORD);
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  await page.waitForURL(/\/app/);
}

async function createMatter(
  api: APIRequestContext,
  token: string,
  code: string,
): Promise<string> {
  const resp = await api.post(`${apiBaseUrl}/api/matters/`, {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      title: `Notice module matter ${code}`,
      matter_code: code,
      client_name: "Acme Foods",
      opposing_party: "GST Department",
      practice_area: "Tax Litigation",
      forum_level: "tribunal",
      status: "intake",
      court_name: "GST Appellate Tribunal",
    },
  });
  expect(resp.status(), await resp.text()).toBe(200);
  return ((await resp.json()) as { id: string }).id;
}

test.describe("Notice module workflows", () => {
  test.setTimeout(180_000);

  test("received and sent notices persist metadata, reply tracking, child documents, and filters", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("notice");
    const { token, ownerEmail } = await bootstrap(api, slug);
    const matterCode = unique("NOTICE").toUpperCase();
    const matterId = await createMatter(api, token, matterCode);
    await api.dispose();

    await signIn(page, slug, ownerEmail);
    await page.goto(`/app/matters/${matterId}/notices`);
    await expect(
      page.getByRole("heading", { name: "Notices", exact: true }),
    ).toBeVisible();
    await expect(page.getByText(/No received notices/i)).toBeVisible();

    await page.getByTestId("matter-notice-type").fill("GST demand");
    await page.getByTestId("matter-notice-department").fill("Finance");
    await page.getByTestId("matter-notice-subject").fill("GST demand notice");
    await page.getByTestId("matter-notice-authority").fill("GST Department");
    await page.getByTestId("matter-notice-internal-spoc").fill("Asha Mehta");
    await page.getByTestId("matter-notice-received-on").fill(dateOffset(-3));
    await page.getByTestId("matter-notice-mode").fill("Email");
    await page.getByTestId("matter-notice-source").fill("Assistant Commissioner");
    await page.getByTestId("matter-notice-amount").fill("12500");
    await page.getByTestId("matter-notice-reply-due-on").fill(dateOffset(-1));
    await page
      .getByTestId("matter-notice-summary")
      .fill("Demand alleges short payment of GST.");
    await page
      .getByTestId("matter-notice-response")
      .fill("Prepare reply with payment challans and limitation objection.");
    await page.getByTestId("matter-notice-remarks").fill("Reply requires accounts input.");
    await page
      .getByTestId("matter-notice-internal-remarks")
      .fill("Escalated to finance controller.");

    const receivedNoticePath = makeUploadFixture(
      `${matterCode.toLowerCase()}-gst-demand-notice.txt`,
      "GST demand notice with reply deadline.",
    );
    const receivedUploadResponse = page.waitForResponse(
      (response) =>
        response.url().includes(`/api/matters/${matterId}/attachments`) &&
        response.request().method() === "POST",
    );
    await page.setInputFiles('[data-testid="matter-notice-file-input"]', receivedNoticePath);
    expect((await receivedUploadResponse).status()).toBe(200);

    const receivedRow = page.getByTestId("matter-notice-row");
    await expect(receivedRow).toContainText("GST demand notice");
    await expect(receivedRow).toContainText("GST Department");
    await expect(receivedRow).toContainText("Assistant Commissioner");
    await expect(receivedRow).toContainText("Reply Overdue");
    await expect(receivedRow).toContainText("Reminders: 7, 3, 1 days before");
    await expect(receivedRow).toContainText("Prepare reply with payment challans");

    const replyPath = makeUploadFixture(
      `${matterCode.toLowerCase()}-gst-demand-reply.txt`,
      "Reply to GST demand notice.",
    );
    const replyUploadResponse = page.waitForResponse(
      (response) =>
        response.url().includes(`/api/matters/${matterId}/attachments`) &&
        response.request().method() === "POST",
    );
    await page.getByRole("button", { name: /Reply document/i }).click();
    await page.setInputFiles(
      '[data-testid="matter-notice-related-file-input"]',
      replyPath,
    );
    expect((await replyUploadResponse).status()).toBe(200);
    await expect(receivedRow).toContainText("Reply Sent");
    await expect(receivedRow).toContainText(path.basename(replyPath));
    await expect(receivedRow).toContainText("Documents and reply history");

    await page.getByTestId("notice-sent-tab").click();
    await page.getByTestId("matter-notice-sent-on").fill(dateOffset(0));
    await page.getByTestId("matter-notice-type").fill("Recovery notice");
    await page.getByTestId("matter-notice-status").fill("Dispatched");
    await page.getByTestId("matter-notice-department").fill("Legal");
    await page.getByTestId("matter-notice-subject").fill("Payment recovery notice");
    await page.getByTestId("matter-notice-authority").fill("Client instruction");
    await page.getByTestId("matter-notice-counsel").fill("Rao & Co.");
    await page.getByTestId("matter-notice-dispute-amount").fill("15000");
    await page.getByTestId("matter-notice-recovered-amount").fill("2500");
    await page
      .getByTestId("matter-notice-summary")
      .fill("Notice sent to recover unpaid invoices.");

    const sentNoticePath = makeUploadFixture(
      `${matterCode.toLowerCase()}-payment-recovery-notice.txt`,
      "Payment recovery notice sent by counsel.",
    );
    const sentUploadResponse = page.waitForResponse(
      (response) =>
        response.url().includes(`/api/matters/${matterId}/attachments`) &&
        response.request().method() === "POST",
    );
    await page.setInputFiles('[data-testid="matter-notice-file-input"]', sentNoticePath);
    expect((await sentUploadResponse).status()).toBe(200);

    const sentRow = page.getByTestId("matter-notice-row");
    await expect(sentRow).toContainText("Payment recovery notice");
    await expect(sentRow).toContainText("Sent");
    await expect(sentRow).toContainText("Rao & Co.");
    await expect(sentRow).toContainText("Dispatched");

    await page.getByTestId("notice-received-tab").click();
    await page.getByTestId("notice-filter-query").fill("GST");
    await page.getByTestId("notice-filter-reply-status").selectOption("reply_sent");
    await expect(page.getByTestId("matter-notice-row")).toHaveCount(1);
    await expect(page.getByTestId("matter-notice-row")).toContainText("GST demand notice");

    await page.goto(`/app/matters/${matterId}/documents`);
    await expect(page.getByText(path.basename(receivedNoticePath)).first()).toBeVisible();
    await expect(page.getByText(path.basename(replyPath)).first()).toBeVisible();
    await expect(page.getByText(path.basename(sentNoticePath)).first()).toBeVisible();
  });
});
