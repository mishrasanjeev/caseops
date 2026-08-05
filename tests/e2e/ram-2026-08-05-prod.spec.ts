import { expect, test, type Page } from "@playwright/test";

const PROD_BASE_URL = process.env.PROD_BASE_URL ?? "https://caseops.ai";
const PROD_API_BASE_URL =
  process.env.PROD_API_BASE_URL ?? "https://api.caseops.ai";
const COMPANY_SLUG = process.env.CASEOPS_RAM_PROD_SLUG ?? "legal";
const TESTER_EMAIL =
  process.env.CASEOPS_RAM_PROD_EMAIL ?? "hari.gupta@gmail.com";
const QA_COMPANY_SLUG = process.env.CASEOPS_QA_SLUG ?? "caseops-qa";
const QA_OWNER_EMAIL = process.env.CASEOPS_QA_EMAIL ?? "qa-bot@caseops.ai";

type StatuteSummary = {
  id: string;
  short_name: string;
  section_count: number;
  catalog_section_count: number;
  coverage_label: string;
};

type SectionSummary = {
  id: string;
  section_number: string;
  verification_status: string;
  source_locator_type: string;
  link_health_status: string;
  source_action: {
    state: string;
    open_url: string | null;
  } | null;
};

function requiredPassword(): string {
  const password = process.env.CASEOPS_RAM_PROD_PASSWORD?.trim() ?? "";
  if (!password) {
    throw new Error(
      "CASEOPS_RAM_PROD_PASSWORD is required for production proof.",
    );
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

async function signInQa(page: Page): Promise<void> {
  const password = process.env.CASEOPS_QA_PASSWORD?.trim() ?? "";
  if (!password) {
    throw new Error(
      "CASEOPS_QA_PASSWORD is required for the production notification proof.",
    );
  }
  await page.goto(`${PROD_BASE_URL}/sign-in`);
  await page.locator("#company-slug").fill(QA_COMPANY_SLUG);
  await page.locator("#email").fill(QA_OWNER_EMAIL);
  await page.locator("#password").fill(password);
  const login = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/api/auth/login" &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  expect((await login).status()).toBe(200);
  await page.waitForURL(new RegExp(`${PROD_BASE_URL}/app(?:[/?]|$)`));
}

test.describe("Ram 2026-08-05 deployed statute trust", () => {
  test.setTimeout(120_000);

  test("IPLF-006C serves truthful verified-only coverage and fail-closed mobile detail", async ({
    page,
  }) => {
    await signIn(page);

    const catalogResponse = await page.request.get(
      `${PROD_API_BASE_URL}/api/statutes/`,
    );
    expect(catalogResponse.status(), await catalogResponse.text()).toBe(200);
    const catalog = (await catalogResponse.json()) as {
      statutes: StatuteSummary[];
      total_section_count: number;
      total_catalog_section_count: number;
      coverage_label: string;
    };
    expect(catalog.coverage_label).toBe("Verified statutory text only");
    expect(catalog.statutes.length).toBeGreaterThan(0);
    expect(catalog.total_section_count).toBe(
      catalog.statutes.reduce(
        (total, statute) => total + statute.section_count,
        0,
      ),
    );
    expect(catalog.total_catalog_section_count).toBe(
      catalog.statutes.reduce(
        (total, statute) => total + statute.catalog_section_count,
        0,
      ),
    );
    for (const statute of catalog.statutes) {
      expect(statute.section_count).toBeLessThanOrEqual(
        statute.catalog_section_count,
      );
      expect(statute.coverage_label).toBe(
        `${statute.section_count} verified of ${statute.catalog_section_count} catalogued sections`,
      );
    }

    const statute =
      catalog.statutes.find((row) => row.catalog_section_count > 0) ??
      catalog.statutes[0]!;
    const sectionsResponse = await page.request.get(
      `${PROD_API_BASE_URL}/api/statutes/${encodeURIComponent(statute.id)}/sections`,
    );
    expect(sectionsResponse.status(), await sectionsResponse.text()).toBe(200);
    const sectionsPayload = (await sectionsResponse.json()) as {
      sections: SectionSummary[];
    };
    expect(sectionsPayload.sections).toHaveLength(statute.section_count);
    for (const section of sectionsPayload.sections) {
      expect(["verified_official", "verified_licensed"]).toContain(
        section.verification_status,
      );
      expect(section.source_locator_type).toBe("section_deep_link");
      expect(section.link_health_status).toBe("available");
      expect(section.source_action).toMatchObject({
        state: "available",
        open_url: `/api/source-actions/targets/statute_section/${section.id}/open`,
      });
    }

    await page.setViewportSize({ width: 360, height: 800 });
    await page.goto(`${PROD_BASE_URL}/app/statutes`);
    await expect(
      page.getByRole("heading", { name: "Bare Acts" }),
    ).toBeVisible();
    const tile = page.getByTestId(`statute-tile-${statute.id}`);
    await expect(tile).toContainText(
      `${statute.section_count} verified / ${statute.catalog_section_count} catalogued`,
    );
    expect(
      await page.evaluate(
        () =>
          document.documentElement.scrollWidth -
          document.documentElement.clientWidth,
      ),
    ).toBeLessThanOrEqual(1);

    await page.goto(
      `${PROD_BASE_URL}/app/statutes/${encodeURIComponent(statute.id)}`,
    );
    if (sectionsPayload.sections.length === 0) {
      await expect(
        page.getByRole("heading", { name: "No verified sections available" }),
      ).toBeVisible();
    } else {
      const section = sectionsPayload.sections[0];
      const detailResponse = await page.request.get(
        `${PROD_API_BASE_URL}/api/statutes/${encodeURIComponent(statute.id)}/sections/${encodeURIComponent(section.section_number)}`,
      );
      expect(detailResponse.status(), await detailResponse.text()).toBe(200);
      const detail = (await detailResponse.json()) as {
        section: {
          id: string;
          section_text: string | null;
          source_sha256: string | null;
          source_publisher: string | null;
          issuing_body: string | null;
          exact_source_version: string | null;
          source_retrieved_at: string | null;
          verification_status: string;
        };
      };
      expect(detail.section.id).toBe(section.id);
      expect(detail.section.section_text).toBeTruthy();
      expect(detail.section.source_sha256).toMatch(/^[a-f0-9]{64}$/);
      expect(detail.section.source_publisher).toBeTruthy();
      expect(detail.section.issuing_body).toBeTruthy();
      expect(detail.section.exact_source_version).toBeTruthy();
      expect(detail.section.source_retrieved_at).toBeTruthy();

      await page.goto(
        `${PROD_BASE_URL}/app/statutes/${encodeURIComponent(statute.id)}/sections/${encodeURIComponent(section.section_number)}`,
      );
      await expect(page.getByTestId("statute-section-text")).toContainText(
        detail.section.section_text!,
      );
      await expect(page.getByTestId("statute-source-metadata")).toContainText(
        detail.section.exact_source_version!,
      );
    }
    expect(
      await page.evaluate(
        () =>
          document.documentElement.scrollWidth -
          document.documentElement.clientWidth,
      ),
    ).toBeLessThanOrEqual(1);
  });
});

test.describe("Ram 2026-08-05 deployed notification convergence", () => {
  test.setTimeout(120_000);

  test("IPLF-007C persists a safe in-app intent with usable 360px controls", async ({
    page,
  }) => {
    await signInQa(page);
    await page.setViewportSize({ width: 360, height: 800 });
    await page.goto(`${PROD_BASE_URL}/app/admin/notifications`);

    await expect(
      page.getByRole("heading", { name: "Notification delivery and recovery" }),
    ).toBeVisible();
    const selfTest = page.getByTestId("notification-self-test");
    await expect(selfTest).toBeVisible();

    const responsePromise = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname ===
          "/api/notification-preferences/test" &&
        response.request().method() === "POST",
    );
    await selfTest.click();
    const response = await responsePromise;
    expect(response.status(), await response.text()).toBe(200);
    const payload = (await response.json()) as {
      intent: {
        id: string;
        channel: string;
        status: string;
        destination: string | null;
        destination_version: number;
      };
      message: string;
    };
    expect(payload.intent).toMatchObject({
      channel: "in_app",
      status: "delivered",
      destination: null,
      destination_version: 1,
    });
    expect(payload.message).toContain("without contacting an external provider");
    await expect(
      page.getByText(/without contacting an external provider/i),
    ).toBeVisible();

    const adminResponse = await page.request.get(
      `${PROD_API_BASE_URL}/api/admin/notifications`,
    );
    expect(adminResponse.status(), await adminResponse.text()).toBe(200);
    const adminPayload = (await adminResponse.json()) as {
      intents: Array<{ id: string; status: string; event_type: string }>;
      metrics: { delivered: number };
    };
    expect(adminPayload.intents).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          id: payload.intent.id,
          status: "delivered",
          event_type: "notification_test",
        }),
      ]),
    );
    expect(adminPayload.metrics.delivered).toBeGreaterThanOrEqual(1);
    await expect(
      page.getByTestId(`notification-intent-${payload.intent.id}`),
    ).toBeVisible();
    expect(
      await page.evaluate(
        () =>
          document.documentElement.scrollWidth -
          document.documentElement.clientWidth,
      ),
    ).toBeLessThanOrEqual(1);
  });
});
