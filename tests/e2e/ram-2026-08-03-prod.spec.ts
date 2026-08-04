import { expect, test, type Page } from "@playwright/test";

const PROD_BASE_URL = process.env.PROD_BASE_URL ?? "https://caseops.ai";
const PROD_API_BASE_URL =
  process.env.PROD_API_BASE_URL ?? "https://api.caseops.ai";
const COMPANY_SLUG = process.env.CASEOPS_RAM_PROD_SLUG ?? "legal";
const TESTER_EMAIL =
  process.env.CASEOPS_RAM_PROD_EMAIL ?? "hari.gupta@gmail.com";

function requiredPassword(): string {
  const password = process.env.CASEOPS_RAM_PROD_PASSWORD?.trim() ?? "";
  if (!password) {
    throw new Error("CASEOPS_RAM_PROD_PASSWORD is required for production proof.");
  }
  return password;
}

async function signIn(page: Page): Promise<void> {
  await page.goto(`${PROD_BASE_URL}/sign-in`);
  await page.locator("#company-slug").fill(COMPANY_SLUG);
  await page.locator("#email").fill(TESTER_EMAIL);
  await page.locator("#password").fill(requiredPassword());
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

test.describe("Ram 2026-08-03 deployed saved research source actions", () => {
  test.setTimeout(120_000);

  test("IPLF-003C preserves the live API contract and fail-closed mobile UI", async ({
    page,
  }) => {
    await signIn(page);
    const headers = await csrfHeaders(page);

    const recentResponse = await page.request.get(
      `${PROD_API_BASE_URL}/api/authorities/documents/recent?limit=20`,
    );
    expect(recentResponse.status(), await recentResponse.text()).toBe(200);
    const recent = await recentResponse.json();
    const sourceBacked = recent.documents.find(
      (document: { source_reference?: string | null }) =>
        typeof document.source_reference === "string" &&
        document.source_reference.trim().length > 0,
    );
    expect(
      sourceBacked,
      "production authority corpus must retain at least one source reference",
    ).toBeTruthy();

    const suffix = Date.now().toString(36).toUpperCase();
    const annotationTitle = `IPLF-003C production proof ${suffix}`;
    const createdResponse = await page.request.post(
      `${PROD_API_BASE_URL}/api/authorities/documents/${sourceBacked.id}/annotations`,
      {
        headers,
        data: {
          kind: "flag",
          title: annotationTitle,
          body: "Ephemeral release verification; removed by the same test.",
        },
      },
    );
    const created = await createdResponse.json();
    expect(createdResponse.status(), JSON.stringify(created)).toBe(201);

    try {
      const savedResponse = await page.request.get(
        `${PROD_API_BASE_URL}/api/authorities/annotations`,
      );
      expect(savedResponse.status(), await savedResponse.text()).toBe(200);
      const saved = await savedResponse.json();
      const liveRow = saved.annotations.find(
        (annotation: { id: string }) => annotation.id === created.id,
      );
      expect(liveRow).toBeTruthy();
      expect(liveRow.authority_source).toBe(sourceBacked.source);
      expect(liveRow.authority_source_reference).toBe(
        sourceBacked.source_reference,
      );
      expect(liveRow.authority_source_action).toMatchObject({
        label: "Open source",
        source_reference: sourceBacked.source_reference,
        opens_new_tab: true,
      });
      expect(
        ["available", "missing", "unverified", "blocked", "quarantined"],
      ).toContain(liveRow.authority_source_action.state);
      if (liveRow.authority_source_action.state === "available") {
        expect(liveRow.authority_source_action.open_url).toBe(
          `/api/source-actions/targets/authority_document/${sourceBacked.id}/open`,
        );
      } else {
        expect(liveRow.authority_source_action.open_url).toBeNull();
      }
      expect(liveRow.authority_source_action).toMatchObject({
        target_type: "authority_document",
        target_id: sourceBacked.id,
      });

      const opaqueOpenUrl = `${PROD_API_BASE_URL}/api/source-actions/targets/authority_document/${sourceBacked.id}/open?origin=saved_research`;
      const opened = await page.request.get(opaqueOpenUrl, { maxRedirects: 0 });
      if (liveRow.authority_source_action.state === "available") {
        expect(opened.status(), await opened.text()).toBe(307);
        expect(opened.headers()["cache-control"]).toBe("no-store");
        expect(opened.headers()["referrer-policy"]).toBe("no-referrer");
        expect(opened.headers().location).toMatch(/^https:\/\//);
      } else {
        expect(opened.status(), await opened.text()).toBe(409);
        expect(opened.headers()["x-source-state"]).toBe(
          liveRow.authority_source_action.state,
        );
      }

      await page.route("**/api/authorities/annotations**", (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            annotations: [
              {
                ...liveRow,
                id: "annotation-available",
                title: "Verified source proof",
                authority_title: "Source-backed saved authority",
                authority_source: "official",
                authority_source_reference:
                  "https://www.sci.gov.in/source-proof.pdf",
                authority_source_action: {
                  state: "available",
                  label: "Open source",
                  open_url:
                    `/api/source-actions/targets/authority_document/${sourceBacked.id}/open`,
                  source_reference:
                    "https://www.sci.gov.in/source-proof.pdf",
                  reason: null,
                  opens_new_tab: true,
                  target_type: "authority_document",
                  target_id: sourceBacked.id,
                },
                authority_neutral_citation: "2026 INSC 303",
              },
              {
                ...liveRow,
                id: "annotation-unverified",
                title: "Provider refresh needed",
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
                  target_id: sourceBacked.id,
                },
                authority_neutral_citation: "2026:DHC:303",
              },
            ],
          }),
        }),
      );

      await page.setViewportSize({ width: 360, height: 800 });
      await page.goto(`${PROD_BASE_URL}/app/research/saved`);
      await expect(
        page.getByRole("heading", { name: "Saved research" }),
      ).toBeVisible();
      await expect(page.getByText("Source-backed saved authority")).toBeVisible();
      await expect(page.getByText(/2026 INSC 303/)).toBeVisible();

      const openSource = page.getByTestId("source-action-open");
      await expect(openSource).toBeVisible();
      await expect(openSource).toHaveAttribute(
        "href",
        new RegExp(
          `/api/source-actions/targets/authority_document/${sourceBacked.id}/open$`,
        ),
      );
      await expect(openSource).toHaveAttribute("target", "_blank");
      await expect(openSource).toHaveAttribute("rel", "noopener noreferrer");
      await expect(openSource).toHaveAttribute("referrerpolicy", "no-referrer");

      await expect(page.getByText("Citation survives source failure")).toBeVisible();
      await expect(page.getByText(/2026:DHC:303/)).toBeVisible();
      const unverified = page.getByTestId("source-action-unverified");
      await expect(unverified).toBeVisible();
      await expect(unverified).toHaveText("unverified");
      await expect(unverified.locator("a")).toHaveCount(0);
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth),
      ).toBeLessThanOrEqual(360);
    } finally {
      const deleted = await page.request.delete(
        `${PROD_API_BASE_URL}/api/authorities/annotations/${created.id}`,
        { headers },
      );
      expect(deleted.status(), await deleted.text()).toBe(204);
    }
  });
});
