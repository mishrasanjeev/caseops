/**
 * Ram 2026-08-24 canonical acceptance.
 *
 * Run this exact file against a fresh local production build, then against the
 * exact deployed release. Production media is disabled by its config.
 */
import {
  expect,
  request as playwrightRequest,
  test,
  type APIRequestContext,
  type Locator,
  type Page,
} from "@playwright/test";

const envOr = (key: string, fallback: string): string =>
  (process.env[key] ?? "").trim() || fallback;

const BASE_URL = envOr(
  "PROD_BASE_URL",
  envOr("CASEOPS_WEB_BASE_URL", "http://127.0.0.1:3100"),
);
const hostname = new URL(BASE_URL).hostname;
const IS_LOCAL = hostname === "127.0.0.1" || hostname === "localhost";
const API_BASE_URL = envOr(
  "PROD_API_BASE_URL",
  IS_LOCAL
    ? `http://127.0.0.1:${envOr("CASEOPS_E2E_API_PORT", "8000")}`
    : "https://api.caseops.ai",
);
const RUN_ID = `${Date.now().toString(36)}-${Math.random()
  .toString(36)
  .slice(2, 8)}`;
const LOCAL_SLUG = `ram-aug24-${RUN_ID}`.toLowerCase();
const COMPANY_SLUG = envOr(
  "CASEOPS_RAM_PROD_SLUG",
  IS_LOCAL ? LOCAL_SLUG : "legal",
);
const TESTER_EMAIL = envOr(
  "CASEOPS_RAM_PROD_EMAIL",
  IS_LOCAL ? `${LOCAL_SLUG}@example.com` : "hari.gupta@gmail.com",
);
const LOCAL_PASSWORD = "RamAug24Local!";

function password(): string {
  const value =
    process.env.CASEOPS_RAM_PROD_PASSWORD?.trim() ||
    process.env.CASEOPS_RAM_LOCAL_PASSWORD?.trim() ||
    (IS_LOCAL ? LOCAL_PASSWORD : "");
  if (!value) {
    throw new Error(
      "CASEOPS_RAM_PROD_PASSWORD or CASEOPS_RAM_LOCAL_PASSWORD is required.",
    );
  }
  return value;
}

async function expectStatus(
  response: { status(): number; text(): Promise<string> },
  expected: number,
  label: string,
): Promise<void> {
  const detail = response.status() === expected ? "" : ` ${await response.text()}`;
  expect(response.status(), `${label}.${detail}`).toBe(expected);
}

async function ensureLocalOwner(request: APIRequestContext): Promise<void> {
  if (!IS_LOCAL) return;
  const login = await request.post(`${API_BASE_URL}/api/auth/login`, {
    data: {
      company_slug: COMPANY_SLUG,
      email: TESTER_EMAIL,
      password: password(),
    },
  });
  if (login.status() === 200) return;
  await expectStatus(login, 401, "fresh local owner login probe");
  const bootstrap = await request.post(`${API_BASE_URL}/api/bootstrap/company`, {
    data: {
      company_name: "CaseOps August 24 Regression LLP",
      company_slug: COMPANY_SLUG,
      company_type: "law_firm",
      owner_full_name: "Ram August 24 Tester",
      owner_email: TESTER_EMAIL,
      owner_password: password(),
    },
  });
  await expectStatus(bootstrap, 200, "bootstrap local owner and workspace data");
}

async function signIn(page: Page): Promise<void> {
  await page.goto(`${BASE_URL}/sign-in`);
  await page.locator("#company-slug").fill(COMPANY_SLUG);
  await page.locator("#email").fill(TESTER_EMAIL);
  await page.locator("#password").fill(password());
  const responsePromise = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/api/auth/login" &&
      response.request().method() === "POST",
    { timeout: 30_000 },
  );
  await page.locator('button[type="submit"]').click();
  await expectStatus(await responsePromise, 200, "explicit tester sign-in");
  await page.waitForURL(/\/app(?:[/?]|$)/);
}

async function establishApiSession(page: Page): Promise<void> {
  const login = await page.request.post(`${API_BASE_URL}/api/auth/login`, {
    data: {
      company_slug: COMPANY_SLUG,
      email: TESTER_EMAIL,
      password: password(),
    },
  });
  await expectStatus(login, 200, "journal-watch API sign-in");
  const session = await login.json();
  await page.goto(`${BASE_URL}/`);
  await page.evaluate((context) => {
    window.localStorage.setItem("caseops.session.context", JSON.stringify(context));
  }, {
    company: session.company,
    user: session.user,
    membership: session.membership,
    capabilities: session.capabilities,
  });
}

async function assertInsideViewport(
  page: Page,
  locator: Locator,
  label: string,
): Promise<{ x: number; y: number; width: number; height: number }> {
  await expect(locator, `${label} must be visible`).toBeVisible();
  const box = await locator.boundingBox();
  const viewport = page.viewportSize();
  expect(box, `${label} must have a rendered box`).not.toBeNull();
  expect(viewport).not.toBeNull();
  expect(box!.width, `${label} must not collapse`).toBeGreaterThan(20);
  expect(box!.x, `${label} must not be left-clipped`).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width, `${label} must not be right-clipped`).toBeLessThanOrEqual(
    viewport!.width + 0.5,
  );
  return box!;
}

test.describe.serial("Ram 2026-08-24 local and deployed regressions", () => {
  test.setTimeout(180_000);

  test.beforeAll(async () => {
    const request = await playwrightRequest.newContext();
    try {
      await ensureLocalOwner(request);
    } finally {
      await request.dispose();
    }
  });

  test("exact deployed API and web identify the release under test", async ({
    page,
  }) => {
    test.skip(IS_LOCAL, "Exact release identity is a production deployment gate.");
    const expectedSha = envOr("CASEOPS_EXPECTED_RELEASE_SHA", "").toLowerCase();
    expect(expectedSha).toMatch(/^[0-9a-f]{40}$/);
    const [apiBuild, webBuild] = await Promise.all([
      page.request.get(`${API_BASE_URL}/api/build`),
      page.request.get(`${BASE_URL}/api/release-identity`),
    ]);
    await expectStatus(apiBuild, 200, "API release identity");
    await expectStatus(webBuild, 200, "web release identity");
    expect((await apiBuild.json()).release_sha).toBe(expectedSha);
    expect((await webBuild.json()).release_sha).toBe(expectedSha);
  });

  test("BUG-001: every portfolio control remains visible and non-overlapping around responsive breakpoints", async ({
    page,
  }) => {
    await signIn(page);

    for (const viewport of [
      { width: 390, height: 844 },
      { width: 1280, height: 900 },
      { width: 1440, height: 900 },
      { width: 1536, height: 960 },
    ]) {
      await page.setViewportSize(viewport);
      await page.goto(`${BASE_URL}/app/ip/portfolio/`);
      await expect(
        page.getByRole("heading", { name: "Trademark portfolio" }),
      ).toBeVisible();

      const section = page.getByRole("region", { name: "Portfolio controls" });
      const search = page.locator("#ip-portfolio-search");
      const searchBox = await assertInsideViewport(page, search, "portfolio search");
      expect(
        searchBox.width,
        `portfolio search must retain useful width at ${viewport.width}px`,
      ).toBeGreaterThanOrEqual(viewport.width < 500 ? 180 : 220);

      const controls = [
        ["search action", page.getByRole("button", { name: "Search portfolio" })],
        ["jurisdiction", page.getByRole("combobox", { name: "Jurisdiction" })],
        ["phase", page.getByRole("combobox", { name: "Phase" })],
        ["status", page.getByRole("combobox", { name: "Status" })],
        ["saved view", page.getByRole("combobox", { name: "Saved view" })],
        ["columns", page.getByRole("button", { name: "Choose portfolio columns" })],
        ["more filters", page.getByRole("button", { name: "More portfolio filters" })],
      ] as const;
      for (const [label, locator] of controls) {
        await assertInsideViewport(page, locator, label);
      }

      const bounds = await section.evaluate((element) => ({
        clientWidth: element.clientWidth,
        scrollWidth: element.scrollWidth,
      }));
      expect(bounds.scrollWidth).toBeLessThanOrEqual(bounds.clientWidth + 1);

      const actionBox = await page
        .getByRole("button", { name: "Search portfolio" })
        .boundingBox();
      expect(actionBox).not.toBeNull();
      expect(
        searchBox.x + searchBox.width,
        "search field must not overlap its submit action",
      ).toBeLessThanOrEqual(actionBox!.x + 0.5);
    }
  });

  test("BUG-002: a legal user creates a real server-scoped dry run without internal hashes or approval gates", async ({
    page,
  }) => {
    await signIn(page);
    await page.goto(`${BASE_URL}/app/admin/data-governance/`);
    await expect(
      page.getByRole("heading", { name: "Data-governance integrity" }),
    ).toBeVisible();
    await expect(page.getByLabel("Registered data class")).toBeVisible();
    await expect(page.getByLabel(/Target identifier/i)).toHaveCount(0);
    await expect(page.getByLabel("Target type")).toHaveCount(0);
    await expect(page.getByRole("button", { name: /request approval/i })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /^approve$/i })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /^reject$/i })).toHaveCount(0);

    await page
      .getByLabel("Registered data class")
      .selectOption("tenant_data_operations");
    await page.getByLabel(/Evidence reference/i).fill(`e2e://ram-2026-08-24/${RUN_ID}`);

    const responsePromise = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname ===
          "/api/admin/data-governance/operations/dry-runs/tenant-scope" &&
        response.request().method() === "POST",
      { timeout: 30_000 },
    );
    await page
      .getByRole("button", { name: "Create non-executable dry run" })
      .click();
    const response = await responsePromise;
    await expectStatus(response, 201, "create tenant-scoped dry run");
    const requestBody = response.request().postDataJSON() as Record<string, unknown>;
    expect(requestBody).not.toHaveProperty("target_identifier_hash");
    expect(requestBody).not.toHaveProperty("target_type");
    expect(requestBody).not.toHaveProperty("candidate_record_count");
    expect(requestBody.data_class_ids).toEqual(["tenant_data_operations"]);

    await expect(page.getByTestId("dry-run-detail")).toContainText("Manifest detail");
    await expect(page.getByTestId("dry-run-detail")).toContainText("1 item(s)");
    await expect(page.getByTestId("dry-run-detail")).toContainText(
      "This record cannot execute an operation",
    );
  });

  test("IPLF-052: the exact release serves journal-watch data and responsive operator views", async ({
    page,
  }) => {
    await establishApiSession(page);
    const workspaceResponsePromise = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === "/api/ip/watch" &&
        response.request().method() === "GET",
      { timeout: 30_000 },
    );

    await page.setViewportSize({ width: 360, height: 800 });
    await page.goto(`${BASE_URL}/app/ip/watch`);
    const workspaceResponse = await workspaceResponsePromise;
    await expectStatus(workspaceResponse, 200, "journal-watch workspace data");
    const workspace = (await workspaceResponse.json()) as Record<string, unknown>;
    for (const collection of [
      "profiles",
      "hits",
      "publications",
      "ingestion_runs",
      "handoffs",
    ]) {
      expect(Array.isArray(workspace[collection]), `${collection} must be an array`).toBe(
        true,
      );
    }

    await expect(
      page.getByRole("heading", { name: "Trademark journal watch" }),
    ).toBeVisible();
    await expect(page.getByLabel("Docket scope")).toBeVisible();

    for (const viewport of [
      { width: 360, height: 800 },
      { width: 639, height: 900 },
      { width: 640, height: 900 },
      { width: 1280, height: 900 },
    ]) {
      await page.setViewportSize(viewport);
      const boxes = [];
      for (const name of ["Hits", "Profiles", "Journal intake", "Runs"]) {
        const box = await assertInsideViewport(
          page,
          page.getByRole("button", { name, exact: true }),
          `${name} watch view at ${viewport.width}px`,
        );
        expect(box.width).toBeGreaterThan(viewport.width < 640 ? 100 : 70);
        boxes.push(box);
      }
      for (let left = 0; left < boxes.length; left += 1) {
        for (let right = left + 1; right < boxes.length; right += 1) {
          const horizontal =
            boxes[left].x < boxes[right].x + boxes[right].width &&
            boxes[left].x + boxes[left].width > boxes[right].x;
          const vertical =
            boxes[left].y < boxes[right].y + boxes[right].height &&
            boxes[left].y + boxes[left].height > boxes[right].y;
          expect(
            horizontal && vertical,
            `watch views ${left} and ${right} must not overlap at ${viewport.width}px`,
          ).toBe(false);
        }
      }
    }

    await page.getByRole("button", { name: "Profiles", exact: true }).click();
    await expect(page.getByRole("heading", { name: "New watch profile" })).toBeVisible();
    await page.getByRole("button", { name: "Runs", exact: true }).click();
    if ((workspace.ingestion_runs as unknown[]).length === 0) {
      await expect(page.getByRole("heading", { name: "No ingestion runs" })).toBeVisible();
    } else {
      await expect(page.getByRole("table")).toBeVisible();
      await expect(page.getByRole("columnheader", { name: "Started" })).toBeVisible();
      await expect(page.getByRole("columnheader", { name: "Provider" })).toBeVisible();
    }

    await page.goto(`${BASE_URL}/law-firms`);
    await expect(
      page.getByRole("heading", { name: "Trademark journal watch" }),
    ).toBeVisible();
    await expect(
      page.getByText(/Live provider polling stays fail-closed until licensing and credentials are approved/),
    ).toBeVisible();
  });
});
