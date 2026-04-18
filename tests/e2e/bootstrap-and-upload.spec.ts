import { expect, test } from "@playwright/test";
import path from "node:path";

import { makeUploadFixture, runDocumentWorkerOnce, uniqueId } from "./support/helpers";

// BG-010 / BG-013 — owners can bootstrap a workspace from the new
// `/sign-in` surface (no more `/legacy` detour), and once inside the
// matter cockpit they can upload a document, see the row appear, and
// trigger a reindex after the worker has processed it.

test.describe("New cockpit — bootstrap + document upload", () => {
  test("owner bootstraps via sign-in tab, creates a matter, uploads a file", async ({
    page,
  }) => {
    const suffix = uniqueId("bg010").slice(-8);
    const slug = `bg010-${suffix}`;
    const email = `owner-${suffix}@example.com`;
    const password = "FoundersPass123!";

    await page.goto("/sign-in");

    // Switch to the "New workspace" tab and submit the form.
    await page.getByRole("tab", { name: /New workspace/i }).click();
    await expect(
      page.getByRole("heading", { level: 1, name: /Create your CaseOps workspace/i }),
    ).toBeVisible();

    await page.getByLabel(/Firm \/ organisation name/i).fill(`E2E Bootstrap ${suffix}`);
    await page.getByLabel(/Workspace slug/i).fill(slug);
    // companyType already defaults to "law_firm".
    await page.getByLabel(/Your full name/i).fill("Asha Partner");
    await page.getByLabel(/Your work email/i).fill(email);
    await page.getByLabel(/^Password$/i).fill(password);
    await page.getByTestId("new-workspace-submit").click();

    // Land on the dashboard.
    await page.waitForURL("**/app");
    await expect(
      page.getByRole("heading", { name: /Good to have you back/i }),
    ).toBeVisible();

    // Create a matter via the new cockpit so we have somewhere to upload.
    await page.getByRole("link", { name: "Matters", exact: true }).click();
    await page.waitForURL("**/app/matters");
    await page.getByTestId("new-matter-trigger").first().click();
    const dialog = page.getByRole("dialog");
    const matterTitle = `Upload Smoke ${suffix}`;
    const matterCode = `BG013-${suffix.toUpperCase()}`;
    await dialog.getByLabel("Title").fill(matterTitle);
    await dialog.getByLabel("Matter code").fill(matterCode);
    await dialog.getByLabel("Practice area").fill("Commercial");
    await dialog.getByRole("button", { name: /Create matter/i }).click();
    await expect(dialog).toBeHidden();

    // Open the new matter, navigate to documents.
    await page.getByText(matterTitle).first().click();
    await page.waitForURL(/\/app\/matters\/[^/]+/);
    await page.getByRole("link", { name: /Documents/ }).first().click();
    await expect(page.getByText(/No documents attached yet/i)).toBeVisible();

    // Upload a small PDF-ish fixture. The worker runs as a BackgroundTask
    // in-process but for determinism in e2e we also poke it directly.
    const filePath = makeUploadFixture(
      `bg013-${suffix}.txt`,
      "Trial order dated 2024-07-18. Sample document body.",
    );
    await page.setInputFiles(
      '[data-testid="matter-attachment-file-input"]',
      filePath,
    );

    await expect(
      page.getByText(path.basename(filePath), { exact: false }),
    ).toBeVisible({ timeout: 15_000 });

    // Drain the document worker queue so status transitions away from
    // "pending" — that's what makes retry/reindex buttons meaningful.
    await runDocumentWorkerOnce();
    await page.reload();

    // The row is still there after reload, proving persistence.
    await expect(
      page.getByText(path.basename(filePath), { exact: false }),
    ).toBeVisible();
  });
});
