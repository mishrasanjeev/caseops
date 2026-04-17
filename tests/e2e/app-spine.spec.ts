import { expect, request, test } from "@playwright/test";
import type { APIRequestContext } from "@playwright/test";

import { apiBaseUrl } from "./support/env";

const PASSWORD = "SpinePass123!";

type BootstrapInput = {
  slug: string;
  name: string;
  ownerEmail: string;
  ownerName: string;
};

async function bootstrapViaApi(
  api: APIRequestContext,
  input: BootstrapInput,
): Promise<void> {
  const response = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: input.name,
      company_slug: input.slug,
      company_type: "law_firm",
      owner_full_name: input.ownerName,
      owner_email: input.ownerEmail,
      owner_password: PASSWORD,
    },
  });
  if (response.status() === 409) {
    // Previous test run already bootstrapped this slug. That's fine.
    return;
  }
  expect(response.status()).toBe(200);
}

function uniqueSlug(prefix: string): string {
  const suffix = Math.random().toString(36).slice(2, 8);
  return `${prefix}-${suffix}`;
}

test.describe("App spine", () => {
  test("sign-in page rejects obviously-invalid input", async ({ page }) => {
    await page.goto("/sign-in");
    await expect(page.getByRole("heading", { name: /Sign in to your workspace/i })).toBeVisible();

    // Zod rejects a slug with spaces.
    await page.locator("#company-slug").fill("Not A Slug");
    await page.locator("#email").fill("not-an-email");
    await page.locator("#password").fill("x");
    await page.getByRole("button", { name: /^Sign in$/ }).click();
    await expect(page.getByText(/Lowercase letters, digits, and hyphens/i)).toBeVisible();
    await expect(page.getByText(/Enter a valid work email/i)).toBeVisible();
  });

  test("sign-in → dashboard → matter cockpit → tabs → sign out", async ({
    page,
    browser,
  }) => {
    const slug = uniqueSlug("spine");
    const input: BootstrapInput = {
      slug,
      name: `${slug} Firm`,
      ownerEmail: `owner@${slug}.in`,
      ownerName: "Spine Owner",
    };
    const api = await request.newContext();
    try {
      await bootstrapViaApi(api, input);
    } finally {
      await api.dispose();
    }

    // Sign in.
    await page.goto("/sign-in");
    await page.locator("#company-slug").fill(input.slug);
    await page.locator("#email").fill(input.ownerEmail);
    await page.locator("#password").fill(PASSWORD);
    await page.getByRole("button", { name: /^Sign in$/ }).click();

    // Dashboard.
    await page.waitForURL("**/app");
    await expect(
      page.getByRole("heading", { name: /Good to have you back/i }),
    ).toBeVisible();
    await expect(page.getByText(/Active matters/i)).toBeVisible();

    // Navigate to Matters.
    await page.getByRole("link", { name: "Matters", exact: true }).click();
    await page.waitForURL("**/app/matters");
    await expect(page.getByRole("heading", { name: "Matter portfolio" })).toBeVisible();

    // Create a matter.
    const code = `SPINE-${Math.random().toString(36).slice(2, 6).toUpperCase()}`;
    await page.getByTestId("new-matter-trigger").first().click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await dialog.getByLabel("Title").fill("Spine matter");
    await dialog.getByLabel("Matter code").fill(code);
    await dialog.getByLabel("Practice area").fill("Commercial");
    await dialog.getByLabel("Client name").fill("Spine Industries");
    await dialog.getByLabel("Opposing party").fill("Opposing Holdings");
    const createResponse = page.waitForResponse(
      (r) =>
        r.url().includes("/api/matters/") &&
        r.request().method() === "POST",
    );
    await dialog.getByRole("button", { name: "Create matter" }).click();
    const created = await createResponse;
    if (!created.ok()) {
      const body = await created.text().catch(() => "<no body>");
      throw new Error(`Matter create failed: ${created.status()} ${body}`);
    }
    // Wait for success toast / dialog close.
    await expect(dialog).toBeHidden();
    await expect(page.getByText(code, { exact: false }).first()).toBeVisible();

    // Open the cockpit by clicking the matter row.
    await page.getByText("Spine matter", { exact: false }).first().click();
    await page.waitForURL(/\/app\/matters\/[0-9a-f-]+/);
    await expect(
      page.getByRole("heading", { name: "Spine matter", level: 1 }),
    ).toBeVisible();

    // Tab navigation works.
    await page.getByRole("link", { name: "Documents", exact: true }).click();
    await page.waitForURL(/\/documents$/);
    await expect(page.getByText(/No documents attached yet/i)).toBeVisible();

    await page.getByRole("link", { name: "Billing", exact: true }).click();
    await page.waitForURL(/\/billing$/);
    await expect(page.getByText("Total billed")).toBeVisible();

    await page.getByRole("link", { name: "Audit", exact: true }).click();
    await page.waitForURL(/\/audit$/);
    await expect(page.getByRole("heading", { name: "Audit trail" })).toBeVisible();

    await page.getByRole("link", { name: "Overview", exact: true }).click();
    await page.waitForURL(/\/matters\/[0-9a-f-]+$/);
    await expect(page.getByRole("heading", { name: /Matter summary/i })).toBeVisible();

    // Sign out flow.
    await page.getByRole("button", { name: "Open user menu" }).click();
    await page.getByTestId("sign-out").click();
    await page.waitForURL(/\/sign-in(\?|$)/);
    await expect(
      page.getByRole("heading", { name: /Sign in to your workspace/i }),
    ).toBeVisible();

    // The /app route now redirects back to /sign-in with a next param.
    await page.goto("/app");
    await page.waitForURL(/\/sign-in\?next=/);

    // Session store is cleared.
    const storedToken = await page.evaluate(() =>
      window.localStorage.getItem("caseops.session.token"),
    );
    expect(storedToken).toBeNull();
    void browser; // parameter kept to request independent context fixtures
  });

  test("roadmap stubs for unbuilt sections load without errors", async ({ page }) => {
    const slug = uniqueSlug("stubs");
    const input: BootstrapInput = {
      slug,
      name: `${slug} Firm`,
      ownerEmail: `owner@${slug}.in`,
      ownerName: "Stub Owner",
    };
    const api = await request.newContext();
    try {
      await bootstrapViaApi(api, input);
    } finally {
      await api.dispose();
    }

    await page.goto("/sign-in");
    await page.locator("#company-slug").fill(input.slug);
    await page.locator("#email").fill(input.ownerEmail);
    await page.locator("#password").fill(PASSWORD);
    await page.getByRole("button", { name: /^Sign in$/ }).click();
    await page.waitForURL("**/app");
    // Wait for the authenticated shell (sidebar) to render before interacting.
    await expect(
      page.getByRole("link", { name: "Home", exact: true }),
    ).toBeVisible();

    const stubs = [
      { label: "Hearings", heading: /Portfolio-wide hearings/ },
      { label: "Research", heading: /Grounded legal research/ },
      { label: "Drafting", heading: /Drafting Studio/ },
      { label: "Recommendations", heading: /Explainable recommendations/ },
      { label: "Contracts", heading: /Contract repository/ },
      { label: "Outside Counsel", heading: /Outside counsel/ },
      { label: "Portfolio", heading: /Firm-wide portfolio/ },
      { label: "Admin", heading: /Admin & governance/ },
    ];
    for (const stub of stubs) {
      await page.getByRole("link", { name: stub.label, exact: true }).click();
      await expect(page.getByRole("heading", { name: stub.heading })).toBeVisible();
    }
  });
});
