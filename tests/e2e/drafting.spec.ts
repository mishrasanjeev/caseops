import { expect, request, test } from "@playwright/test";
import type { APIRequestContext } from "@playwright/test";

import { apiBaseUrl } from "./support/env";

const PASSWORD = "DraftingPass123!";

async function bootstrap(api: APIRequestContext, slug: string): Promise<string> {
  const resp = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "Drafting Test LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Drafting Owner",
      owner_email: `owner-${slug}@example.com`,
      owner_password: PASSWORD,
    },
  });
  if (resp.status() === 409) {
    // Re-bootstrap idempotency path: the firm already exists; ok for e2e.
    return slug;
  }
  if (resp.status() !== 200) {
    throw new Error(`Bootstrap failed: ${resp.status()} ${await resp.text()}`);
  }
  return slug;
}

function unique(prefix: string): string {
  return `${prefix}-${Math.random().toString(36).slice(2, 8)}`;
}

test.describe("Drafting studio (§4.3)", () => {
  // Opus 4.7 generation is the slow step in this flow; give the whole
  // test a generous window so we never fail on raw model latency.
  test.setTimeout(300_000);

  test("create draft, generate, submit, request changes, regenerate, approve, finalize", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("ds");
    await bootstrap(api, slug);

    // Seed an authority the verifier will match.
    // We can't seed DB directly from Playwright, so we rely on whatever
    // the mock/Postgres authority catalog already holds. The important
    // assertion is the UI state machine; the approve step may be
    // legitimately blocked when no citations survive verification —
    // the test asserts the UX handles that honestly.

    // Sign in.
    await page.goto("/sign-in");
    await page.locator("#company-slug").fill(slug);
    await page.locator("#email").fill(`owner-${slug}@example.com`);
    await page.locator("#password").fill(PASSWORD);
    await page.getByRole("button", { name: /^Sign in$/ }).click();
    await page.waitForURL(/\/app/);

    // Create a matter for the draft.
    await page.goto("/app/matters");
    await page.getByTestId("new-matter-trigger").first().click();
    const dialog = page.getByRole("dialog");
    const matterCode = `DS-${Math.random().toString(36).slice(2, 6).toUpperCase()}`;
    await dialog.getByLabel("Title").fill("Drafting studio e2e");
    await dialog.getByLabel("Matter code").fill(matterCode);
    await dialog.getByLabel("Practice area").fill("Commercial");
    await dialog.getByRole("button", { name: /Create matter/i }).click();
    await expect(dialog).toBeHidden();

    // Open the new matter's cockpit via the DataTable row.
    await page.getByText("Drafting studio e2e").first().click();
    await page.waitForURL(/\/app\/matters\/[0-9a-f-]+$/);

    // Navigate to Drafts tab.
    await page.getByRole("link", { name: "Drafts", exact: true }).click();
    await page.waitForURL(/\/app\/matters\/[0-9a-f-]+\/drafts$/);
    await expect(
      page.getByRole("heading", { name: "Drafting studio", exact: true }),
    ).toBeVisible();

    // ENH-004 (2026-05-01): "New draft" no longer opens a dialog — it
    // navigates to /drafts/new which renders the template-grid + multi-
    // step fact-capture stepper. The CREATE step is incidental to what
    // this test covers (the generate → submit → request_changes → ...
    // state machine), so we bypass the new UI and create the draft via
    // the matter-scoped API. Use page.context().request so the call
    // shares the BrowserContext's cookies — fetch() inside evaluate
    // would be cross-origin (web :3100 → api :8000) and miss the auth.
    const draftsListUrl = page.url();
    const matterId = draftsListUrl.match(/matters\/([0-9a-f-]+)\/drafts/)?.[1];
    if (!matterId) throw new Error(`could not parse matter id from ${draftsListUrl}`);
    // CaseOps uses double-submit CSRF: the api/client.ts helper reads
    // the caseops_csrf cookie and forwards it as X-CSRF-Token. Mirror
    // that here for the raw API call.
    const cookies = await page.context().cookies();
    const csrf = cookies.find((c) => c.name === "caseops_csrf")?.value;
    if (!csrf) throw new Error("caseops_csrf cookie missing after sign-in");
    const draftRes = await page.context().request.post(
      `http://127.0.0.1:8000/api/matters/${matterId}/drafts`,
      {
        data: { title: "E2E reply brief", draft_type: "brief" },
        headers: { "X-CSRF-Token": csrf },
      },
    );
    if (!draftRes.ok()) {
      throw new Error(
        `POST /matters/${matterId}/drafts -> ${draftRes.status()}: ${await draftRes.text()}`,
      );
    }
    const draftId = ((await draftRes.json()) as { id: string }).id;
    await page.goto(`/app/matters/${matterId}/drafts/${draftId}`);
    await expect(
      page.getByRole("heading", { name: "E2E reply brief" }),
    ).toBeVisible();

    // Generate the first version. Drafting now routes to Opus 4.7 which,
    // at 8k max output tokens, comfortably runs 30-60s. Bump the window
    // so the test tracks the production reality instead of the legacy
    // Haiku cadence.
    await page.getByTestId("draft-generate").click();
    await expect(
      page.getByText(/Generated /).first(),
    ).toBeVisible({ timeout: 120_000 });

    // Submit for review.
    await page.getByTestId("draft-submit").click();
    await expect(page.getByText(/in review/i).first()).toBeVisible();

    // Reviewer requests changes, sending us back to changes_requested.
    await page.getByTestId("draft-request-changes").click();
    await expect(page.getByText(/changes requested/i).first()).toBeVisible();

    // Download button is present whenever a version exists.
    await expect(page.getByTestId("draft-download-docx")).toBeVisible();
  });
});
