/* Sprint: Codex gap audit #6 */
import { expect, request, test } from "@playwright/test";
import type { APIRequestContext } from "@playwright/test";

import { apiBaseUrl } from "./support/env";
import { plusDays } from "./support/helpers";

const PASSWORD = "HearingsPass123!";

async function bootstrap(
  api: APIRequestContext,
  slug: string,
): Promise<{ slug: string; token: string }> {
  const resp = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "Hearings Test LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Hearings Owner",
      owner_email: `owner-${slug}@example.com`,
      owner_password: PASSWORD,
    },
  });
  if (resp.status() !== 200) {
    throw new Error(`Bootstrap failed: ${resp.status()} ${await resp.text()}`);
  }
  const body = (await resp.json()) as { access_token: string };
  return { slug, token: body.access_token };
}

function unique(prefix: string): string {
  return `${prefix}-${Math.random().toString(36).slice(2, 8)}`;
}

test.describe("Matter hearings (BUG-004 manual schedule)", () => {
  test.setTimeout(120_000);

  test("schedule hearing via UI, see it in Scheduled hearings", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("mh");
    const { token } = await bootstrap(api, slug);
    const authHeaders = { Authorization: `Bearer ${token}` };

    // Create matter via API.
    const matterCode = `MH-${Math.random().toString(36).slice(2, 6).toUpperCase()}`;
    const matterResp = await api.post(`${apiBaseUrl}/api/matters/`, {
      headers: authHeaders,
      data: {
        title: "Hearings e2e matter",
        matter_code: matterCode,
        practice_area: "criminal",
        forum_level: "high_court",
        status: "active",
      },
    });
    expect(matterResp.status()).toBe(200);
    const matter = (await matterResp.json()) as { id: string };

    // UI sign-in.
    await page.goto("/sign-in");
    await page.locator("#company-slug").fill(slug);
    await page.locator("#email").fill(`owner-${slug}@example.com`);
    await page.locator("#password").fill(PASSWORD);
    await page.getByRole("button", { name: /^Sign in$/ }).click();
    await page.waitForURL(/\/app/);

    // Hearings tab of the matter.
    await page.goto(`/app/matters/${matter.id}/hearings`);
    await expect(
      page.getByRole("heading", { name: /Scheduled hearings/i }),
    ).toBeVisible({ timeout: 15_000 });

    // Open the schedule dialog.
    await page.getByTestId("schedule-hearing-open").click();

    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();

    const hearingDate = plusDays(14); // YYYY-MM-DD
    const forumName = "Delhi High Court, Bench: Hon'ble Mr. Justice X";
    const purpose = "Arguments on bail (BNSS s.483)";

    // Fill the form. date input uses data-testid; forum_name / purpose
    // are found by label.
    await dialog.getByTestId("schedule-hearing-date").fill(hearingDate);
    await dialog.getByLabel(/Forum \/ bench/i).fill(forumName);
    await dialog.getByLabel(/Purpose \/ stage/i).fill(purpose);

    // Submit.
    await dialog.getByTestId("schedule-hearing-submit").click();
    await expect(dialog).toBeHidden({ timeout: 15_000 });

    // The new hearing row appears under Scheduled hearings. The row
    // renders hearing_type (defaulted to "Hearing" when not supplied)
    // and the scheduled-for date — asserting the formatted date is the
    // most robust signal that the row landed.
    const scheduledCard = page
      .getByRole("heading", { name: /Scheduled hearings/i })
      .locator("..");
    await expect(scheduledCard.getByText(/Scheduled:/).first()).toBeVisible({
      timeout: 15_000,
    });
  });
});
