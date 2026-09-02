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
import { spawnSync } from "node:child_process";

const envOr = (key: string, fallback: string): string =>
  (process.env[key] ?? "").trim() || fallback;

const BASE_URL = envOr(
  "PROD_BASE_URL",
  envOr("CASEOPS_WEB_BASE_URL", "http://127.0.0.1:13100"),
);
const IS_LOCAL = ["127.0.0.1", "localhost"].includes(new URL(BASE_URL).hostname);
const API_BASE_URL = envOr(
  "PROD_API_BASE_URL",
  IS_LOCAL
    ? `http://127.0.0.1:${envOr("CASEOPS_E2E_API_PORT", "18100")}`
    : "https://api.caseops.ai",
);
const RUN_ID = `${Date.now().toString(36)}-${Math.random()
  .toString(36)
  .slice(2, 8)}`.toUpperCase();
const COMPANY_SLUG = envOr(
  "CASEOPS_RAM_PROD_SLUG",
  IS_LOCAL ? `ram-sep02-${RUN_ID.toLowerCase()}` : "legal",
);
const TESTER_EMAIL = envOr(
  "CASEOPS_RAM_PROD_EMAIL",
  IS_LOCAL ? `ram-sep02-${RUN_ID.toLowerCase()}@example.com` : "hari.gupta@gmail.com",
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
  const detail = response.status() === expected ? "" : ` ${await response.text()}`;
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

function seedVerifiedLocalStatute(): void {
  if (!IS_LOCAL) return;
  const project = envOr("CASEOPS_E2E_DOCKER_PROJECT", "");
  const composeFile = envOr("CASEOPS_E2E_DOCKER_COMPOSE_FILE", "");
  if (!project || !composeFile) {
    throw new Error("Docker project metadata is required to seed the local statute fixture.");
  }
  const script = `
from datetime import UTC, datetime
from caseops_api.db.models import Statute, StatuteSection
from caseops_api.db.session import get_session_factory

now = datetime.now(UTC)
with get_session_factory()() as session:
    statute = session.get(Statute, "e2e-verified-evidence-act")
    if statute is None:
        statute = Statute(
            id="e2e-verified-evidence-act",
            short_name="E2E Evidence Act",
            long_name="Deterministic verified-source acceptance fixture",
            enacted_year=2026,
            jurisdiction="india",
            source_url="https://www.indiacode.nic.in/",
            issuing_body="Legislative Department, Ministry of Law and Justice",
            source_status="official",
            verification_status="verified_official",
            exact_source_version="E2E acceptance fixture 2026-09-02",
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        session.add(statute)
        session.flush()
    section = session.get(StatuteSection, "ram-sep02-verified-section")
    if section is None:
        section = StatuteSection(
            id="ram-sep02-verified-section",
            statute_id=statute.id,
            section_number="73",
            section_label="Deterministic acceptance evidence",
            section_text="A deterministic local fixture used only to verify the reference workflow.",
            section_text_source="indiacode",
            section_text_fetched_at=now,
            is_provisional=False,
            verification_status="verified_official",
            source_sha256="7b87df264c4fd520b9231f683c6de00553b8e48360547da816b1e09c78037ee0",
            source_publisher="Legislative Department, Ministry of Law and Justice",
            issuing_body="Legislative Department, Ministry of Law and Justice",
            source_status="official",
            legal_status="enacted",
            exact_source_version="E2E acceptance fixture 2026-09-02",
            source_locator_type="section_deep_link",
            source_policy_json={"fixture": True},
            link_health_status="available",
            link_last_checked_at=now,
            section_url="https://www.indiacode.nic.in/",
            ordinal=1,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        session.add(section)
    session.commit()
`;
  const seeded = spawnSync(
    "docker",
    ["compose", "-p", project, "-f", composeFile, "exec", "-T", "api", "python", "-c", script],
    { encoding: "utf8" },
  );
  if (seeded.status !== 0) {
    throw new Error(`Could not seed verified statute fixture.\n${seeded.stdout}\n${seeded.stderr}`);
  }
}

test.describe.serial("Ram 2026-09-02 workbook regressions", () => {
  test.setTimeout(240_000);

  test.beforeAll(async () => {
    api = await playwrightRequest.newContext();
    await ensureTenant();
    seedVerifiedLocalStatute();
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
      const current = await api.get(`${API_BASE_URL}/api/matters/${matter.id}`, {
        headers: headers(),
      });
      if (current.status() === 200) {
        const row = (await current.json()) as MatterRecord;
        if (row.status !== "disposed") {
          await api.patch(`${API_BASE_URL}/api/matters/${row.id}/lifecycle/status`, {
            headers: headers(),
            data: {
              to_status: "disposed",
              expected_from_status: row.status,
              expected_updated_at: row.updated_at,
              reason: "Close the September 02 regression fixture after validation.",
            },
          });
        }
      }
    }
    await api.dispose();
  });

  test("exact production release identifies the deployed revision", async ({ page }) => {
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
      await expectStatus(await disabled, 200, "disable assistant through owner control");
      await expect(toggle).toHaveAttribute("aria-pressed", "false");
      await expect(toggle).toBeEnabled();
    }
    await page.goto(`${BASE_URL}/app/assistant`);
    await page.getByRole("textbox", { name: "Find workspace records" }).fill("workspace");
    await page.getByRole("button", { name: "Find permitted records" }).click();
    const recoveryLink = page.getByRole("link", { name: "Admin → AI controls" });
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
    await expectStatus(enabledResponse, 200, "enable assistant through owner control");
    expect(enabledResponse.request().postDataJSON()).toMatchObject({
      workspace_assistant_enabled: true,
    });
    await expect(ownerToggle).toHaveAttribute("aria-pressed", "true");
    const persisted = await api.get(`${API_BASE_URL}/api/admin/tenant-ai-policy`, {
      headers: headers(),
    });
    await expectStatus(persisted, 200, "read persisted assistant policy");
    expect((await persisted.json()).workspace_assistant_enabled).toBe(true);
  });

  test("BUG-002: Indian Kanoon reports only machine-verifiable prerequisites", async ({
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

    const operations = await api.get(`${API_BASE_URL}/api/admin/provider-operations/readiness`, {
      headers: headers(),
    });
    await expectStatus(operations, 200, "provider operations readiness");
    const indianKanoon = ((await operations.json()).providers as Array<Record<string, unknown>>)
      .find((provider) => provider.provider === "indian-kanoon");
    expect(indianKanoon).toBeTruthy();
    expect(indianKanoon?.required_approval_keys).toEqual([]);
    expect(indianKanoon?.missing_approval_keys).toEqual([]);

    await signIn(page);
    await page.goto(`${BASE_URL}/app/research`);
    await page.getByTestId("research-source-indian-kanoon").click();
    const readinessCopy = page.getByTestId("research-indian-kanoon-readiness");
    await expect(readinessCopy).not.toContainText("Checking licensed-source readiness");
    const copy = await readinessCopy.innerText();
    expect(copy.toLowerCase()).not.toContain("approval");
    expect(copy).toMatch(/disabled|missing configuration|invalid or expired|cost profiles|active/);
  });

  test("BUG-006: Add Reference offers only Acts with verified sections and attaches one", async ({
    page,
  }) => {
    const catalogResponse = await api.get(`${API_BASE_URL}/api/statutes/`, {
      headers: headers(),
    });
    await expectStatus(catalogResponse, 200, "read verified statute catalog");
    const catalog = (await catalogResponse.json()) as {
      statutes: Array<{ id: string; short_name: string; section_count: number }>;
    };
    const selectable = catalog.statutes.filter((statute) => statute.section_count > 0);

    await signIn(page);
    await page.goto(`${BASE_URL}/app/matters/${matter.id}/statutes`);
    await page.getByTestId("matter-statute-add-trigger").click();
    const actSelect = page.getByTestId("matter-statute-act-select");
    await expect(actSelect.locator("option")).toHaveCount(selectable.length + 1);
    for (const unavailable of catalog.statutes.filter((row) => row.section_count === 0)) {
      await expect(actSelect.locator(`option[value="${unavailable.id}"]`)).toHaveCount(0);
    }
    if (selectable.length === 0) {
      await expect(page.getByTestId("matter-statute-no-selectable-acts")).toContainText(
        "No Acts currently have source-verified sections",
      );
      return;
    }
    const sectionsResponsePromise = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname ===
          `/api/statutes/${encodeURIComponent(selectable[0].id)}/sections` &&
        response.request().method() === "GET",
    );
    await actSelect.selectOption(selectable[0].id);
    const sectionsResponse = await sectionsResponsePromise;
    await expectStatus(sectionsResponse, 200, "load selected Act sections");
    const sectionSelect = page.getByTestId("matter-statute-section-select");
    await expect.poll(() => sectionSelect.locator("option").count()).toBeGreaterThan(1);
    const firstSection = await sectionSelect.locator("option").nth(1).getAttribute("value");
    expect(firstSection).toBeTruthy();
    await sectionSelect.selectOption(firstSection!);
    const attach = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === `/api/matters/${matter.id}/statute-references` &&
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
      new RegExp(`/api/matters/${matter.id}/litigation-intelligence/review(?:\\?.*)?$`),
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
                description: "Canonical source-action target fields must survive validation.",
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
                    source_reference:
                      `/api/matters/${matter.id}/attachments/attachment-ram902/download`,
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
    await page.goto(`${BASE_URL}/app/matters/${matter.id}/litigation-intelligence`);
    await expect(page.getByText("Verify the supporting attachment")).toBeVisible();
    await expect(page.getByTestId("source-action-open")).toBeVisible();
    await expect(page.getByTestId("source-action-report")).toBeVisible();
    await expect(page.getByText("Could not load litigation intelligence review")).toHaveCount(0);
  });

  test("BUG-004: strategy generation never reaches the invalid strict-schema 400", async () => {
    const generated = await api.post(
      `${API_BASE_URL}/api/matters/${matter.id}/recommendations`,
      {
        headers: headers(),
        data: { type: "litigation_strategy" },
        timeout: 120_000,
      },
    );
    const body = await generated.text();
    expect(generated.status(), body).not.toBe(400);
    expect(generated.status(), body).toBeLessThan(500);
    expect(body).not.toMatch(/additionalProperties.*required.*false/i);
    expect(body).not.toMatch(/invalid.*strict.*schema/i);
  });

  test("BUG-001: transient case-tracking failures do not require administrator replay", async ({
    page,
  }) => {
    if (IS_LOCAL) {
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
      await expectStatus(await searched, 200, "search by case number through Docker provider");
      await expect(page.getByText("Local Docker Petitioner v Local Docker Respondent")).toBeVisible();
      return;
    }

    const bookmarks = await api.get(`${API_BASE_URL}/api/case-tracking/bookmarks`, {
      headers: headers(),
    });
    await expectStatus(bookmarks, 200, "read production tracked cases");
    const rows = ((await bookmarks.json()).bookmarks as Array<{
      id: string;
      tracked_case: {
        response_class: string | null;
        freshness_status: string;
        provider_health: string;
        manual_refresh_allowed: boolean;
        manual_refresh_disabled_reason: string | null;
      };
    }>).filter((row) =>
      ["provider_error", "rate_limit", "timeout"].includes(
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
    const recoverable = rows.find((row) => row.tracked_case.manual_refresh_allowed);
    if (recoverable) {
      const refreshed = await api.post(
        `${API_BASE_URL}/api/case-tracking/bookmarks/${recoverable.id}/refresh`,
        { headers: headers(), timeout: 60_000 },
      );
      expect(refreshed.status(), await refreshed.text()).not.toBe(409);
    }
  });
});
