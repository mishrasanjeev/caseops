import { expect, request, test } from "@playwright/test";
import type { APIRequestContext, Page } from "@playwright/test";

import { apiBaseUrl } from "./support/env";

const PASSWORD = "Hari0707Pass123!";

function unique(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random()
    .toString(36)
    .slice(2, 8)}`;
}

async function expectOk(response: Awaited<ReturnType<APIRequestContext["post"]>>, label: string) {
  expect(response.ok(), `${label}: ${response.status()} ${await response.text()}`).toBe(true);
}

async function bootstrap(
  api: APIRequestContext,
  slug: string,
): Promise<{ token: string; ownerEmail: string }> {
  const ownerEmail = `owner-${slug}@example.com`;
  const response = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: `Hari 2026-07-07 ${slug}`,
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Hari 0707 Owner",
      owner_email: ownerEmail,
      owner_password: PASSWORD,
    },
  });
  await expectOk(response, "bootstrap");
  return { token: (await response.json()).access_token as string, ownerEmail };
}

async function signIn(page: Page, slug: string, email: string): Promise<void> {
  await page.goto("/sign-in");
  await page.locator("#company-slug").fill(slug);
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(PASSWORD);
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  await page.waitForURL(/\/app/);
}

async function createClient(
  api: APIRequestContext,
  token: string,
  name: string,
): Promise<string> {
  const response = await api.post(`${apiBaseUrl}/api/clients/`, {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      name,
      client_type: "corporate",
    },
  });
  await expectOk(response, "create client");
  return ((await response.json()) as { id: string }).id;
}

async function createMatter(
  api: APIRequestContext,
  token: string,
  code: string,
  opposingParty: string,
): Promise<string> {
  const response = await api.post(`${apiBaseUrl}/api/matters/`, {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      title: `Conflict review ${code}`,
      matter_code: code,
      client_name: "Neutral Local Client",
      opposing_party: opposingParty,
      practice_area: "litigation",
      forum_level: "high_court",
      court_name: "Delhi High Court",
      status: "intake",
      description: "Regression matter for the optional conflict-review workflow.",
    },
  });
  await expectOk(response, "create matter");
  return ((await response.json()) as { id: string }).id;
}

test.describe("Hari 2026-07-07 conflict-check bug regressions", () => {
  test.setTimeout(180_000);

  test("client-backed conflict scan stays usable but does not block activation", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("hari-0707");
    const { token, ownerEmail } = await bootstrap(api, slug);
    const existingClient = unique("Conflict Probe Client");
    await createClient(api, token, existingClient);
    const matterId = await createMatter(
      api,
      token,
      unique("H0707").toUpperCase(),
      existingClient,
    );
    await api.dispose();

    await signIn(page, slug, ownerEmail);
    await page.goto(`/app/matters/${matterId}`);

    const conflictCard = page.getByTestId("matter-conflict-card");
    await expect(conflictCard).toBeVisible();
    await expect(conflictCard).toContainText("No conflict check has been run yet.");

    await conflictCard.getByTestId("conflict-run-open").click();
    await page.getByTestId("conflict-run-opposing").fill(existingClient);
    const runResponse = page.waitForResponse(
      (response) =>
        response.url().includes(`/api/matters/${matterId}/conflict-checks`) &&
        response.request().method() === "POST",
    );
    await page.getByTestId("conflict-run-submit").click();
    expect((await runResponse).status()).toBe(200);
    await expect(conflictCard.getByTestId("conflict-status-pending")).toBeVisible();
    await expect(conflictCard).toContainText(existingClient);
    await expect(conflictCard).toContainText("client");

    await page.getByTestId("matter-edit-open").click();
    await page.getByTestId("matter-edit-status").selectOption("active");
    await expect(page.getByTestId("matter-edit-active-conflict-hint")).toHaveCount(0);

    const activation = page.waitForResponse(
      (response) =>
        response.url().endsWith(`/api/matters/${matterId}`) &&
        response.request().method() === "PATCH",
    );
    await page.getByTestId("matter-edit-save").click();
    const activationResponse = await activation;
    expect(activationResponse.status()).toBe(200);
    expect(((await activationResponse.json()) as { status: string }).status).toBe(
      "active",
    );
    await expect(page.getByTestId("matter-edit-form")).toBeHidden();
    await expect(page.getByTestId("matter-edit-conflict-gate")).toHaveCount(0);

    const clearResponse = page.waitForResponse(
      (response) =>
        response.url().includes("/api/conflict-checks/") &&
        response.request().method() === "PATCH",
    );
    await conflictCard.getByTestId("conflict-resolve-clear").click();
    expect((await clearResponse).status()).toBe(200);
    await expect(conflictCard.getByTestId("conflict-status-cleared")).toBeVisible();
  });
});
