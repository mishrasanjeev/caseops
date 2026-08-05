import { expect, request, test } from "@playwright/test";
import type { APIRequestContext, Page } from "@playwright/test";
import path from "node:path";

import { apiBaseUrl } from "./support/env";
import { makeUploadFixture, plusDays } from "./support/helpers";

const PASSWORD = "FunctionalQa123!";

type BootstrapResult = {
  ownerEmail: string;
  slug: string;
  token: string;
};

function unique(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random()
    .toString(36)
    .slice(2, 8)}`;
}

async function bootstrapTenant(
  api: APIRequestContext,
  slug: string,
): Promise<BootstrapResult> {
  const ownerEmail = `owner-${slug}@example.com`;
  const response = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: `Functional QA ${slug}`,
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Functional QA Owner",
      owner_email: ownerEmail,
      owner_password: PASSWORD,
    },
  });
  expect(response.status(), await response.text()).toBe(200);
  return {
    ownerEmail,
    slug,
    token: ((await response.json()) as { access_token: string }).access_token,
  };
}

async function signIn(page: Page, tenant: BootstrapResult): Promise<void> {
  await page.goto("/sign-in");
  await page.locator("#company-slug").fill(tenant.slug);
  await page.locator("#email").fill(tenant.ownerEmail);
  await page.locator("#password").fill(PASSWORD);
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  await page.waitForURL(/\/app/);
  await expect(
    page.getByRole("heading", { name: /Good to have you back/i }),
  ).toBeVisible();
}

async function expectSurface(
  page: Page,
  route: string,
  text: RegExp,
): Promise<void> {
  const response = await page.goto(route);
  if (response) {
    expect(response.status(), `${route} HTTP status`).toBeLessThan(400);
  }
  await expect(page.locator("main").getByText(text).first()).toBeVisible({
    timeout: 20_000,
  });
}

async function createMatterFromUi(
  page: Page,
  code: string,
  title: string,
): Promise<string> {
  await page.goto("/app/matters");
  await expectSurface(page, "/app/matters", /Matter portfolio/i);
  await page.locator("main").getByTestId("new-matter-trigger").first().click();

  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await dialog.getByLabel("Title").fill(title);
  await dialog.getByLabel("Matter code").fill(code);
  await dialog.getByLabel("Practice area").fill("Litigation");
  await dialog.getByLabel("Client name").fill("Functional QA Client");
  await dialog.getByLabel("Opposing party").fill("Functional QA Respondent");
  await dialog.getByLabel("Case number").fill("WP(C) 77/2026");
  await dialog.getByLabel("CNR number").fill("dlhc-0100-7777-2026");

  const createResponse = page.waitForResponse(
    (response) =>
      response.url().includes("/api/matters/") &&
      response.request().method() === "POST",
  );
  await dialog.getByRole("button", { name: /Create matter/i }).click();
  const response = await createResponse;
  expect(response.status(), await response.text()).toBe(200);
  const matter = (await response.json()) as { id: string };

  await expect(dialog).toBeHidden({ timeout: 15_000 });
  await expect(page.getByText(code).first()).toBeVisible({ timeout: 15_000 });
  return matter.id;
}

async function expectCaseTrackingBookmark(
  api: APIRequestContext,
  token: string,
  matterCode: string,
): Promise<void> {
  await expect
    .poll(
      async () => {
        const response = await api.get(`${apiBaseUrl}/api/case-tracking/bookmarks`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        expect(response.status(), await response.text()).toBe(200);
        const body = (await response.json()) as {
          bookmarks: Array<{
            name: string | null;
            tracked_case: {
              case_number: string | null;
              cnr_number: string | null;
              court_name: string | null;
            };
          }>;
        };
        return body.bookmarks.some(
          (bookmark) =>
            bookmark.name === matterCode &&
            bookmark.tracked_case.cnr_number === "DLHC010077772026" &&
            bookmark.tracked_case.case_number === "WP(C) 77/2026" &&
            bookmark.tracked_case.court_name === "Delhi High Court",
        );
      },
      { timeout: 20_000 },
    )
    .toBe(true);
}

test.describe("Functional QA automation spine", () => {
  test.setTimeout(180_000);

  test("owner can exercise core lifecycle and every primary authenticated surface", async ({
    page,
  }) => {
    const serverErrors: string[] = [];
    page.on("response", (response) => {
      const url = response.url();
      if (
        response.status() >= 500 &&
        (url.startsWith(apiBaseUrl) || url.includes("127.0.0.1:3100"))
      ) {
        serverErrors.push(`${response.status()} ${response.request().method()} ${url}`);
      }
    });

    const api = await request.newContext();
    const slug = unique("fqa");
    const tenant = await bootstrapTenant(api, slug);
    const matterCode = unique("FQA").toUpperCase();
    const matterTitle = `Functional QA matter ${matterCode}`;

    try {
      await signIn(page, tenant);
      const matterId = await createMatterFromUi(page, matterCode, matterTitle);
      await expectCaseTrackingBookmark(api, tenant.token, matterCode);

      const topLevelSurfaces: Array<[string, RegExp]> = [
        ["/app", /Good to have you back/i],
        ["/app/today", /^Today$/i],
        ["/app/matters", /Matter portfolio/i],
        ["/app/calendar", /^Calendar$/i],
        ["/app/hearings", /Hearings across your portfolio/i],
        ["/app/case-tracking", /CNR and case-number tracking/i],
        ["/app/cause-list", /Cause list/i],
        ["/app/clients", /Clients & engagements/i],
        ["/app/contracts", /Contract repository/i],
        ["/app/courts", /Court directory/i],
        ["/app/drafting", /Drafting studio/i],
        ["/app/drive", /Document review queue/i],
        ["/app/intake", /Legal intake queue/i],
        ["/app/mailbox", /Review queue/i],
        ["/app/outside-counsel", /Outside counsel & spend/i],
        ["/app/portfolio", /Portfolio health/i],
        ["/app/recommendations", /^Recommendations$/i],
        ["/app/research", /Grounded legal research/i],
        ["/app/research/saved", /Saved research/i],
        ["/app/statutes", /Bare Acts/i],
        ["/app/admin", /Admin & governance/i],
        ["/app/admin/billing", /Plan, usage, invoices, and credits/i],
        ["/app/admin/billing/usage", /Usage and spend report/i],
        ["/app/admin/email-templates", /Email templates/i],
        ["/app/admin/employees", /Employee directory/i],
        ["/app/admin/inbound-email", /Inbound email/i],
        ["/app/admin/integrations", /^Integrations$/i],
        ["/app/admin/matter-billing", /Matter billing/i],
        ["/app/admin/microsoft365", /Microsoft 365/i],
        ["/app/admin/notifications", /Notification delivery and recovery/i],
        ["/app/admin/outlook", /Outlook configuration/i],
        ["/app/admin/provider-operations", /Provider operations/i],
        ["/app/admin/roles", /Custom role templates/i],
        ["/app/admin/teams", /^Teams$/i],
        ["/app/platform-admin", /Access denied|Platform admin/i],
      ];

      for (const [route, expectedText] of topLevelSurfaces) {
        await expectSurface(page, route, expectedText);
      }

      await expectSurface(page, `/app/matters/${matterId}`, /Matter summary/i);

      await expectSurface(page, `/app/matters/${matterId}/hearings`, /Upcoming hearings/i);
      await page.getByTestId("schedule-hearing-open").click();
      const hearingDialog = page.getByRole("dialog");
      await hearingDialog.getByTestId("schedule-hearing-date").fill(plusDays(21));
      await hearingDialog
        .getByLabel(/Forum \/ bench/i)
        .fill("Delhi High Court, Functional QA Bench");
      await hearingDialog.getByLabel(/Purpose \/ stage/i).fill("Functional QA hearing");
      await hearingDialog.getByTestId("schedule-hearing-submit").click();
      await expect(hearingDialog).toBeHidden({ timeout: 15_000 });
      await expect(page.getByText(/Scheduled:/).first()).toBeVisible({
        timeout: 15_000,
      });

      await expectSurface(page, `/app/matters/${matterId}/documents`, /No documents attached yet/i);
      const filePath = makeUploadFixture(
        `${matterCode.toLowerCase()}-functional-note.txt`,
        "Functional QA upload body for local end-to-end verification.",
      );
      await page.setInputFiles('[data-testid="matter-attachment-file-input"]', filePath);
      await expect(page.getByText(path.basename(filePath)).first()).toBeVisible({
        timeout: 15_000,
      });

      const matterSurfaces: Array<[string, RegExp]> = [
        [`/app/matters/${matterId}/billing`, /Billing setup|Invoices/i],
        [`/app/matters/${matterId}/communications`, /^Communications$/i],
        [`/app/matters/${matterId}/drafts`, /Drafting studio/i],
        [`/app/matters/${matterId}/knowledge-graph`, /Legal Knowledge Graph|Legal knowledge graph unavailable/i],
        [`/app/matters/${matterId}/litigation-intelligence`, /Litigation Intelligence Review|Litigation intelligence review unavailable/i],
        [`/app/matters/${matterId}/outside-counsel`, /Outside counsel/i],
        [
          `/app/matters/${matterId}/predictive-intelligence`,
          /Source-backed litigation signals|Predictive intelligence (?:unavailable|is disabled)/i,
        ],
        [`/app/matters/${matterId}/recommendations`, /AI Recommendations/i],
        [`/app/matters/${matterId}/statutes`, /Statutes referenced/i],
        [`/app/matters/${matterId}/strategy`, /Strategy Plan/i],
        [`/app/matters/${matterId}/tasks`, /^Tasks$/i],
        [`/app/matters/${matterId}/timeline`, /Matter timeline/i],
        [`/app/matters/${matterId}/audit`, /Matter audit/i],
      ];

      for (const [route, expectedText] of matterSurfaces) {
        await expectSurface(page, route, expectedText);
      }

      await page.getByRole("button", { name: "Open user menu" }).click();
      await page.getByTestId("sign-out").click();
      await page.waitForURL(/\/sign-in(\?|$)/);
      await expect(
        page.getByRole("heading", { name: /Sign in to your workspace/i }),
      ).toBeVisible();

      expect(serverErrors).toEqual([]);
    } finally {
      await api.dispose();
    }
  });
});
