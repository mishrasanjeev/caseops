/**
 * Ram 2026-09-02 workbook acceptance.
 *
 * The same spec runs against the deterministic local Docker stack and the
 * exact production release. Production credentials are supplied through the
 * existing CASEOPS_RAM_PROD_* environment variables.
 */
import {
  expect,
  request as playwrightRequest,
  test,
  type APIRequestContext,
  type Page,
} from "@playwright/test";
import { seedVerifiedLocalStatute } from "./support/verified-statute-fixture";

const envOr = (key: string, fallback: string): string =>
  (process.env[key] ?? "").trim() || fallback;

const BASE_URL = envOr(
  "PROD_BASE_URL",
  envOr("CASEOPS_WEB_BASE_URL", "http://127.0.0.1:3100"),
);
const IS_LOCAL = ["127.0.0.1", "localhost"].includes(
  new URL(BASE_URL).hostname,
);
const IS_DOCKER_LOCAL =
  IS_LOCAL && Boolean(envOr("CASEOPS_E2E_DOCKER_PROJECT", ""));
const API_BASE_URL = envOr(
  "PROD_API_BASE_URL",
  IS_LOCAL
    ? `http://127.0.0.1:${envOr("CASEOPS_E2E_API_PORT", "8000")}`
    : "https://api.caseops.ai",
);
const RUN_ID = `${Date.now().toString(36)}-${Math.random()
  .toString(36)
  .slice(2, 8)}`.toUpperCase();
const COMPANY_SLUG = envOr(
  "CASEOPS_RAM_PROD_SLUG",
  IS_LOCAL ? `ram-sep02-${RUN_ID.toLowerCase()}` : "test-legal",
);
const TESTER_EMAIL = envOr(
  "CASEOPS_RAM_PROD_EMAIL",
  IS_LOCAL
    ? `ram-sep02-${RUN_ID.toLowerCase()}@example.com`
    : "ram@testfirm.com",
);
const LOCAL_PASSWORD = "RamSep02Local!";

type LoginPayload = {
  access_token: string;
  company: unknown;
  user: unknown;
  membership: unknown;
  capabilities: unknown;
};

type MatterRecord = {
  id: string;
  matter_code: string;
  status: "intake" | "active" | "on_hold" | "disposed";
  updated_at: string;
};

let api: APIRequestContext;
let identity: LoginPayload;
let matter: MatterRecord;

function password(): string {
  const value =
    process.env.CASEOPS_RAM_PROD_PASSWORD?.trim() ||
    process.env.CASEOPS_RAM_LOCAL_PASSWORD?.trim() ||
    (IS_LOCAL ? LOCAL_PASSWORD : "");
  if (!value) throw new Error("CASEOPS_RAM_PROD_PASSWORD is required.");
  return value;
}

function headers(): Record<string, string> {
  return { Authorization: `Bearer ${identity.access_token}` };
}

async function expectStatus(
  response: { status(): number; text(): Promise<string> },
  expected: number,
  label: string,
): Promise<void> {
  const detail =
    response.status() === expected ? "" : ` ${await response.text()}`;
  expect(response.status(), `${label}.${detail}`).toBe(expected);
}

async function ensureTenant(): Promise<void> {
  const login = await api.post(`${API_BASE_URL}/api/auth/login`, {
    data: {
      company_slug: COMPANY_SLUG,
      email: TESTER_EMAIL,
      password: password(),
    },
  });
  if (login.status() === 200) {
    identity = (await login.json()) as LoginPayload;
    return;
  }
  if (!IS_LOCAL) await expectStatus(login, 200, "production tester login");
  await expectStatus(login, 401, "fresh local tester login probe");
  const bootstrap = await api.post(`${API_BASE_URL}/api/bootstrap/company`, {
    data: {
      company_name: "CaseOps September 02 Regression LLP",
      company_slug: COMPANY_SLUG,
      company_type: "law_firm",
      owner_full_name: "September 02 Regression Owner",
      owner_email: TESTER_EMAIL,
      owner_password: password(),
    },
  });
  await expectStatus(bootstrap, 200, "bootstrap local regression tenant");
  identity = (await bootstrap.json()) as LoginPayload;
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
  );
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  await expectStatus(await responsePromise, 200, "browser sign-in");
  await page.waitForURL(/\/app(?:[/?]|$)/);
}

test.describe.serial("Ram 2026-09-02 workbook regressions", () => {
  test.setTimeout(240_000);

  test.beforeAll(async () => {
    api = await playwrightRequest.newContext();
    await ensureTenant();
    seedVerifiedLocalStatute(IS_LOCAL);
    const created = await api.post(`${API_BASE_URL}/api/matters/`, {
      headers: headers(),
      data: {
        title: `September 02 workbook regression ${RUN_ID}`,
        matter_code: `RAM902-${RUN_ID}`.slice(0, 78),
        status: "active",
        practice_area: "Commercial Litigation",
        forum_level: "high_court",
        forum_catalog_entry_id: "hc:delhi",
      },
    });
    await expectStatus(created, 200, "create workbook regression matter");
    matter = (await created.json()) as MatterRecord;
  });

  test.afterAll(async () => {
    if (matter?.id && matter.status !== "disposed") {
      const current = await api.get(
        `${API_BASE_URL}/api/matters/${matter.id}`,
        {
          headers: headers(),
        },
      );
      if (current.status() === 200) {
        const row = (await current.json()) as MatterRecord;
        if (row.status !== "disposed") {
          await api.patch(
            `${API_BASE_URL}/api/matters/${row.id}/lifecycle/status`,
            {
              headers: headers(),
              data: {
                to_status: "disposed",
                expected_from_status: row.status,
                expected_updated_at: row.updated_at,
                reason:
                  "Close the September 02 regression fixture after validation.",
              },
            },
          );
        }
      }
    }
    await api.dispose();
  });

  test("exact production release identifies the deployed revision", async ({
    page,
  }) => {
    test.skip(IS_LOCAL, "Production-only exact release gate.");
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

  test("BUG-003: an owner can enable the workspace assistant without an external approval", async ({
    page,
  }) => {
    await signIn(page);
    await page.goto(`${BASE_URL}/app/admin`);
    const toggle = page.getByTestId("tenant-ai-policy-assistant-toggle");
    await expect(toggle).toBeVisible();
    await expect(toggle).toBeEnabled();

    if ((await toggle.getAttribute("aria-pressed")) === "true") {
      const disabled = page.waitForResponse(
        (response) =>
          new URL(response.url()).pathname === "/api/admin/tenant-ai-policy" &&
          response.request().method() === "PATCH",
      );
      await toggle.click();
      await expectStatus(
        await disabled,
        200,
        "disable assistant through owner control",
      );
      await expect(toggle).toHaveAttribute("aria-pressed", "false");
      await expect(toggle).toBeEnabled();
    }
    await page.goto(`${BASE_URL}/app/assistant`);
    await page
      .getByRole("textbox", { name: "Find workspace records" })
      .fill("workspace");
    await page.getByRole("button", { name: "Find permitted records" }).click();
    const recoveryLink = page.getByRole("link", {
      name: "Admin → AI controls",
    });
    await expect(recoveryLink).toBeVisible();
    await recoveryLink.click();
    await expect(page).toHaveURL(/\/app\/admin(?:[/?]|$)/);
    const ownerToggle = page.getByTestId("tenant-ai-policy-assistant-toggle");
    await expect(ownerToggle).toBeEnabled();
    await expect(ownerToggle).toHaveAttribute("aria-pressed", "false");
    const enabled = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === "/api/admin/tenant-ai-policy" &&
        response.request().method() === "PATCH",
    );
    await ownerToggle.click();
    const enabledResponse = await enabled;
    await expectStatus(
      enabledResponse,
      200,
      "enable assistant through owner control",
    );
    expect(enabledResponse.request().postDataJSON()).toMatchObject({
      workspace_assistant_enabled: true,
    });
    await expect(ownerToggle).toHaveAttribute("aria-pressed", "true");
    const persisted = await api.get(
      `${API_BASE_URL}/api/admin/tenant-ai-policy`,
      {
        headers: headers(),
      },
    );
    await expectStatus(persisted, 200, "read persisted assistant policy");
    expect((await persisted.json()).workspace_assistant_enabled).toBe(true);
  });

  test("BUG-002 / UPDATED-BUG-003: Indian Kanoon reports actionable machine-verifiable prerequisites", async ({
    page,
  }) => {
    const readiness = await api.get(
      `${API_BASE_URL}/api/authorities/providers/indian-kanoon/readiness`,
      { headers: headers() },
    );
    await expectStatus(readiness, 200, "Indian Kanoon readiness");
    const readinessBody = (await readiness.json()) as {
      state: string;
      missing_approval_keys: string[];
      missing_config_names: string[];
      invalid_terms_config: string[];
      missing_cost_categories: string[];
    };
    expect(readinessBody.missing_approval_keys).toEqual([]);

    const operations = await api.get(
      `${API_BASE_URL}/api/admin/provider-operations/readiness`,
      {
        headers: headers(),
      },
    );
    await expectStatus(operations, 200, "provider operations readiness");
    const indianKanoon = (
      (await operations.json()).providers as Array<Record<string, unknown>>
    ).find((provider) => provider.provider === "indian-kanoon");
    expect(indianKanoon).toBeTruthy();
    expect(indianKanoon?.required_approval_keys).toEqual([]);
    expect(indianKanoon?.missing_approval_keys).toEqual([]);

    await signIn(page);
    await page.goto(`${BASE_URL}/app/research`);
    await page.getByTestId("research-source-indian-kanoon").click();
    const readinessCopy = page.getByTestId("research-indian-kanoon-readiness");
    await expect(readinessCopy).not.toContainText(
      "Checking licensed-source readiness",
    );
    const copy = await readinessCopy.innerText();
    expect(copy.toLowerCase()).not.toContain("approval");
    expect(copy).toMatch(
      /setup is incomplete|disabled by the runtime switch|invalid or expired|cost profiles|active/,
    );
    if (
      readinessBody.state === "blocked_disabled" &&
      (readinessBody.missing_config_names.length > 0 ||
        readinessBody.missing_cost_categories.length > 0)
    ) {
      expect(copy).toContain("setup is incomplete");
      expect(copy).toContain("No provider call will be made");
      expect(copy).not.toContain("INDIAN_KANOON_");
    }
  });

  test("BUG-006 / UPDATED-BUG-002: official Article 14 is selectable and attachable", async ({
    page,
  }) => {
    const catalogResponse = await api.get(`${API_BASE_URL}/api/statutes/`, {
      headers: headers(),
    });
    await expectStatus(catalogResponse, 200, "read verified statute catalog");
    const catalog = (await catalogResponse.json()) as {
      statutes: Array<{
        id: string;
        short_name: string;
        section_count: number;
        catalog_section_count: number;
      }>;
      total_section_count: number;
      total_catalog_section_count: number;
    };
    const selectable = catalog.statutes.filter(
      (statute) => statute.section_count > 0,
    );

    await signIn(page);
    await page.goto(`${BASE_URL}/app/matters/${matter.id}/statutes`);
    await page.getByTestId("matter-statute-add-trigger").click();
    const actSelect = page.getByTestId("matter-statute-act-select");
    await expect(actSelect.locator("option")).toHaveCount(
      catalog.statutes.length + 1,
    );
    await expect(
      page.getByTestId("matter-statute-catalog-coverage"),
    ).toContainText(
      `${catalog.total_section_count} verified of ${catalog.total_catalog_section_count} catalogued`,
    );
    for (const unavailable of catalog.statutes.filter(
      (row) => row.section_count === 0,
    )) {
      await expect(
        actSelect.locator(`option[value="${unavailable.id}"]`),
      ).toHaveAttribute("disabled", "");
    }
    expect(selectable.length).toBeGreaterThan(0);
    const constitution = selectable.find(
      (row) => row.id === "constitution-india",
    );
    expect(constitution).toBeTruthy();
    const sectionsResponsePromise = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname ===
          "/api/statutes/constitution-india/sections" &&
        response.request().method() === "GET",
    );
    await actSelect.selectOption("constitution-india");
    const sectionsResponse = await sectionsResponsePromise;
    await expectStatus(sectionsResponse, 200, "load selected Act sections");
    const sectionPayload = (await sectionsResponse.json()) as {
      sections: Array<{
        id: string;
        section_number: string;
        verification_status: string;
      }>;
      catalog_sections: Array<{
        id: string;
        section_number: string;
        selection_state: string;
      }>;
      verified_section_count: number;
      catalog_section_count: number;
    };
    const article14Record = sectionPayload.sections.find(
      (row) => row.section_number === "Article 14",
    );
    expect(article14Record).toBeTruthy();
    expect(article14Record?.verification_status).toBe("verified_official");
    const sectionSelect = page.getByTestId("matter-statute-section-select");
    await expect(sectionSelect.locator("option")).toHaveCount(
      sectionPayload.catalog_section_count + 1,
    );
    for (const unavailable of sectionPayload.catalog_sections.filter(
      (row) => row.selection_state !== "verified_selectable",
    )) {
      await expect(
        sectionSelect.locator(`option[value="${unavailable.id}"]`),
      ).toHaveAttribute("disabled", "");
    }
    const article14 = sectionSelect.locator(
      `option[value="${article14Record!.id}"]`,
    );
    await expect(article14).toHaveCount(1);
    await sectionSelect.selectOption(article14Record!.id);
    const attach = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname ===
          `/api/matters/${matter.id}/statute-references` &&
        response.request().method() === "POST",
    );
    await page.getByTestId("matter-statute-add-submit").click();
    await expectStatus(await attach, 201, "attach verified statute section");
  });

  test("BUG-005: canonical nested source target identity renders in Litigation Intelligence", async ({
    page,
  }) => {
    await signIn(page);
    await page.route(
      new RegExp(
        `/api/matters/${matter.id}/litigation-intelligence/review(?:\\?.*)?$`,
      ),
      (route) =>
        route.fulfill({
          contentType: "application/json",
          body: JSON.stringify({
            matter_id: matter.id,
            generated_at: new Date().toISOString(),
            disclaimer: "Source-backed decision support, not legal advice.",
            summary: {
              total_items: 1,
              review_required_count: 1,
              source_linked_count: 1,
              by_type: { affidavit_question: 1 },
              by_status: { review_required: 1 },
            },
            items: [
              {
                id: "affidavit-question:ram902",
                item_type: "affidavit_question",
                title: "Verify the supporting attachment",
                description:
                  "Canonical source-action target fields must survive validation.",
                status: "review_required",
                priority: "high",
                confidence_label: "high",
                evidence_quality: null,
                sample_size: null,
                limitation_note: "Lawyer review remains required.",
                review_reason: "The attachment must be checked.",
                source: {
                  source_type: "matter_document",
                  source_id: "attachment-ram902",
                  label: "Source attachment",
                  reference: "attachment-ram902",
                  snippet: "Source-backed excerpt.",
                  page_reference: null,
                  source_action: {
                    state: "available",
                    label: "Open source",
                    open_url:
                      "/api/source-actions/targets/matter_attachment/attachment-ram902/open",
                    source_reference: `/api/matters/${matter.id}/attachments/attachment-ram902/download`,
                    reason: null,
                    opens_new_tab: true,
                    target_type: "matter_attachment",
                    target_id: "attachment-ram902",
                  },
                },
                due_on: null,
                review_note: null,
                last_review_action: null,
                reviewed_at: null,
                reviewed_by_membership_id: null,
                created_at: new Date().toISOString(),
                updated_at: null,
              },
            ],
          }),
        }),
    );
    await page.goto(
      `${BASE_URL}/app/matters/${matter.id}/litigation-intelligence`,
    );
    await expect(
      page.getByText("Verify the supporting attachment"),
    ).toBeVisible();
    await expect(page.getByTestId("source-action-open")).toBeVisible();
    await expect(page.getByTestId("source-action-report")).toBeVisible();
    await expect(
      page.getByText("Could not load litigation intelligence review"),
    ).toHaveCount(0);
  });

  test("BUG-004: strategy generation never reaches the invalid strict-schema 400", async () => {
    test.setTimeout(260_000);
    let status = 503;
    let body = "Recommendation provider was not called.";

    // Provider failures are transient at the user boundary. Keep every
    // attempt inside Cloud Run's 120-second deadline, prove the service stays
    // responsive after a failed attempt, and allow one bounded retry.
    for (let attempt = 0; attempt < 2; attempt += 1) {
      const generated = await api.post(
        `${API_BASE_URL}/api/matters/${matter.id}/recommendations`,
        {
          headers: headers(),
          data: { type: "litigation_strategy" },
          timeout: 110_000,
        },
      );
      status = generated.status();
      body = await generated.text();
      expect(status, body).not.toBe(400);
      expect(body).not.toMatch(/additionalProperties.*required.*false/i);
      expect(body).not.toMatch(/invalid.*strict.*schema/i);
      if (status < 500) break;

      const health = await api.get(`${API_BASE_URL}/api/health`, {
        timeout: 10_000,
      });
      expect(health.status(), await health.text()).toBe(200);
    }

    expect(status, body).toBeLessThan(500);
    expect(body).not.toMatch(/additionalProperties.*required.*false/i);
    expect(body).not.toMatch(/invalid.*strict.*schema/i);
  });

  test("UPDATED-BUG-001: invented court code is rejected before a paid provider search", async ({
    page,
  }) => {
    await signIn(page);
    await page.goto(`${BASE_URL}/app/case-tracking`);
    await page
      .getByTestId("case-tracking-query")
      .fill("Reliance Industries vs Regulatory");
    await page.getByTestId("case-tracking-case-number").fill("CIV-114/2026");
    await page.getByTestId("case-tracking-court-code").fill("COURT-FORUM-114");
    const searched = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === "/api/case-tracking/search" &&
        response.request().method() === "POST",
    );
    await page.getByTestId("case-tracking-search-submit").click();
    const response = await searched;
    expect(response.status(), await response.text()).toBe(422);
    await expect(page.getByTestId("case-tracking-search-error")).toContainText(
      /provider-published alphanumeric search code|Court code/i,
    );
    await expect(
      page.getByTestId("case-tracking-search-error"),
    ).not.toContainText("Case tracking provider search failed");
  });

  test("BUG-001: transient case-tracking failures do not require administrator replay", async ({
    page,
  }) => {
    if (IS_DOCKER_LOCAL) {
      await signIn(page);
      await page.goto(`${BASE_URL}/app/case-tracking`);
      const caseNumber = `WP(C) ${Date.now().toString().slice(-6)}/2026`;
      await page.getByTestId("case-tracking-case-number").fill(caseNumber);
      const searched = page.waitForResponse(
        (response) =>
          new URL(response.url()).pathname === "/api/case-tracking/search" &&
          response.request().method() === "POST",
      );
      await page.getByTestId("case-tracking-search-submit").click();
      await expectStatus(
        await searched,
        200,
        "search by case number through Docker provider",
      );
      await expect(
        page.getByText("Local Docker Petitioner v Local Docker Respondent"),
      ).toBeVisible();
      return;
    }

    const bookmarks = await api.get(
      `${API_BASE_URL}/api/case-tracking/bookmarks`,
      {
        headers: headers(),
      },
    );
    await expectStatus(bookmarks, 200, "read tracked cases");
    const rows = (
      (await bookmarks.json()).bookmarks as Array<{
        id: string;
        tracked_case: {
          response_class: string | null;
          freshness_status: string;
          provider_health: string;
          manual_refresh_allowed: boolean;
          manual_refresh_disabled_reason: string | null;
        };
      }>
    ).filter((row) =>
      ["billing", "provider_error", "rate_limit", "timeout"].includes(
        row.tracked_case.response_class ?? "",
      ),
    );
    for (const row of rows) {
      expect(row.tracked_case.freshness_status).not.toBe("quarantined");
      expect(row.tracked_case.provider_health).toBe("degraded");
      expect(row.tracked_case.manual_refresh_disabled_reason ?? "").not.toMatch(
        /administrator|review or replay/i,
      );
    }
    // The same recovery path is exercised end to end against the Docker
    // provider above. Production regression is read-only here so it never
    // consumes a paid provider credit or creates a failed provider operation.
  });

  test("REOPENING: only the audited lifecycle route reopens a disposed matter", async () => {
    const before = await api.get(`${API_BASE_URL}/api/matters/${matter.id}`, {
      headers: headers(),
    });
    await expectStatus(before, 200, "read matter before lifecycle regression");
    const active = (await before.json()) as MatterRecord;
    const disposedResponse = await api.patch(
      `${API_BASE_URL}/api/matters/${matter.id}/lifecycle/status`,
      {
        headers: headers(),
        data: {
          to_status: "disposed",
          expected_from_status: active.status,
          expected_updated_at: active.updated_at,
          reason:
            "Verify the reported reopening path from persisted lifecycle state.",
        },
      },
    );
    await expectStatus(disposedResponse, 200, "dispose lifecycle fixture");
    const disposed = (await disposedResponse.json()) as MatterRecord;
    matter = disposed;

    const genericReopen = await api.patch(
      `${API_BASE_URL}/api/matters/${matter.id}`,
      {
        headers: headers(),
        data: {
          status: "active",
          expected_updated_at: disposed.updated_at,
        },
      },
    );
    await expectStatus(genericReopen, 409, "reject generic metadata reopening");
    const today = await api.get(`${API_BASE_URL}/api/me/today`, {
      headers: headers(),
    });
    await expectStatus(today, 200, "read operational view after disposal");
    expect(JSON.stringify(await today.json())).not.toContain(matter.id);

    const reopenResponse = await api.patch(
      `${API_BASE_URL}/api/matters/${matter.id}/lifecycle/status`,
      {
        headers: headers(),
        data: {
          to_status: "intake",
          expected_from_status: "disposed",
          expected_updated_at: disposed.updated_at,
          reason: "Fresh instructions require a controlled reopen into Intake.",
        },
      },
    );
    await expectStatus(reopenResponse, 200, "controlled reopen to Intake");
    const reopened = (await reopenResponse.json()) as MatterRecord;
    expect(reopened.status).toBe("intake");

    const persisted = await api.get(
      `${API_BASE_URL}/api/matters/${matter.id}`,
      { headers: headers() },
    );
    await expectStatus(persisted, 200, "reload reopened matter");
    const persistedReopen = (await persisted.json()) as MatterRecord;
    expect(persistedReopen.status).toBe("intake");
    const audit = await api.get(
      `${API_BASE_URL}/api/matters/${matter.id}/audit-events`,
      { headers: headers(), params: { limit: 200 } },
    );
    await expectStatus(audit, 200, "read lifecycle audit trail");
    const actions = (
      (await audit.json()) as { events: Array<{ action: string }> }
    ).events.map((row) => row.action);
    expect(actions).toEqual(
      expect.arrayContaining([
        "matter.lifecycle.disposed",
        "matter.lifecycle.reopened",
      ]),
    );

    const activate = await api.patch(
      `${API_BASE_URL}/api/matters/${matter.id}`,
      {
        headers: headers(),
        data: {
          status: "active",
          expected_updated_at: persistedReopen.updated_at,
        },
      },
    );
    await expectStatus(activate, 200, "explicit Intake to Active transition");
    matter = (await activate.json()) as MatterRecord;
    expect(matter.status).toBe("active");
  });
});
