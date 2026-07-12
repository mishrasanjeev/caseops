/**
 * Hari 2026-07-03 workbook regressions.
 *
 * BUG-003: Created matters can be edited from the matter overview.
 * BUG-004: Multiple matter documents can be selected and downloaded as one ZIP.
 * BUG-005: Notice uploads capture structured source/subject/received/response fields.
 */
import path from "node:path";

import { expect, request, test } from "@playwright/test";
import type { APIRequestContext, Page } from "@playwright/test";

import { apiBaseUrl } from "./support/env";
import { makeUploadFixture } from "./support/helpers";

const PASSWORD = "HariJul03Bugs!";

function unique(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random()
    .toString(36)
    .slice(2, 8)}`;
}

async function bootstrap(
  api: APIRequestContext,
  slug: string,
): Promise<{ token: string; ownerEmail: string }> {
  const ownerEmail = `owner-${slug}@example.com`;
  const resp = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "Hari 2026-07-03 LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Hari Jul03 Owner",
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
      title: `Hari Jul03 editable matter ${code}`,
      matter_code: code,
      client_name: "Original Client",
      opposing_party: "Original Opponent",
      case_number: "OLD-CASE",
      cnr_number: "OLD-CNR",
      practice_area: "Civil",
      forum_level: "high_court",
      status: "intake",
      court_name: "Delhi High Court",
      judge_name: "Original Bench",
      description: "Original summary",
      next_hearing_on: "2026-07-20",
    },
  });
  expect(resp.status(), await resp.text()).toBe(200);
  return ((await resp.json()) as { id: string }).id;
}

async function uploadDocument(
  api: APIRequestContext,
  token: string,
  matterId: string,
  filename: string,
  body: string,
): Promise<string> {
  const resp = await api.post(`${apiBaseUrl}/api/matters/${matterId}/attachments`, {
    headers: { Authorization: `Bearer ${token}` },
    multipart: {
      file: {
        name: filename,
        mimeType: "text/plain",
        buffer: Buffer.from(body),
      },
      document_type: "evidence",
      lifecycle_stage: "evidence",
    },
  });
  expect(resp.status(), await resp.text()).toBe(200);
  return ((await resp.json()) as { id: string }).id;
}

test.describe("Hari 2026-07-03 bugs", () => {
  test.setTimeout(150_000);

  test("BUG-003/004/005: matter edit, bulk document ZIP, and notice template", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("h703").toLowerCase();
    const { token, ownerEmail } = await bootstrap(api, slug);
    const matterCode = unique("H703").toUpperCase();
    const matterId = await createMatter(api, token, matterCode);
    const firstAttachmentId = await uploadDocument(
      api,
      token,
      matterId,
      "pleading-hari-703.txt",
      "First Hari 2026-07-03 bulk-download document.",
    );
    const secondAttachmentId = await uploadDocument(
      api,
      token,
      matterId,
      "evidence-hari-703.txt",
      "Second Hari 2026-07-03 bulk-download document.",
    );
    await api.dispose();

    await signIn(page, slug, ownerEmail);

    await page.goto(`/app/matters/${matterId}`);
    await page.getByTestId("matter-edit-open").click();
    await page.getByTestId("matter-edit-title").fill("Hari Jul03 corrected matter");
    await page.getByTestId("matter-edit-code").fill(`${matterCode}-FIX`);
    await page.getByTestId("matter-edit-client").fill("Corrected Client");
    await page.getByTestId("matter-edit-opposing").fill("Corrected Opponent");
    await page.getByTestId("matter-edit-case-number").fill("CORRECT-CASE");
    await page.getByTestId("matter-edit-cnr-number").fill("CORRECT-CNR");
    await page.getByTestId("matter-edit-description").fill("Corrected summary");
    const updateResponse = page.waitForResponse(
      (response) =>
        response.url().includes(`/api/matters/${matterId}`) &&
        response.request().method() === "PATCH",
    );
    await page.getByTestId("matter-edit-save").click();
    expect((await updateResponse).status()).toBe(200);
    await expect(page.getByText("Corrected summary")).toBeVisible();
    await expect(
      page.getByRole("definition").filter({ hasText: `${matterCode}-FIX` }),
    ).toBeVisible();
    await expect(page.getByText("Corrected Client", { exact: true }).first()).toBeVisible();

    await page.goto(`/app/matters/${matterId}/documents`);
    await page.getByTestId(`matter-document-select-${firstAttachmentId}`).check();
    await page.getByTestId(`matter-document-select-${secondAttachmentId}`).check();
    await expect(page.getByTestId("matter-documents-selected-count")).toContainText(
      "2 selected",
    );
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.getByTestId("matter-documents-bulk-download").click(),
    ]);
    expect(download.suggestedFilename()).toMatch(/documents\.zip$/);

    await page.goto(`/app/matters/${matterId}/notices`);
    await page.getByTestId("matter-notice-source").fill("Opposing counsel");
    await page.getByTestId("matter-notice-subject").fill("Hari Jul03 demand notice");
    await page.getByTestId("matter-notice-received-on").fill("2026-07-03");
    await page
      .getByTestId("matter-notice-response")
      .fill("Draft reply denying the demand and preserving limitation.");
    const noticePath = makeUploadFixture(
      "hari-jul03-demand-notice.txt",
      "Structured Hari 2026-07-03 notice upload.",
    );
    const uploadResponse = page.waitForResponse(
      (response) =>
        response.url().includes(`/api/matters/${matterId}/attachments`) &&
        response.request().method() === "POST",
    );
    await page.setInputFiles('[data-testid="matter-notice-file-input"]', noticePath);
    expect((await uploadResponse).status()).toBe(200);

    await expect(page.getByTestId("matter-notice-row")).toContainText(
      "Hari Jul03 demand notice",
    );
    await expect(page.getByTestId("matter-notice-row")).toContainText("Opposing counsel");
    await expect(page.getByTestId("matter-notice-row")).toContainText(
      "Draft reply denying the demand",
    );
    await expect(page.getByTestId("matter-notice-row")).toContainText(
      path.basename(noticePath),
    );
  });
});
