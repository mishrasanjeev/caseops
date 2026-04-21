/* Sprint: Codex gap audit #6 */
import { expect, request, test } from "@playwright/test";
import type { APIRequestContext } from "@playwright/test";

import { apiBaseUrl } from "./support/env";

const PASSWORD = "IntakePass123!";

type BootstrapResult = { slug: string; token: string };

async function bootstrap(
  api: APIRequestContext,
  slug: string,
): Promise<BootstrapResult> {
  const resp = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "Intake Test LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Intake Owner",
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

test.describe("Intake queue (§4 intake)", () => {
  test.setTimeout(120_000);

  test("file intake via API, triage to triaging, promote to matter", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("it");
    const { token } = await bootstrap(api, slug);
    const authHeaders = { Authorization: `Bearer ${token}` };

    // Create intake request via API (fastest path — UI dialog is exercised
    // separately by the unit tests).
    const intakeResp = await api.post(`${apiBaseUrl}/api/intake/requests`, {
      headers: authHeaders,
      data: {
        title: "Review vendor MSA for ACME",
        category: "contract_review",
        priority: "high",
        requester_name: "Priya Requester",
        description:
          "Need a quick review of the ACME master services agreement before sign-off on Friday.",
      },
    });
    expect(intakeResp.status()).toBe(200);
    const intake = (await intakeResp.json()) as { id: string; title: string };

    // UI sign-in so the browser session matches the API session.
    await page.goto("/sign-in");
    await page.locator("#company-slug").fill(slug);
    await page.locator("#email").fill(`owner-${slug}@example.com`);
    await page.locator("#password").fill(PASSWORD);
    await page.getByRole("button", { name: /^Sign in$/ }).click();
    await page.waitForURL(/\/app/);

    // Navigate to intake and assert the row renders.
    await page.goto("/app/intake");
    const list = page.getByTestId("intake-request-list");
    await expect(list).toBeVisible();
    await expect(list.getByText(intake.title).first()).toBeVisible();

    // Patch status → triaging via API.
    const patchResp = await api.patch(
      `${apiBaseUrl}/api/intake/requests/${intake.id}`,
      {
        headers: authHeaders,
        data: { status: "triaging" },
      },
    );
    expect(patchResp.status()).toBe(200);

    // Promote via API with a fresh matter code.
    const matterCode = `INT-${Math.random().toString(36).slice(2, 6).toUpperCase()}`;
    const promoteResp = await api.post(
      `${apiBaseUrl}/api/intake/requests/${intake.id}/promote`,
      {
        headers: authHeaders,
        data: {
          matter_code: matterCode,
          practice_area: "commercial",
          forum_level: "high_court",
        },
      },
    );
    expect(promoteResp.status()).toBe(200);
    const promoted = (await promoteResp.json()) as {
      linked_matter_id: string | null;
      linked_matter_code: string | null;
    };
    expect(promoted.linked_matter_code).toBe(matterCode);

    // Assert the new matter surfaces on /app/matters.
    await page.goto("/app/matters");
    await expect(page.getByText(matterCode).first()).toBeVisible({
      timeout: 15_000,
    });
  });
});
