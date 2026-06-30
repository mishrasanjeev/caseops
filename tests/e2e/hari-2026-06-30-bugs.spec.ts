/**
 * Hari 2026-06-30 workbook regressions.
 *
 * BUG-001: a matter created from /app/matters with case identifiers must be
 * automatically linked to eCourt/case tracking.
 */
import { expect, request, test } from "@playwright/test";
import type { APIRequestContext, Page } from "@playwright/test";

import { apiBaseUrl } from "./support/env";

const PASSWORD = "HariJun30Bugs!";

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
      company_name: "Hari 2026-06-30 LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Hari Jun30 Owner",
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

test.describe("Hari 2026-06-30 bugs", () => {
  test.setTimeout(120_000);

  test("BUG-001: New Matter auto-links eCourt case tracking when case identity is supplied", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("h63001");
    const { token, ownerEmail } = await bootstrap(api, slug);
    const matterCode = unique("H630").toUpperCase();
    const matterTitle = `Hari Jun30 eCourt matter ${matterCode}`;

    await signIn(page, slug, ownerEmail);
    await page.goto("/app/matters");
    await page.locator("main").getByTestId("new-matter-trigger").first().click();
    await page.getByLabel("Title").fill(matterTitle);
    await page.getByLabel("Matter code").fill(matterCode);
    await page.getByLabel("Practice area").fill("Litigation");
    await page.getByLabel("Client name").fill("Example Petitioner");
    await page.getByLabel("Opposing party").fill("Example Respondent");
    await page.getByLabel("Case number").fill("WP(C) 1/2026");
    await page.getByLabel("CNR number").fill("dlhc-0100-1234-2026");
    await expect(page.getByTestId("new-matter-forum-state")).toHaveValue("Delhi");
    await page.getByRole("button", { name: /Create matter/i }).click();

    await expect
      .poll(
        async () => {
          const resp = await api.get(`${apiBaseUrl}/api/case-tracking/bookmarks`, {
            headers: { Authorization: `Bearer ${token}` },
          });
          expect(resp.status(), await resp.text()).toBe(200);
          const body = (await resp.json()) as {
            bookmarks: Array<{
              matter_id: string | null;
              name: string | null;
              tracked_case: {
                case_title: string;
                cnr_number: string | null;
                case_number: string | null;
                court_name: string | null;
              };
            }>;
          };
          const bookmark = body.bookmarks.find(
            (item) => item.tracked_case.cnr_number === "DLHC010012342026",
          );
          return Boolean(
            bookmark?.matter_id &&
              bookmark.name === matterCode &&
              bookmark.tracked_case.case_title === matterTitle &&
              bookmark.tracked_case.case_number === "WP(C) 1/2026" &&
              bookmark.tracked_case.court_name === "Delhi High Court",
          );
        },
        { timeout: 15_000 },
      )
      .toBe(true);

    await page.goto("/app/case-tracking");
    await expect(page.getByText(matterCode)).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText("Delhi High Court").first()).toBeVisible();

    await api.dispose();
  });
});
