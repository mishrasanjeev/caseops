import { expect, test, type Page } from "@playwright/test";

const PROD_BASE_URL = process.env.PROD_BASE_URL ?? "https://caseops.ai";
const PROD_API_BASE_URL =
  process.env.PROD_API_BASE_URL ?? "https://api.caseops.ai";
const COMPANY_SLUG = process.env.CASEOPS_RAM_PROD_SLUG ?? "legal";
const TESTER_EMAIL =
  process.env.CASEOPS_RAM_PROD_EMAIL ?? "hari.gupta@gmail.com";

function required(name: string): string {
  const value = process.env[name]?.trim() ?? "";
  if (!value) throw new Error(`${name} is required for production release proof.`);
  return value;
}

async function signIn(page: Page): Promise<void> {
  await page.goto(`${PROD_BASE_URL}/sign-in`);
  await page.locator("#company-slug").fill(COMPANY_SLUG);
  await page.locator("#email").fill(TESTER_EMAIL);
  await page.locator("#password").fill(required("CASEOPS_RAM_PROD_PASSWORD"));
  const login = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/api/auth/login" &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  expect((await login).status()).toBe(200);
  await page.waitForURL(new RegExp(`${PROD_BASE_URL}/app(?:[/?]|$)`));
}

async function csrfHeaders(page: Page): Promise<Record<string, string>> {
  const cookies = await page.context().cookies();
  const csrf = cookies.find((cookie) => cookie.name === "caseops_csrf")?.value;
  expect(csrf, "caseops_csrf cookie must exist after sign-in").toBeTruthy();
  return { "X-CSRF-Token": csrf! };
}

async function approvedBookmarkId(
  page: Page,
  headers: Record<string, string>,
): Promise<string> {
  const configuredId = process.env.CASEOPS_QA_TRACKED_CASE_BOOKMARK_ID?.trim();
  if (configuredId) return configuredId;

  const listed = await page.request.get(
    `${PROD_API_BASE_URL}/api/case-tracking/bookmarks`,
  );
  const listedBody = await listed.json();
  expect(listed.status(), JSON.stringify(listedBody)).toBe(200);
  const tagged = listedBody.bookmarks.find(
    (bookmark: { tracked_case?: { metadata?: Record<string, unknown> } }) =>
      bookmark.tracked_case?.metadata?.release_smoke_fixture === true,
  );
  if (tagged) return tagged.id as string;

  const fixtureCnr = required("CASEOPS_QA_TRACKED_CASE_CNR");
  const searched = await page.request.post(
    `${PROD_API_BASE_URL}/api/case-tracking/search`,
    { headers, data: { cnr_number: fixtureCnr } },
  );
  const searchedBody = await searched.json();
  expect(searched.status(), JSON.stringify(searchedBody)).toBe(200);
  const result = searchedBody.results.find(
    (row: { cnr_number?: string }) => row.cnr_number === fixtureCnr,
  );
  expect(result, `No exact provider result for QA CNR ${fixtureCnr}`).toBeTruthy();

  const created = await page.request.post(
    `${PROD_API_BASE_URL}/api/case-tracking/bookmarks`,
    {
      headers,
      data: {
        ...result,
        name: "CaseOps exact-release provider canary",
        notification_enabled: false,
        metadata: {
          release_smoke_fixture: true,
          release_smoke_fixture_cnr: fixtureCnr,
        },
      },
    },
  );
  const createdBody = await created.json();
  expect(created.status(), JSON.stringify(createdBody)).toBe(201);
  expect(createdBody.tracked_case.metadata.release_smoke_fixture).toBe(true);
  return createdBody.id as string;
}

test.describe("Ram 2026-08-05 exact-release case tracking canary", () => {
  test.setTimeout(180_000);

  test("freshens the approved QA case and opens its protected source at 360px", async ({
    page,
  }) => {
    const releaseSha = required("CASEOPS_EXPECTED_RELEASE_SHA");
    expect(releaseSha).toMatch(/^[0-9a-f]{40}$/);

    const [apiIdentity, webIdentity] = await Promise.all([
      page.request.get(`${PROD_API_BASE_URL}/api/build`),
      page.request.get(`${PROD_BASE_URL}/api/release-identity`),
    ]);
    expect(apiIdentity.status(), await apiIdentity.text()).toBe(200);
    expect(webIdentity.status(), await webIdentity.text()).toBe(200);
    expect((await apiIdentity.json()).release_sha).toBe(releaseSha);
    expect((await webIdentity.json()).release_sha).toBe(releaseSha);

    await signIn(page);
    const headers = await csrfHeaders(page);
    const bookmarkId = await approvedBookmarkId(page, headers);
    const canary = await page.request.post(
      `${PROD_API_BASE_URL}/api/case-tracking/bookmarks/${bookmarkId}/release-smoke`,
      { headers, data: { release_sha: releaseSha } },
    );
    const canaryBody = await canary.json();
    expect(canary.status(), JSON.stringify(canaryBody)).toBe(200);
    expect(canaryBody.release_sha).toBe(releaseSha);
    expect(["success", "no_change"]).toContain(canaryBody.response_class);
    expect(canaryBody.operation_id).toBeTruthy();
    expect(canaryBody.bookmark.id).toBe(bookmarkId);
    expect(canaryBody.bookmark.tracked_case.freshness_status).toBe("fresh");
    expect(canaryBody.bookmark.tracked_case.provider_health).toBe("healthy");
    expect(canaryBody.bookmark.tracked_case.last_provider_successful_at).toBeTruthy();

    const sourcePath = canaryBody.source_update.source_url as string;
    expect(sourcePath).toBe(
      `/api/case-tracking/bookmarks/${bookmarkId}/updates/${canaryBody.source_update.id}/source`,
    );
    const source = await page.request.get(`${PROD_API_BASE_URL}${sourcePath}`);
    expect(source.status(), await source.text()).toBe(200);
    expect(source.headers()["content-disposition"]).toMatch(/^attachment;/);
    expect((await source.body()).byteLength).toBeGreaterThan(16);

    await page.setViewportSize({ width: 360, height: 800 });
    await page.goto(`${PROD_BASE_URL}/app/case-tracking`);
    await expect(
      page.getByRole("heading", { name: "CNR and case-number tracking" }),
    ).toBeVisible();
    await expect(page.getByTestId("case-tracking-support-matrix")).toBeVisible();

    const bookmark = page.getByTestId(`case-tracking-bookmark-${bookmarkId}`);
    await expect(bookmark).toBeVisible({ timeout: 30_000 });
    const refresh = bookmark.getByRole("button", { name: "Refresh" });
    await expect(refresh).toBeVisible();
    await expect(refresh).toBeEnabled();
    const refreshBox = await refresh.boundingBox();
    expect(refreshBox).not.toBeNull();
    expect(refreshBox!.x).toBeGreaterThanOrEqual(0);
    expect(refreshBox!.x + refreshBox!.width).toBeLessThanOrEqual(360);

    await bookmark.getByRole("button").first().click();
    const update = page.getByTestId(
      `case-tracking-update-${canaryBody.source_update.id}`,
    );
    await expect(update).toBeVisible();
    const sourceLink = update.getByRole("link", { name: "Source" });
    await expect(sourceLink).toBeVisible();
    const href = await sourceLink.getAttribute("href");
    expect(href).toBe(`${PROD_API_BASE_URL}${sourcePath}`);
    await expect(sourceLink).toHaveAttribute("target", "_blank");
    await expect(sourceLink).toHaveAttribute("rel", "noopener noreferrer");
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBeLessThanOrEqual(360);
  });
});
