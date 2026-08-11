/**
 * Ram 2026-08-11 canonical local-and-production acceptance.
 *
 * Run this exact file first with playwright.app.config.ts against a fresh
 * local build/database, then with playwright.prod-ram.config.ts against the
 * deployed revision. Browser media is disabled by the production config.
 */
import {
  expect,
  request as playwrightRequest,
  test,
  type APIRequestContext,
  type Page,
} from "@playwright/test";

const envOr = (key: string, fallback: string): string =>
  (process.env[key] ?? "").trim() || fallback;

const BASE_URL = envOr(
  "PROD_BASE_URL",
  envOr("CASEOPS_WEB_BASE_URL", "http://127.0.0.1:3100"),
);
const BASE_HOST = new URL(BASE_URL).hostname;
const IS_LOCAL = BASE_HOST === "127.0.0.1" || BASE_HOST === "localhost";
const API_BASE_URL = envOr(
  "PROD_API_BASE_URL",
  IS_LOCAL
    ? `http://127.0.0.1:${envOr("CASEOPS_E2E_API_PORT", "8000")}`
    : "https://api.caseops.ai",
);
const COMPANY_SLUG = envOr("CASEOPS_RAM_PROD_SLUG", "legal");
const TESTER_EMAIL = envOr("CASEOPS_RAM_PROD_EMAIL", "hari.gupta@gmail.com");
// Local bootstrap credentials are synthetic and never used for production.
const LOCAL_TESTER_PASSWORD = "RamAug11Local!";
const RUN_ID = `${Date.now().toString(36)}-${Math.random()
  .toString(36)
  .slice(2, 8)}`.toUpperCase();

type MatterRecord = {
  id: string;
  matter_code: string;
  title: string;
  status: "intake" | "active" | "on_hold" | "disposed";
  is_active: boolean;
  lifecycle_version: number;
  updated_at: string;
  forum_level?: string;
  court_name?: string | null;
  forum_catalog_entry_id?: string | null;
  forum_state?: string | null;
};

type LoginPayload = { access_token: string };

let lastAccessToken = "";
const createdMatterIds = new Set<string>();

function requiredPassword(): string {
  const password =
    process.env.CASEOPS_RAM_PROD_PASSWORD?.trim() ||
    process.env.CASEOPS_RAM_LOCAL_PASSWORD?.trim() ||
    (IS_LOCAL ? LOCAL_TESTER_PASSWORD : "");
  if (!password) {
    throw new Error(
      "CASEOPS_RAM_PROD_PASSWORD or CASEOPS_RAM_LOCAL_PASSWORD is required for the August 11 regression.",
    );
  }
  return password;
}

function uniqueCode(prefix: string): string {
  return `${prefix}-${RUN_ID}`.replace(/[^A-Z0-9-]/g, "").slice(0, 78);
}

function isoDate(offsetDays: number): string {
  const value = new Date();
  value.setUTCDate(value.getUTCDate() + offsetDays);
  return value.toISOString().slice(0, 10);
}

function authHeaders(token: string): Record<string, string> {
  return { Accept: "application/json", Authorization: `Bearer ${token}` };
}

async function expectStatus(
  response: { status(): number; text(): Promise<string> },
  expected: number,
  label: string,
): Promise<void> {
  const detail =
    response.status() === expected ? "" : ` ${await response.text()}`;
  expect(
    response.status(),
    `${label}: expected HTTP ${expected}, received ${response.status()}.${detail}`,
  ).toBe(expected);
}

async function ensureLocalTester(request: APIRequestContext): Promise<void> {
  if (!IS_LOCAL) return;
  const login = await request.post(`${API_BASE_URL}/api/auth/login`, {
    data: {
      company_slug: COMPANY_SLUG,
      email: TESTER_EMAIL,
      password: requiredPassword(),
    },
  });
  if (login.status() === 200) return;
  await expectStatus(login, 401, "probe fresh local tester login");
  const bootstrap = await request.post(
    `${API_BASE_URL}/api/bootstrap/company`,
    {
      data: {
        company_name: "Legal Regression LLP",
        company_slug: COMPANY_SLUG,
        company_type: "law_firm",
        owner_full_name: "Hari Gupta",
        owner_email: TESTER_EMAIL,
        owner_password: requiredPassword(),
      },
    },
  );
  await expectStatus(
    bootstrap,
    200,
    "bootstrap local legal tester and data owner",
  );
}

async function signIn(page: Page): Promise<string> {
  await page.goto(`${BASE_URL}/sign-in`);
  await page.locator("#company-slug").fill(COMPANY_SLUG);
  await page.locator("#email").fill(TESTER_EMAIL);
  await page.locator("#password").fill(requiredPassword());
  const [login] = await Promise.all([
    page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === "/api/auth/login" &&
        response.request().method() === "POST",
      { timeout: 30_000 },
    ),
    page.locator('button[type="submit"]').click(),
  ]);
  await expectStatus(login, 200, "explicit tester sign-in");
  const payload = (await login.json()) as LoginPayload;
  expect(payload.access_token).toBeTruthy();
  lastAccessToken = payload.access_token;
  await page.waitForURL(/\/app(?:[/?]|$)/);
  return payload.access_token;
}

async function getMatter(
  request: APIRequestContext,
  token: string,
  matterId: string,
): Promise<MatterRecord> {
  const response = await request.get(
    `${API_BASE_URL}/api/matters/${matterId}`,
    {
      headers: authHeaders(token),
    },
  );
  await expectStatus(response, 200, `read matter ${matterId}`);
  return (await response.json()) as MatterRecord;
}

async function transitionLifecycle(
  request: APIRequestContext,
  token: string,
  matter: MatterRecord,
  toStatus: "intake" | "disposed",
  reason: string,
): Promise<MatterRecord> {
  const response = await request.patch(
    `${API_BASE_URL}/api/matters/${matter.id}/lifecycle/status`,
    {
      headers: authHeaders(token),
      data: {
        to_status: toStatus,
        expected_from_status: matter.status,
        expected_updated_at: matter.updated_at,
        reason,
      },
    },
  );
  await expectStatus(
    response,
    200,
    `${matter.matter_code} lifecycle ${matter.status} -> ${toStatus}`,
  );
  return (await response.json()) as MatterRecord;
}

async function createMatter(
  request: APIRequestContext,
  token: string,
  code: string,
): Promise<MatterRecord> {
  const response = await request.post(`${API_BASE_URL}/api/matters/`, {
    headers: authHeaders(token),
    data: {
      title: `August 11 lifecycle ${RUN_ID}`,
      matter_code: code,
      status: "active",
      practice_area: "Commercial Litigation",
      forum_level: "high_court",
      forum_catalog_entry_id: "hc:delhi",
    },
  });
  await expectStatus(response, 200, "create lifecycle regression matter");
  const matter = (await response.json()) as MatterRecord;
  createdMatterIds.add(matter.id);
  return matter;
}

async function assertElementWithinViewport(
  page: Page,
  label: string,
  locator: ReturnType<Page["locator"]>,
): Promise<void> {
  await expect(locator, `${label} must be user-visible`).toBeVisible();
  const box = await locator.boundingBox();
  const viewport = page.viewportSize();
  expect(box, `${label} must have a rendered box`).not.toBeNull();
  expect(viewport, "Playwright viewport must be known").not.toBeNull();
  expect(
    box!.x,
    `${label} must not be clipped on the left`,
  ).toBeGreaterThanOrEqual(0);
  expect(
    box!.x + box!.width,
    `${label} must not be clipped on the right`,
  ).toBeLessThanOrEqual(viewport!.width + 0.5);
}

test.describe.serial("Ram 2026-08-11 local and deployed regressions", () => {
  test.setTimeout(300_000);

  test.beforeAll(async () => {
    const request = await playwrightRequest.newContext();
    try {
      await ensureLocalTester(request);
    } finally {
      await request.dispose();
    }
  });

  test.afterAll(async () => {
    if (!lastAccessToken || !createdMatterIds.size) return;
    const request = await playwrightRequest.newContext();
    const cleanupFailures: string[] = [];
    try {
      for (const matterId of createdMatterIds) {
        try {
          const matter = await getMatter(request, lastAccessToken, matterId);
          if (matter.status !== "disposed") {
            await transitionLifecycle(
              request,
              lastAccessToken,
              matter,
              "disposed",
              "August 11 regression cleanup returned this test record to terminal state.",
            );
          }
        } catch (error) {
          cleanupFailures.push(
            `${matterId}: ${error instanceof Error ? error.message : String(error)}`,
          );
        }
      }
    } finally {
      await request.dispose();
    }
    expect(
      cleanupFailures,
      "regression cleanup must not leave operational Matter records",
    ).toEqual([]);
  });

  test("BUG-001: every Matter filter and grouped action remains visible at desktop, tablet, and mobile widths", async ({
    page,
  }) => {
    await signIn(page);

    for (const viewport of [
      { width: 1280, height: 900 },
      { width: 1024, height: 850 },
      { width: 390, height: 844 },
    ]) {
      await page.setViewportSize(viewport);
      await page.goto(`${BASE_URL}/app/matters`);
      await expect(
        page.getByRole("heading", { name: "Matter portfolio" }),
      ).toBeVisible();

      const search = page.locator("#matter-filter-q");
      await search.fill(`bounds-${viewport.width}`);
      await page.getByRole("button", { name: /^Apply$/ }).click();
      const controls = [
        ["Search", search],
        ["Status", page.getByLabel("Matter status filter")],
        ["Forum", page.getByLabel("Forum filter")],
        ["Tag", page.getByLabel("Tag filter")],
        ["Min claim", page.getByLabel("Min claim")],
        ["Max claim", page.getByLabel("Max claim")],
        ["Apply", page.getByRole("button", { name: /^Apply$/ })],
        ["Reset", page.getByRole("button", { name: /^Reset$/ })],
      ] as const;
      for (const [label, locator] of controls) {
        await assertElementWithinViewport(page, label, locator);
      }

      const overflow = await page
        .getByTestId("matter-filter-grid")
        .evaluate((element) => ({
          clientWidth: element.clientWidth,
          scrollWidth: element.scrollWidth,
        }));
      expect(
        overflow.scrollWidth,
        `Matter filter grid must not overflow at ${viewport.width}px`,
      ).toBeLessThanOrEqual(overflow.clientWidth + 1);
    }
  });

  test("BUG-002: all seven Grounded Legal Research modes complete before the UI deadline", async ({
    page,
  }) => {
    await signIn(page);
    let researchStatsRequests = 0;
    await page.route("**/api/authorities/stats", async (route) => {
      if (new URL(page.url()).pathname === "/app/research") {
        researchStatsRequests += 1;
      }
      await route.continue();
    });
    await page.goto(`${BASE_URL}/app/research`);
    await expect(
      page.getByRole("heading", { name: "Grounded legal research" }),
    ).toBeVisible();

    const cases = [
      ["keyword", "bail application"],
      [
        "contextual",
        "Cheque bounced due to insufficient funds and notice was sent after 35 days",
      ],
      ["exact-citation", "2026:MHC:483"],
      ["party", "State"],
      ["court", "Delhi High Court"],
      ["judge", "Chandrachud"],
      ["act-section", "Section 138 Negotiable Instruments Act"],
    ] as const;

    for (const [mode, query] of cases) {
      await page.getByTestId(`research-mode-${mode}`).click();
      await page.getByTestId("research-query-input").fill(query);
      const responsePromise = page.waitForResponse(
        (response) =>
          new URL(response.url()).pathname === "/api/authorities/search" &&
          response.request().method() === "POST",
        { timeout: 20_000 },
      );
      const startedAt = Date.now();
      await page.getByTestId("research-query-submit").click();
      const response = await responsePromise;
      const elapsedMs = Date.now() - startedAt;
      await expectStatus(response, 200, `${mode} research response`);
      const responseBody = (await response.json()) as {
        outcome: string;
        diagnostics: { total_latency_ms?: number };
        corpus_coverage: { document_count: number; index_state: string };
      };
      expect(elapsedMs, `${mode} must finish before the UI abort`).toBeLessThan(
        20_000,
      );
      expect(
        responseBody.diagnostics.total_latency_ms,
        `${mode} must report its server-side latency budget`,
      ).toBeLessThan(20_000);
      if (!IS_LOCAL) {
        expect(
          responseBody.corpus_coverage.document_count,
          `${mode} production replay must exercise the real corpus`,
        ).toBeGreaterThan(100_000);
        expect(responseBody.corpus_coverage.index_state).toBe("current");
        expect(responseBody.outcome).not.toBe("corpus_unavailable");
        expect(responseBody.outcome).not.toBe("provider_unavailable");
      }
      console.log(
        `[BUG-002] ${mode}: browser=${elapsedMs}ms server=${responseBody.diagnostics.total_latency_ms}ms outcome=${responseBody.outcome}`,
      );
      await expect(page.getByTestId("research-query-submit")).toBeEnabled();
      await expect(page.getByTestId("research-corpus-coverage")).toBeVisible();
      await expect(
        page.getByText("Request timed out", { exact: true }),
      ).toHaveCount(0);
    }
    expect(
      researchStatsRequests,
      "Research must use coverage from search instead of racing a duplicate stats request",
    ).toBe(0);
  });

  test("ENH-001: manual create/edit and bulk import use the same exact forum catalog", async ({
    page,
  }) => {
    const token = await signIn(page);
    await page.goto(`${BASE_URL}/app/matters`);
    await page.getByTestId("new-matter-trigger").first().click();
    const dialog = page.getByRole("dialog", { name: /New matter/i });
    await expect(dialog.getByTestId("new-matter-forum-state")).toHaveValue(
      "Delhi",
      {
        timeout: 90_000,
      },
    );

    const categoryLabels = await dialog
      .getByTestId("new-matter-forum-category")
      .locator("option")
      .allTextContents();
    expect(categoryLabels).toEqual(
      expect.arrayContaining([
        "Supreme Court",
        "High Court",
        "District Court",
        "NCDRC",
        "State Commission",
        "District Commission",
        "DRAT / DRT",
        "Recovery Forums",
        "NCLAT / NCLT",
        "TDSAT",
        "Appellate Tribunal",
      ]),
    );

    await dialog.getByLabel("Title").fill(`Manual DRT selection ${RUN_ID}`);
    await dialog.getByLabel("Matter code").fill(uniqueCode("RAM811-MANUAL"));
    await dialog.getByLabel("Practice area").fill("Banking and Finance");
    await dialog
      .getByTestId("new-matter-forum-category")
      .selectOption("drt_drat");
    await dialog
      .getByTestId("new-matter-forum-specialist-forum")
      .selectOption("drt:delhi:drt-2");
    await expect(dialog).toContainText(/DRAT \/ DRT > Delhi > DRT-2/);

    const createPromise = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === "/api/matters/" &&
        response.request().method() === "POST",
    );
    await dialog.getByRole("button", { name: /Create matter/i }).click();
    const createResponse = await createPromise;
    await expectStatus(
      createResponse,
      200,
      "create catalogued DRT-2 matter through UI",
    );
    let manualMatter = (await createResponse.json()) as MatterRecord;
    createdMatterIds.add(manualMatter.id);
    expect(manualMatter).toMatchObject({
      forum_level: "tribunal",
      court_name: "DRT-2",
      forum_catalog_entry_id: "drt:delhi:drt-2",
      forum_state: "Delhi",
    });

    await page.goto(`${BASE_URL}/app/matters/${manualMatter.id}`);
    await expect(page.getByTestId("matter-forum-card")).toContainText("DRT-2");
    await expect(page.getByTestId("matter-forum-card")).toContainText(
      "Catalogued",
    );
    await page.getByTestId("matter-forum-edit").click();
    await page
      .getByTestId("matter-edit-forum-category")
      .selectOption("company_law_tribunal");
    await page
      .getByTestId("matter-edit-forum-specialist-forum")
      .selectOption("company-law:nclt");
    const editPromise = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname ===
          `/api/matters/${manualMatter.id}` &&
        response.request().method() === "PATCH",
    );
    await page.getByTestId("matter-forum-save").click();
    const editResponse = await editPromise;
    await expectStatus(editResponse, 200, "edit exact catalog forum to NCLT");
    manualMatter = (await editResponse.json()) as MatterRecord;
    expect(manualMatter).toMatchObject({
      forum_level: "tribunal",
      court_name: "NCLT",
      forum_catalog_entry_id: "company-law:nclt",
    });

    const bulkCode = uniqueCode("RAM811-BULK");
    const invalidCode = uniqueCode("RAM811-INVALID");
    const csv = Buffer.from(
      [
        "Matter Title,Matter Code,Practice Area,Forum,Court",
        `Bulk DRT selection ${RUN_ID},${bulkCode},Banking and Finance,DRAT / DRT,DRT-2`,
        `Invented tribunal ${RUN_ID},${invalidCode},Banking and Finance,DRAT / DRT,DRT-99`,
      ].join("\n"),
      "utf8",
    );
    const preview = await page.request.post(
      `${API_BASE_URL}/api/matters/imports/preview`,
      {
        headers: authHeaders(token),
        multipart: {
          file: {
            name: "ram-2026-08-11-forums.csv",
            mimeType: "text/csv",
            buffer: csv,
          },
        },
      },
    );
    await expectStatus(preview, 200, "preview catalog-backed bulk import");
    const job = (await preview.json()) as {
      id: string;
      valid_rows: number;
      invalid_rows: number;
      rows: Array<{
        normalized: Record<string, unknown>;
        errors: string[];
      }>;
    };
    expect(job.valid_rows).toBe(1);
    expect(job.invalid_rows).toBe(1);
    expect(job.rows[0].normalized).toMatchObject({
      forum_level: "tribunal",
      court_name: "DRT-2",
      forum_catalog_entry_id: "drt:delhi:drt-2",
      forum_state: "Delhi",
    });
    expect(job.rows[1].errors).toContain(
      "Court is not an active DRAT / DRT catalog selection.",
    );

    const commit = await page.request.post(
      `${API_BASE_URL}/api/matters/imports/${job.id}/commit`,
      { headers: authHeaders(token) },
    );
    await expectStatus(
      commit,
      200,
      "commit the one valid catalog-backed bulk row",
    );
    const committed = (await commit.json()) as { created_matter_ids: string[] };
    expect(committed.created_matter_ids).toHaveLength(1);
    const bulkMatterId = committed.created_matter_ids[0];
    createdMatterIds.add(bulkMatterId);
    const bulkMatter = await getMatter(page.request, token, bulkMatterId);
    expect(bulkMatter).toMatchObject({
      forum_level: "tribunal",
      court_name: "DRT-2",
      forum_catalog_entry_id: "drt:delhi:drt-2",
      forum_state: "Delhi",
    });
  });

  test("lifecycle: disposal is atomic, stale writes and child resurrection fail closed, and controlled reopen persists only to Intake", async ({
    page,
  }) => {
    const token = await signIn(page);
    let matter = await createMatter(
      page.request,
      token,
      uniqueCode("RAM811-LIFECYCLE"),
    );
    const today = isoDate(0);
    const future = isoDate(2);

    const taskResponse = await page.request.post(
      `${API_BASE_URL}/api/matters/${matter.id}/tasks`,
      {
        headers: authHeaders(token),
        data: { title: `August 11 task ${RUN_ID}`, due_on: today },
      },
    );
    await expectStatus(taskResponse, 200, "create pre-disposal task");
    const task = (await taskResponse.json()) as { id: string };
    const deadlineResponse = await page.request.post(
      `${API_BASE_URL}/api/matters/${matter.id}/deadlines`,
      {
        headers: authHeaders(token),
        data: {
          title: `August 11 deadline ${RUN_ID}`,
          kind: "filing",
          due_on: future,
        },
      },
    );
    await expectStatus(deadlineResponse, 200, "create pre-disposal deadline");
    const deadline = (await deadlineResponse.json()) as { id: string };
    const hearingResponse = await page.request.post(
      `${API_BASE_URL}/api/matters/${matter.id}/hearings`,
      {
        headers: authHeaders(token),
        data: {
          hearing_on: future,
          forum_name: "Delhi High Court",
          purpose: `August 11 hearing ${RUN_ID}`,
        },
      },
    );
    await expectStatus(hearingResponse, 200, "create pre-disposal hearing");
    const hearing = (await hearingResponse.json()) as { id: string };

    await page.goto(`${BASE_URL}/app/matters/${matter.id}`);
    await page.getByTestId("matter-edit-open").click();
    await page.getByTestId("matter-edit-title").fill(`Stale title ${RUN_ID}`);
    const staleSnapshot = await getMatter(page.request, token, matter.id);
    matter = await transitionLifecycle(
      page.request,
      token,
      staleSnapshot,
      "disposed",
      "Final order closed the August 11 lifecycle regression matter.",
    );
    expect(matter.status).toBe("disposed");
    expect(matter.is_active).toBe(false);
    expect(matter.lifecycle_version).toBe(staleSnapshot.lifecycle_version + 1);

    const staleSavePromise = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === `/api/matters/${matter.id}` &&
        response.request().method() === "PATCH",
    );
    await page.getByTestId("matter-edit-save").click();
    const staleSave = await staleSavePromise;
    await expectStatus(
      staleSave,
      409,
      "reject stale editor write after disposal",
    );
    await expect(page.getByTestId("matter-edit-stale-write")).toContainText(
      /changed in another session/i,
    );

    const genericReopen = await page.request.patch(
      `${API_BASE_URL}/api/matters/${matter.id}`,
      {
        headers: authHeaders(token),
        data: { status: "active", expected_updated_at: matter.updated_at },
      },
    );
    await expectStatus(
      genericReopen,
      409,
      "reject generic disposed-to-active patch",
    );
    expect((await getMatter(page.request, token, matter.id)).status).toBe(
      "disposed",
    );

    for (const [label, path, data] of [
      ["task", "tasks", { title: `Rejected task ${RUN_ID}`, due_on: today }],
      [
        "deadline",
        "deadlines",
        {
          title: `Rejected deadline ${RUN_ID}`,
          kind: "filing",
          due_on: future,
        },
      ],
      [
        "hearing",
        "hearings",
        {
          hearing_on: future,
          forum_name: "Delhi High Court",
          purpose: `Rejected hearing ${RUN_ID}`,
        },
      ],
    ] as const) {
      const response = await page.request.post(
        `${API_BASE_URL}/api/matters/${matter.id}/${path}`,
        { headers: authHeaders(token), data },
      );
      await expectStatus(response, 409, `reject ${label} on disposed matter`);
    }

    const todayResponse = await page.request.get(
      `${API_BASE_URL}/api/me/today`,
      {
        headers: authHeaders(token),
      },
    );
    await expectStatus(todayResponse, 200, "read Today after disposal");
    expect(JSON.stringify(await todayResponse.json())).not.toContain(matter.id);
    const calendarResponse = await page.request.get(
      `${API_BASE_URL}/api/calendar/events`,
      { headers: authHeaders(token), params: { from: today, to: future } },
    );
    await expectStatus(calendarResponse, 200, "read calendar after disposal");
    expect(JSON.stringify(await calendarResponse.json())).not.toContain(
      matter.id,
    );

    await page.reload();
    await expect(page.getByTestId("matter-edit-open")).toHaveCount(0);
    await page.getByTestId("matter-reopen-trigger").click();
    await page
      .getByTestId("matter-lifecycle-reason")
      .fill("Fresh instructions require a controlled reopen into Intake.");
    const reopenPromise = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname ===
          `/api/matters/${matter.id}/lifecycle/status` &&
        response.request().method() === "PATCH",
    );
    await page.getByTestId("matter-lifecycle-confirm").click();
    const reopenResponse = await reopenPromise;
    await expectStatus(
      reopenResponse,
      200,
      "controlled disposed-to-intake reopen",
    );
    const reopened = (await reopenResponse.json()) as MatterRecord;
    expect(reopened.status).toBe("intake");
    expect(reopened.is_active).toBe(true);
    expect(reopened.lifecycle_version).toBe(matter.lifecycle_version + 1);
    matter = reopened;

    const tasksAfter = await page.request.get(
      `${API_BASE_URL}/api/matters/${matter.id}/tasks`,
      { headers: authHeaders(token) },
    );
    await expectStatus(tasksAfter, 200, "read tasks after controlled reopen");
    expect(
      (
        (await tasksAfter.json()) as {
          tasks: Array<{ id: string; status: string }>;
        }
      ).tasks.find((row) => row.id === task.id)?.status,
    ).toBe("cancelled");
    const deadlinesAfter = await page.request.get(
      `${API_BASE_URL}/api/matters/${matter.id}/deadlines`,
      { headers: authHeaders(token) },
    );
    await expectStatus(
      deadlinesAfter,
      200,
      "read deadlines after controlled reopen",
    );
    expect(
      (
        (await deadlinesAfter.json()) as {
          deadlines: Array<{ id: string; status: string }>;
        }
      ).deadlines.find((row) => row.id === deadline.id)?.status,
    ).toBe("cancelled");
    const workspaceAfter = await page.request.get(
      `${API_BASE_URL}/api/matters/${matter.id}/workspace`,
      { headers: authHeaders(token) },
    );
    await expectStatus(
      workspaceAfter,
      200,
      "read hearing history after reopen",
    );
    expect(
      (
        (await workspaceAfter.json()) as {
          hearings: Array<{ id: string; status: string }>;
        }
      ).hearings.find((row) => row.id === hearing.id)?.status,
    ).toBe("cancelled");

    for (const [label, path, data] of [
      ["task", `tasks/${task.id}`, { status: "todo" }],
      ["deadline", `deadlines/${deadline.id}`, { status: "open" }],
      ["hearing", `hearings/${hearing.id}`, { status: "scheduled" }],
    ] as const) {
      const response = await page.request.patch(
        `${API_BASE_URL}/api/matters/${matter.id}/${path}`,
        { headers: authHeaders(token), data },
      );
      await expectStatus(
        response,
        409,
        `reject resurrection of lifecycle-cancelled ${label}`,
      );
    }

    await page.reload();
    const persistedReopen = await getMatter(page.request, token, matter.id);
    expect(persistedReopen.status).toBe("intake");
    expect(persistedReopen.lifecycle_version).toBe(matter.lifecycle_version);
    const auditResponse = await page.request.get(
      `${API_BASE_URL}/api/matters/${matter.id}/audit-events`,
      { headers: authHeaders(token), params: { limit: 200 } },
    );
    await expectStatus(auditResponse, 200, "read lifecycle audit history");
    const actions = (
      (await auditResponse.json()) as { events: Array<{ action: string }> }
    ).events.map((event) => event.action);
    expect(actions).toEqual(
      expect.arrayContaining([
        "matter.lifecycle.disposed",
        "matter.lifecycle.reopened",
      ]),
    );

    matter = await transitionLifecycle(
      page.request,
      token,
      persistedReopen,
      "disposed",
      "August 11 lifecycle regression complete; return test Matter to terminal state.",
    );
    const finalState = await getMatter(page.request, token, matter.id);
    expect(finalState.status).toBe("disposed");
    expect(finalState.is_active).toBe(false);
    expect(finalState.lifecycle_version).toBe(matter.lifecycle_version);
  });
});
