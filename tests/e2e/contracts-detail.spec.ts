/* Sprint: Codex gap audit #6 */
import { expect, request, test } from "@playwright/test";
import type { APIRequestContext } from "@playwright/test";

import { apiBaseUrl } from "./support/env";

const PASSWORD = "ContractsPass123!";

async function bootstrap(
  api: APIRequestContext,
  slug: string,
): Promise<{ slug: string; token: string }> {
  const resp = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "Contracts Test LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Contracts Owner",
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

test.describe("Contract detail workspace (§4.4)", () => {
  test.setTimeout(120_000);

  test("create contract via API, switch through each tab", async ({ page }) => {
    const api = await request.newContext();
    const slug = unique("cd");
    const { token } = await bootstrap(api, slug);
    const authHeaders = { Authorization: `Bearer ${token}` };

    // POST a contract via API.
    const contractCode = `CT-${Math.random().toString(36).slice(2, 6).toUpperCase()}`;
    const createResp = await api.post(`${apiBaseUrl}/api/contracts/`, {
      headers: authHeaders,
      data: {
        title: "ACME Master Services Agreement",
        contract_code: contractCode,
        counterparty_name: "ACME Services Pvt Ltd",
        contract_type: "msa",
        status: "under_review",
      },
    });
    expect(createResp.status()).toBe(200);
    const contract = (await createResp.json()) as { id: string; title: string };

    // Sign in via UI.
    await page.goto("/sign-in");
    await page.locator("#company-slug").fill(slug);
    await page.locator("#email").fill(`owner-${slug}@example.com`);
    await page.locator("#password").fill(PASSWORD);
    await page.getByRole("button", { name: /^Sign in$/ }).click();
    await page.waitForURL(/\/app/);

    // Go to the contract detail page.
    await page.goto(`/app/contracts/${contract.id}`);
    await expect(
      page.getByRole("heading", { name: contract.title }),
    ).toBeVisible({ timeout: 15_000 });

    // The actual tab labels on this page (inspected from the source) are:
    // Overview, Attachments (N), Clauses (N), Obligations (N), Playbook (N),
    // Redline. We use getByRole("tab") on each, then assert the matching
    // TabsContent becomes the active panel.
    const tablist = page.getByRole("tablist").first();
    await expect(tablist).toBeVisible();

    for (const label of [
      /^Overview$/,
      /^Attachments/,
      /^Clauses/,
      /^Obligations/,
      /^Playbook/,
      /^Redline$/,
    ]) {
      const tab = tablist.getByRole("tab", { name: label });
      await expect(tab).toBeVisible();
      await tab.click();
      // Radix Tabs sets data-state="active" on the selected tab.
      await expect(tab).toHaveAttribute("data-state", "active");
    }

    // Final tab: Redline. The empty-state ("Pick an attachment") should
    // render since we haven't uploaded any DOCX.
    await expect(page.getByText(/Pick an attachment/i)).toBeVisible();
  });
});
