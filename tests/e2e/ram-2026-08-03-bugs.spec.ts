import { expect, test, type APIRequestContext } from "@playwright/test";

import { apiBaseUrl } from "./support/env";

const PASSWORD = "SavedSourceProof2026!";

function unique(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random()
    .toString(36)
    .slice(2, 8)}`;
}

type BootstrapSession = {
  company: unknown;
  user: unknown;
  membership: unknown;
  capabilities: string[];
};

async function bootstrap(
  api: APIRequestContext,
  slug: string,
): Promise<BootstrapSession> {
  const response = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "Saved Source Proof LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Saved Source Owner",
      owner_email: `owner-${slug}@example.com`,
      owner_password: PASSWORD,
    },
  });
  expect(response.status(), await response.text()).toBe(200);
  const payload = (await response.json()) as BootstrapSession;
  return {
    company: payload.company,
    user: payload.user,
    membership: payload.membership,
    capabilities: payload.capabilities,
  };
}

test.describe("Ram 2026-08-03 saved research source actions", () => {
  test("IPLF-003C/004B preserves source state and reports defects at 360px", async ({
    page,
  }) => {
    const slug = unique("saved-source");
    // page.request shares the browser context's HttpOnly session cookie. Seed
    // only the non-sensitive shell context, matching storeSession; no access
    // token is exposed to browser JavaScript.
    const session = await bootstrap(page.request, slug);
    await page.goto("/sign-in");
    await page.evaluate((value) => {
      window.localStorage.setItem(
        "caseops.session.context",
        JSON.stringify(value),
      );
    }, session);

    let reportPayload: Record<string, unknown> | null = null;
    await page.route("**/api/source-actions/reports", async (route) => {
      reportPayload = (await route.request().postDataJSON()) as Record<
        string,
        unknown
      >;
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({
          id: "report-proof",
          target_type: reportPayload.target_type,
          target_id: reportPayload.target_id,
          origin_surface: reportPayload.origin_surface,
          issue_type: reportPayload.issue_type,
          status: "queued",
          source_state: "unverified",
          destination_class: "unavailable_unverified",
          created_at: "2026-08-04T00:00:00Z",
        }),
      });
    });

    await page.route("**/api/authorities/annotations**", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          annotations: [
            {
              id: "annotation-available",
              authority_document_id: "authority-available",
              created_by_membership_id: "membership-proof",
              kind: "flag",
              title: "Verified source proof",
              body: "Saved result retains its original source contract.",
              is_archived: false,
              created_at: "2026-08-03T00:00:00Z",
              updated_at: "2026-08-03T00:00:00Z",
              authority_court_name: "Supreme Court of India",
              authority_forum_level: "supreme_court",
              authority_document_type: "judgment",
              authority_title: "Source-backed saved authority",
              authority_source: "official",
              authority_source_reference: "https://www.sci.gov.in/source-proof.pdf",
              authority_source_action: {
                state: "available",
                label: "Open source",
                open_url:
                  "/api/source-actions/targets/authority_document/authority-available/open",
                source_reference: "https://www.sci.gov.in/source-proof.pdf",
                reason: null,
                opens_new_tab: true,
                target_type: "authority_document",
                target_id: "authority-available",
              },
              authority_neutral_citation: "2026 INSC 303",
              authority_case_reference: null,
              authority_decision_date: "2026-08-01",
              authority_summary: "Deterministic source fixture",
            },
            {
              id: "annotation-unverified",
              authority_document_id: "authority-unverified",
              created_by_membership_id: "membership-proof",
              kind: "note",
              title: "Provider refresh needed",
              body: null,
              is_archived: false,
              created_at: "2026-08-03T00:01:00Z",
              updated_at: "2026-08-03T00:01:00Z",
              authority_court_name: "Delhi High Court",
              authority_forum_level: "high_court",
              authority_document_type: "judgment",
              authority_title: "Citation survives source failure",
              authority_source: "provider",
              authority_source_reference: "https://provider.invalid/expired",
              authority_source_action: {
                state: "unverified",
                label: "Open source",
                open_url: null,
                source_reference: "https://provider.invalid/expired",
                reason: "Source access must be refreshed by the provider.",
                opens_new_tab: true,
                target_type: "authority_document",
                target_id: "authority-unverified",
              },
              authority_neutral_citation: "2026:DHC:303",
              authority_case_reference: null,
              authority_decision_date: "2026-08-02",
              authority_summary: "Deterministic unavailable fixture",
            },
          ],
        }),
      }),
    );

    await page.setViewportSize({ width: 360, height: 800 });
    await page.goto("/app/research/saved");

    await expect(
      page.getByRole("heading", { name: "Saved research" }),
    ).toBeVisible();
    await expect(page.getByText("Source-backed saved authority")).toBeVisible();
    await expect(page.getByText(/2026 INSC 303/)).toBeVisible();
    const openSource = page.getByTestId("source-action-open");
    await expect(openSource).toBeVisible();
    await expect(openSource).toHaveAttribute(
      "href",
      /\/api\/source-actions\/targets\/authority_document\/[^/]+\/open/,
    );
    await expect(openSource).toHaveAttribute("target", "_blank");
    await expect(openSource).toHaveAttribute("href", /origin=saved_research/);

    await expect(page.getByText("Citation survives source failure")).toBeVisible();
    await expect(page.getByText(/2026:DHC:303/)).toBeVisible();
    await expect(page.getByTestId("source-action-unverified")).toBeVisible();
    await expect(page.getByTestId("source-action-unverified")).toHaveText(
      "unverified",
    );
    const reportButtons = page.getByTestId("source-action-report");
    await expect(reportButtons).toHaveCount(2);
    for (const reportButton of await reportButtons.all()) {
      const box = await reportButton.boundingBox();
      expect(box).not.toBeNull();
      expect(box!.x + box!.width).toBeLessThanOrEqual(360);
    }
    await reportButtons.nth(1).click();
    await page.getByLabel("Issue", { exact: true }).selectOption("wrong_document");
    await page
      .getByLabel("Details (optional)")
      .fill("The citation opens a different judgment.");
    await page.getByRole("button", { name: "Queue report" }).click();
    await expect(page.getByText("Source report queued for review.")).toBeVisible();
    expect(reportPayload).toMatchObject({
      target_type: "authority_document",
      target_id: "authority-unverified",
      origin_surface: "saved_research",
      issue_type: "wrong_document",
      description: "The citation opens a different judgment.",
    });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      360,
    );
  });
});
