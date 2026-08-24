/**
 * Ram 2026-07-15 deployed-production regression.
 *
 * This is intentionally a live, no-mock suite. It creates uniquely named
 * records in the tester-authorized `legal` workspace and leaves matters in
 * the terminal Disposed state after the assertions. Notice records are
 * retained as Closed because the product has no destructive notice-delete
 * workflow and their audit history is part of what this test validates.
 *
 * Authentication is deliberately independent of the QA storage state in
 * playwright.prod-ram.config.ts. The suite opens a fresh context and signs in
 * as the July 15 tester. The password is required from the environment and is
 * never committed or included in an assertion/error message.
 *
 * Do not run this before the candidate commit is deployed. Once deployed:
 *
 *   npx playwright test --config playwright.prod-ram.config.ts \
 *     tests/e2e/ram-2026-07-15-prod.spec.ts --project tester-prod-chromium
 */
import {
  expect,
  test,
  type APIResponse,
  type BrowserContext,
  type Page,
} from "@playwright/test";
import { readFile } from "node:fs/promises";

const envOr = (key: string, fallback: string): string => {
  const value = (process.env[key] ?? "").trim();
  return value || fallback;
};

const PROD_BASE_URL = envOr("PROD_BASE_URL", "https://caseops.ai");
const PROD_API_BASE_URL = envOr(
  "PROD_API_BASE_URL",
  "https://api.caseops.ai",
);
const COMPANY_SLUG = envOr("CASEOPS_RAM_PROD_SLUG", "legal");
const TESTER_EMAIL = envOr(
  "CASEOPS_RAM_PROD_EMAIL",
  "hari.gupta@gmail.com",
);
const RUN_ID = `${Date.now().toString(36)}-${Math.random()
  .toString(36)
  .slice(2, 8)}`.toUpperCase();

type MatterRecord = {
  id: string;
  matter_code: string;
  title: string;
  status: "intake" | "active" | "on_hold" | "disposed";
  updated_at: string;
};

type AuthContext = {
  company: { slug: string };
  user: { email: string; full_name: string };
  membership: { id: string };
  capabilities: string[];
};

type NoticeRecord = {
  id: string;
  read_only?: boolean;
  direction: "received" | "sent";
  subject: string;
  status: string;
  updated_at: string;
  owner_membership_id: string | null;
  matter_links: Array<{
    matter_id: string;
    matter_code: string;
    matter_title: string;
  }>;
};

let context: BrowserContext;
let page: Page;
let tester: AuthContext;
let lifecycleMatter: MatterRecord;
let linkedMatter: MatterRecord;
let receivedNotice: NoticeRecord;
let sentNotice: NoticeRecord;

function requiredPassword(): string {
  const value = process.env.CASEOPS_RAM_PROD_PASSWORD?.trim() ?? "";
  if (!value) {
    throw new Error(
      "CASEOPS_RAM_PROD_PASSWORD is required for the July 15 production regression.",
    );
  }
  return value;
}

function uniqueCode(prefix: string): string {
  return `${prefix}-${RUN_ID}`.replace(/[^A-Z0-9-]/g, "").slice(0, 78);
}

function isoDate(offsetDays: number): string {
  const date = new Date();
  date.setUTCDate(date.getUTCDate() + offsetDays);
  return date.toISOString().slice(0, 10);
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

async function expectStatus(
  response: APIResponse,
  expected: number,
  label: string,
): Promise<void> {
  const body = response.status() === expected ? "" : ` ${await response.text()}`;
  expect(
    response.status(),
    `${label}: expected HTTP ${expected}, received ${response.status()}.${body}`,
  ).toBe(expected);
}

async function authHeaders(): Promise<Record<string, string>> {
  const cookies = await context.cookies([PROD_BASE_URL, PROD_API_BASE_URL]);
  const cookieHeader = cookies
    .map((cookie) => `${cookie.name}=${cookie.value}`)
    .join("; ");
  const csrf = cookies.find((cookie) => cookie.name === "caseops_csrf")?.value;

  expect(cookieHeader, "authenticated cookie jar must not be empty").not.toBe("");
  expect(csrf, "caseops_csrf cookie must exist after explicit sign-in").toBeTruthy();

  return {
    Accept: "application/json",
    Cookie: cookieHeader,
    "Content-Type": "application/json",
    "X-CSRF-Token": csrf!,
  };
}

async function signInAsTester(): Promise<AuthContext> {
  await context.clearCookies();
  await page.goto(`${PROD_BASE_URL}/sign-in`);
  await expect(
    page.getByRole("heading", { name: /Sign in to your workspace/i }),
  ).toBeVisible();
  await page.locator("#company-slug").fill(COMPANY_SLUG);
  await page.locator("#email").fill(TESTER_EMAIL);
  await page.locator("#password").fill(requiredPassword());

  const loginResponsePromise = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/api/auth/login" &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  const loginResponse = await loginResponsePromise;
  expect(
    loginResponse.status(),
    `explicit tester sign-in returned HTTP ${loginResponse.status()}`,
  ).toBe(200);
  await page.waitForURL(new RegExp(`${escapeRegExp(PROD_BASE_URL)}/app(?:[/?]|$)`));

  const meResponse = await context.request.get(
    `${PROD_API_BASE_URL}/api/auth/me`,
    { headers: await authHeaders() },
  );
  await expectStatus(meResponse, 200, "read explicit tester auth context");
  const auth = (await meResponse.json()) as AuthContext;
  expect(auth.company.slug).toBe(COMPANY_SLUG);
  expect(auth.user.email.toLowerCase()).toBe(TESTER_EMAIL.toLowerCase());
  expect(auth.membership.id).toBeTruthy();
  expect(auth.capabilities).toEqual(
    expect.arrayContaining([
      "matters:create",
      "matters:edit",
      "matters:write",
      "matters:archive",
      "conflicts:run",
      "conflicts:resolve",
      "documents:upload",
      "documents:manage",
      "company:manage_users",
      "calendar:view",
    ]),
  );
  return auth;
}

async function getMatter(matterId: string): Promise<MatterRecord> {
  const response = await context.request.get(
    `${PROD_API_BASE_URL}/api/matters/${matterId}`,
    { headers: await authHeaders() },
  );
  await expectStatus(response, 200, `read matter ${matterId}`);
  return (await response.json()) as MatterRecord;
}

async function runClearedConflictCheck(
  matterId: string,
  opposingPartyName: string,
  label: string,
): Promise<{ id: string; status: string }> {
  const response = await context.request.post(
    `${PROD_API_BASE_URL}/api/matters/${matterId}/conflict-checks`,
    {
      headers: await authHeaders(),
      data: {
        opposing_party_name: opposingPartyName,
        related_party_names: [],
      },
    },
  );
  await expectStatus(response, 200, label);
  let check = (await response.json()) as { id: string; status: string };

  if (check.status === "pending") {
    const resolution = await context.request.patch(
      `${PROD_API_BASE_URL}/api/conflict-checks/${check.id}`,
      {
        headers: await authHeaders(),
        data: {
          status: "cleared",
          resolution_note:
            "Owner reviewed the production regression overlap and confirmed no real conflict.",
        },
      },
    );
    await expectStatus(resolution, 200, `${label} resolution`);
    check = (await resolution.json()) as { id: string; status: string };
  }

  expect(check.status).toBe("cleared");
  return check;
}

async function createMatterWithoutStatus(code: string): Promise<MatterRecord> {
  const response = await context.request.post(
    `${PROD_API_BASE_URL}/api/matters/`,
    {
      headers: await authHeaders(),
      data: {
        title: `July 15 omitted-status regression ${code}`,
        matter_code: code,
        client_name: `Regression Client ${RUN_ID}`,
        opposing_party: `Regression Opponent B ${RUN_ID}`,
        practice_area: "Commercial Litigation",
        forum_level: "high_court",
        court_name: "Delhi High Court",
      },
    },
  );
  let created: MatterRecord | undefined;
  if (response.status() >= 200 && response.status() < 300) {
    created = (await response.json()) as MatterRecord;
    // Track the record before any assertion so afterAll can dispose it even
    // when a deployed response contract changes unexpectedly.
    linkedMatter = created;
  }
  await expectStatus(response, 200, "create matter with omitted status");
  expect(created, "successful Matter creation must return its record").toBeDefined();
  return created!;
}

async function cleanupDiscoveredRunRecords(): Promise<void> {
  // This fallback is intentionally independent of the globals assigned by the
  // assertions. If a response creates a record but violates an expected
  // status/body contract, the unique RUN_ID still lets cleanup find it.
  const noticeResponse = await context.request.get(
    `${PROD_API_BASE_URL}/api/notices/`,
    {
      headers: await authHeaders(),
      params: { query: RUN_ID, limit: 100 },
    },
  );
  await expectStatus(noticeResponse, 200, "discover production regression notices");
  const noticePayload = (await noticeResponse.json()) as {
    notices: NoticeRecord[];
  };
  for (const notice of noticePayload.notices) {
    if (!notice.read_only && notice.status !== "Closed") {
      await closeNotice(notice);
    }
  }

  const matterResponse = await context.request.get(
    `${PROD_API_BASE_URL}/api/matters/`,
    {
      headers: await authHeaders(),
      params: { q: RUN_ID, limit: 100 },
    },
  );
  await expectStatus(matterResponse, 200, "discover production regression matters");
  const matterPayload = (await matterResponse.json()) as {
    matters: MatterRecord[];
  };
  for (const matter of matterPayload.matters) {
    await disposeIfOperational(matter);
  }
}

async function transitionLifecycle(
  matter: MatterRecord,
  toStatus: "intake" | "disposed",
  reason: string,
): Promise<MatterRecord> {
  const response = await context.request.patch(
    `${PROD_API_BASE_URL}/api/matters/${matter.id}/lifecycle/status`,
    {
      headers: await authHeaders(),
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

async function closeNotice(notice: NoticeRecord): Promise<NoticeRecord> {
  const currentResponse = await context.request.get(
    `${PROD_API_BASE_URL}/api/notices/${notice.id}`,
    { headers: await authHeaders() },
  );
  await expectStatus(
    currentResponse,
    200,
    `read notice ${notice.id} before cleanup`,
  );
  const current = (await currentResponse.json()) as NoticeRecord;
  if (current.status === "Closed") return current;
  const response = await context.request.patch(
    `${PROD_API_BASE_URL}/api/notices/${notice.id}`,
    {
      headers: await authHeaders(),
      data: {
        status: "Closed",
        expected_updated_at: current.updated_at,
      },
    },
  );
  await expectStatus(response, 200, `close notice ${notice.id}`);
  const closed = (await response.json()) as NoticeRecord;
  expect(closed.status).toBe("Closed");
  return closed;
}

async function disposeIfOperational(matter: MatterRecord | undefined): Promise<void> {
  if (!matter) return;
  const current = await getMatter(matter.id);
  if (current.status === "disposed") return;
  await transitionLifecycle(
    current,
    "disposed",
    "Production regression cleanup returned this test matter to terminal state.",
  );
}

test.describe.serial("Ram 2026-07-15 deployed workbook fixes", () => {
  test.setTimeout(180_000);

  test.beforeAll(async ({ browser }) => {
    // A blank context makes it impossible for the QA Bot storage state to
    // satisfy this suite accidentally. The explicit Hari login above is the
    // only authentication path used by these tests.
    context = await browser.newContext({
      baseURL: PROD_BASE_URL,
      storageState: { cookies: [], origins: [] },
    });
    page = await context.newPage();
    tester = await signInAsTester();
  });

  test.afterAll(async () => {
    if (!context) return;
    const cleanupFailures: string[] = [];
    for (const [label, cleanup] of [
      [
        "received notice",
        async () => {
          if (receivedNotice) receivedNotice = await closeNotice(receivedNotice);
        },
      ],
      [
        "sent notice",
        async () => {
          if (sentNotice) sentNotice = await closeNotice(sentNotice);
        },
      ],
      ["lifecycle matter", async () => disposeIfOperational(lifecycleMatter)],
      ["linked matter", async () => disposeIfOperational(linkedMatter)],
    ] as const) {
      try {
        await cleanup();
      } catch (error) {
        cleanupFailures.push(
          `${label}: ${error instanceof Error ? error.message : String(error)}`,
        );
      }
    }
    try {
      await cleanupDiscoveredRunRecords();
    } catch (error) {
      cleanupFailures.push(
        `RUN_ID discovery fallback: ${
          error instanceof Error ? error.message : String(error)
        }`,
      );
    }
    await context.close();
    expect(
      cleanupFailures,
      "production regression cleanup must complete without leaving operational test records",
    ).toEqual([]);
  });

  test("BUG-002: New Matter defaults to Active and omitted API status also creates Active", async () => {
    await page.goto(`${PROD_BASE_URL}/app/matters`);
    await page.locator("main").getByTestId("new-matter-trigger").first().click();

    const dialog = page.getByRole("dialog", { name: /New matter/i });
    await expect(dialog).toBeVisible();
    // Creation is intentionally blocked until the structured forum catalog
    // resolves. Waiting for the selected state makes this a real readiness
    // assertion instead of a catalog-speed race that can pass or fail based on
    // production latency. Allow one bounded multi-container autoscale cold
    // start (ClamAV readiness followed by API startup).
    await expect(dialog.getByTestId("new-matter-forum-state")).toHaveValue(
      "Delhi",
      { timeout: 90_000 },
    );
    const statusSelect = dialog.getByRole("combobox", { name: "Status" });
    await expect(statusSelect).toHaveText(/^Active$/);
    await statusSelect.click();
    await expect(page.getByRole("option", { name: "Dispose" })).toHaveCount(0);
    await page.keyboard.press("Escape");
    await expect(dialog).toContainText(/not an intake gate/i);

    const code = uniqueCode("RAM715-PROD-A");
    await dialog.getByLabel("Title").fill(`July 15 Active default ${RUN_ID}`);
    await dialog.getByLabel("Matter code").fill(code);
    await dialog.getByLabel("Practice area").fill("Commercial Litigation");
    await dialog.getByLabel("Client name").fill(`Regression Client ${RUN_ID}`);
    await dialog
      .getByLabel("Opposing party")
      .fill(`Regression Opponent A ${RUN_ID}`);

    const createResponsePromise = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === "/api/matters/" &&
        response.request().method() === "POST",
    );
    await expect(dialog.getByRole("button", { name: /Create matter/i })).toBeEnabled();
    await dialog.getByRole("button", { name: /Create matter/i }).click();
    const createResponse = await createResponsePromise;
    if (createResponse.status() >= 200 && createResponse.status() < 300) {
      lifecycleMatter = (await createResponse.json()) as MatterRecord;
    }
    expect(createResponse.status(), await createResponse.text()).toBe(200);
    expect(createResponse.request().postDataJSON()).toMatchObject({ status: "active" });
    expect(
      lifecycleMatter,
      "successful UI Matter creation must return a cleanup-trackable record",
    ).toBeDefined();
    expect(lifecycleMatter.status).toBe("active");
    await expect(dialog).toBeHidden();
    await expect(page.getByText(code).first()).toBeVisible();

    // This probes the server-side default independently of the React form.
    // The request helper intentionally has no `status` property.
    linkedMatter = await createMatterWithoutStatus(uniqueCode("RAM715-PROD-B"));
    expect(linkedMatter.status).toBe("active");
  });

  test("BUG-001: global Notices supports unlinked and multi-matter assigned workflows", async () => {
    await page.goto(`${PROD_BASE_URL}/app`);
    const noticesLink = page.getByRole("link", { name: "Notices", exact: true });
    await expect(noticesLink).toBeVisible();
    await noticesLink.click();
    await expect(page).toHaveURL(/\/app\/notices$/);
    await expect(
      page.getByRole("heading", { name: "Notice management" }),
    ).toBeVisible();

    const receivedSubject = `RAM715 received ${RUN_ID}`;
    await page.getByRole("button", { name: "New notice" }).first().click();
    let dialog = page.getByTestId("create-notice-dialog");
    await dialog.getByLabel("Subject").fill(receivedSubject);
    await dialog.getByLabel("Authority / counterparty").fill("Tax Authority");
    await dialog.getByLabel("Received from").fill("Assessment Division");
    await dialog.getByLabel("Summary").fill("Production regression notice with no matter link.");
    await dialog.getByLabel("Reply required").check();
    await dialog.getByLabel("Reply due on").fill(isoDate(7));
    await expect(dialog.getByText(/Matter links and a document are optional/i)).toBeVisible();

    const ownerSelect = dialog.getByLabel("Owner");
    await expect(ownerSelect).toBeEnabled();
    await expect(ownerSelect.locator(`option[value="${tester.membership.id}"]`)).toHaveCount(1);
    await ownerSelect.selectOption(tester.membership.id);

    const receivedCreatePromise = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === "/api/notices/" &&
        response.request().method() === "POST",
    );
    await dialog.getByRole("button", { name: "Create notice" }).click();
    const receivedResponse = await receivedCreatePromise;
    if (receivedResponse.status() >= 200 && receivedResponse.status() < 300) {
      receivedNotice = (await receivedResponse.json()) as NoticeRecord;
    }
    expect(receivedResponse.status(), await receivedResponse.text()).toBe(201);
    expect(
      receivedNotice,
      "successful received Notice creation must be tracked for cleanup",
    ).toBeDefined();
    expect(receivedNotice.direction).toBe("received");
    expect(receivedNotice.matter_links).toEqual([]);
    expect(receivedNotice.owner_membership_id).toBe(tester.membership.id);

    const receivedRow = page.getByTestId(`notice-row-${receivedNotice.id}`);
    await expect(receivedRow).toContainText(receivedSubject);
    await expect(receivedRow).toContainText(/Standalone.*no linked matters/i);
    await expect(receivedRow).toContainText(`Owner: ${tester.user.full_name}`);
    await expect(receivedRow).toContainText(/Reply due:/i);

    const statusUpdatePromise = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === `/api/notices/${receivedNotice.id}` &&
        response.request().method() === "PATCH",
    );
    const receivedStatus = receivedRow.getByLabel(`Status for ${receivedSubject}`);
    await receivedStatus.selectOption("Under Review");
    const statusResponse = await statusUpdatePromise;
    if (statusResponse.status() >= 200 && statusResponse.status() < 300) {
      receivedNotice = (await statusResponse.json()) as NoticeRecord;
    }
    expect(statusResponse.status(), await statusResponse.text()).toBe(200);
    expect(receivedNotice.status).toBe("Under Review");
    await expect(receivedStatus).toBeEnabled({ timeout: 30_000 });
    await expect(receivedStatus).toHaveValue("Under Review");

    const queryFilterPromise = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return (
        url.pathname === "/api/notices/" &&
        response.request().method() === "GET" &&
        url.searchParams.get("query") === receivedSubject &&
        !url.searchParams.has("status") &&
        !url.searchParams.has("owner_membership_id")
      );
    });
    await page.locator("#notice-search").fill(receivedSubject);
    const queryFilterResponse = await queryFilterPromise;
    expect(queryFilterResponse.status(), await queryFilterResponse.text()).toBe(200);

    const statusFilterPromise = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return (
        url.pathname === "/api/notices/" &&
        response.request().method() === "GET" &&
        url.searchParams.get("query") === receivedSubject &&
        url.searchParams.get("status") === "Under Review" &&
        !url.searchParams.has("owner_membership_id")
      );
    });
    await page.getByLabel("Filter by status").fill("Under Review");
    const statusFilterResponse = await statusFilterPromise;
    expect(statusFilterResponse.status(), await statusFilterResponse.text()).toBe(200);

    const filteredRegisterPromise = page.waitForResponse(
      (response) => {
        const url = new URL(response.url());
        return (
          url.pathname === "/api/notices/" &&
          response.request().method() === "GET" &&
          url.searchParams.get("query") === receivedSubject &&
          url.searchParams.get("status") === "Under Review" &&
          url.searchParams.get("owner_membership_id") === tester.membership.id
        );
      },
      { timeout: 30_000 },
    );
    await page.getByLabel("Filter by owner").selectOption(tester.membership.id);
    const filteredRegisterResponse = await filteredRegisterPromise;
    expect(
      filteredRegisterResponse.status(),
      await filteredRegisterResponse.text(),
    ).toBe(200);
    const filteredRegister = (await filteredRegisterResponse.json()) as {
      notices: NoticeRecord[];
    };
    expect(filteredRegister.notices.map((notice) => notice.id)).toContain(
      receivedNotice.id,
    );
    await expect(receivedRow).toBeVisible({ timeout: 30_000 });
    await page.getByRole("button", { name: "Reset" }).click();

    const sentSubject = `RAM715 sent multi ${RUN_ID}`;
    await page.getByRole("button", { name: "New notice" }).first().click();
    dialog = page.getByTestId("create-notice-dialog");
    await dialog.getByLabel("Direction").selectOption("sent");
    await dialog.getByLabel("Subject").fill(sentSubject);
    await dialog.getByLabel("Authority / counterparty").fill("Opposing Counsel");
    await dialog.getByLabel("Summary").fill("One sent notice linked to two matters.");
    await dialog.getByLabel("Owner").selectOption(tester.membership.id);
    await dialog
      .getByRole("checkbox", {
        name: new RegExp(escapeRegExp(lifecycleMatter.matter_code)),
      })
      .check();
    await dialog
      .getByRole("checkbox", {
        name: new RegExp(escapeRegExp(linkedMatter.matter_code)),
      })
      .check();
    const sentFileBody =
      "Ram July 15 deployed multi-matter sent notice regression document.";
    await dialog.getByLabel("Notice document (optional)").setInputFiles({
      name: `ram-0715-${RUN_ID.toLowerCase()}-sent-notice.txt`,
      mimeType: "text/plain",
      buffer: Buffer.from(sentFileBody, "utf8"),
    });

    const sentCreatePromise = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === "/api/notices/" &&
        response.request().method() === "POST",
    );
    const sentUploadPromise = page.waitForResponse(
      (response) =>
        /\/api\/notices\/[^/]+\/file$/.test(new URL(response.url()).pathname) &&
        response.request().method() === "POST",
    );
    await dialog.getByRole("button", { name: "Create notice" }).click();
    const sentResponse = await sentCreatePromise;
    if (sentResponse.status() >= 200 && sentResponse.status() < 300) {
      sentNotice = (await sentResponse.json()) as NoticeRecord;
    }
    expect(sentResponse.status(), await sentResponse.text()).toBe(201);
    expect(
      sentNotice,
      "successful sent Notice creation must be tracked for cleanup",
    ).toBeDefined();
    expect(sentNotice.direction).toBe("sent");
    expect(sentNotice.owner_membership_id).toBe(tester.membership.id);
    expect(new Set(sentNotice.matter_links.map((link) => link.matter_id))).toEqual(
      new Set([lifecycleMatter.id, linkedMatter.id]),
    );
    const sentUploadResponse = await sentUploadPromise;
    if (
      sentUploadResponse.status() >= 200 &&
      sentUploadResponse.status() < 300
    ) {
      sentNotice = (await sentUploadResponse.json()) as NoticeRecord;
    }
    expect(
      sentUploadResponse.status(),
      await sentUploadResponse.text(),
    ).toBe(200);

    await page.getByTestId("notices-sent-tab").click();
    const sentRow = page.getByTestId(`notice-row-${sentNotice.id}`);
    await expect(sentRow).toContainText(sentSubject);
    await expect(sentRow).toContainText(lifecycleMatter.matter_code);
    await expect(sentRow).toContainText(linkedMatter.matter_code);
    const downloadButton = sentRow.getByRole("button", { name: /Download/i });
    await expect(downloadButton).toBeVisible();
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      downloadButton.click(),
    ]);
    const downloadedPath = await download.path();
    expect(downloadedPath).toBeTruthy();
    expect(await readFile(downloadedPath!, "utf8")).toBe(sentFileBody);

    await sentRow.getByRole("button", { name: "Manage details & links" }).click();
    const manageDialog = page.getByRole("dialog", { name: "Manage notice" });
    const linkedMatterCheckbox = manageDialog.getByRole("checkbox", {
      name: new RegExp(escapeRegExp(linkedMatter.matter_code)),
    });
    await expect(linkedMatterCheckbox).toBeChecked();
    await linkedMatterCheckbox.uncheck();
    const linkUpdatePromise = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === `/api/notices/${sentNotice.id}` &&
        response.request().method() === "PATCH",
    );
    await manageDialog.getByRole("button", { name: "Save changes" }).click();
    const linkUpdateResponse = await linkUpdatePromise;
    if (linkUpdateResponse.status() >= 200 && linkUpdateResponse.status() < 300) {
      sentNotice = (await linkUpdateResponse.json()) as NoticeRecord;
    }
    expect(linkUpdateResponse.status(), await linkUpdateResponse.text()).toBe(200);
    await expect(manageDialog).toBeHidden();
    await expect(sentRow).toContainText(lifecycleMatter.matter_code);
    await expect(sentRow).not.toContainText(linkedMatter.matter_code);

    // The matter view must surface the same standalone source record rather
    // than creating a duplicate attachment or file copy.
    await page.goto(
      `${PROD_BASE_URL}/app/matters/${lifecycleMatter.id}/notices`,
    );
    await page.getByTestId("notice-sent-tab").click();
    await expect(
      page.getByTestId(`matter-global-notice-${sentNotice.id}`),
    ).toContainText(sentSubject);

    await page.goto(`${PROD_BASE_URL}/app/notices`);
    await page.getByTestId("notices-sent-tab").click();

    await page.locator("#notice-search").fill(sentSubject);
    await page.getByLabel("Filter by matter").selectOption(lifecycleMatter.id);
    const sentFilterPromise = page.waitForResponse(
      (response) => {
        const url = new URL(response.url());
        return (
          url.pathname === "/api/notices/" &&
          response.request().method() === "GET" &&
          url.searchParams.get("query") === sentSubject &&
          url.searchParams.get("matter_id") === lifecycleMatter.id &&
          url.searchParams.get("owner_membership_id") === tester.membership.id
        );
      },
      { timeout: 30_000 },
    );
    await page.getByLabel("Filter by owner").selectOption(tester.membership.id);
    const sentFilterResponse = await sentFilterPromise;
    expect(sentFilterResponse.status(), await sentFilterResponse.text()).toBe(200);
    const sentFilterRegister = (await sentFilterResponse.json()) as {
      notices: NoticeRecord[];
    };
    expect(sentFilterRegister.notices.map((notice) => notice.id)).toContain(
      sentNotice.id,
    );
    await expect(sentRow).toBeVisible({ timeout: 30_000 });

    // Safe production cleanup: preserve the auditable records, but leave
    // neither notice looking operational after the regression completes.
    receivedNotice = await closeNotice(receivedNotice);
    sentNotice = await closeNotice(sentNotice);
  });

  test("lifecycle: terminal state rejects stale writes, suppresses operations, and reopens only to Intake", async () => {
    // Keep an existing conflict-review record across the lifecycle exercise.
    // It is advisory and must not weaken any terminal-state guard.
    await runClearedConflictCheck(
      lifecycleMatter.id,
      `Regression Opponent A ${RUN_ID}`,
      "run pre-disposal conflict check",
    );

    const today = isoDate(0);
    const future = isoDate(2);
    const preTask = await context.request.post(
      `${PROD_API_BASE_URL}/api/matters/${lifecycleMatter.id}/tasks`,
      {
        headers: await authHeaders(),
        data: { title: `RAM715 task ${RUN_ID}`, due_on: today },
      },
    );
    await expectStatus(preTask, 200, "create pre-disposal task");
    const preTaskRecord = (await preTask.json()) as { id: string };
    const preDeadline = await context.request.post(
      `${PROD_API_BASE_URL}/api/matters/${lifecycleMatter.id}/deadlines`,
      {
        headers: await authHeaders(),
        data: {
          title: `RAM715 deadline ${RUN_ID}`,
          kind: "filing",
          due_on: future,
        },
      },
    );
    await expectStatus(preDeadline, 200, "create pre-disposal deadline");
    const preDeadlineRecord = (await preDeadline.json()) as { id: string };
    const preHearing = await context.request.post(
      `${PROD_API_BASE_URL}/api/matters/${lifecycleMatter.id}/hearings`,
      {
        headers: await authHeaders(),
        data: {
          hearing_on: future,
          forum_name: "Delhi High Court",
          purpose: `RAM715 hearing ${RUN_ID}`,
        },
      },
    );
    await expectStatus(preHearing, 200, "create pre-disposal hearing");
    const preHearingRecord = (await preHearing.json()) as { id: string };

    await page.goto(`${PROD_BASE_URL}/app/matters/${lifecycleMatter.id}`);
    await page.getByTestId("matter-edit-open").click();
    await page
      .getByTestId("matter-edit-title")
      .fill(`Stale title must not persist ${RUN_ID}`);

    const beforeDispose = await getMatter(lifecycleMatter.id);
    lifecycleMatter = await transitionLifecycle(
      beforeDispose,
      "disposed",
      "Final order closed this production regression matter.",
    );
    expect(lifecycleMatter.status).toBe("disposed");

    const staleSavePromise = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === `/api/matters/${lifecycleMatter.id}` &&
        response.request().method() === "PATCH",
    );
    await page.getByTestId("matter-edit-save").click();
    const staleSave = await staleSavePromise;
    expect(staleSave.status()).toBe(409);
    const stalePayload = staleSave.request().postDataJSON() as Record<
      string,
      unknown
    >;
    expect(stalePayload).toMatchObject({
      title: `Stale title must not persist ${RUN_ID}`,
      expected_updated_at: beforeDispose.updated_at,
    });
    expect(stalePayload).not.toHaveProperty("status");
    expect(stalePayload).not.toHaveProperty("is_active");
    await expect(page.getByTestId("matter-edit-stale-write")).toContainText(
      /changed in another session/i,
    );
    expect((await getMatter(lifecycleMatter.id)).status).toBe("disposed");

    // Even a client that deliberately attempts the old generic status patch
    // cannot bypass the terminal lifecycle endpoint.
    const genericReopen = await context.request.patch(
      `${PROD_API_BASE_URL}/api/matters/${lifecycleMatter.id}`,
      {
        headers: await authHeaders(),
        data: {
          status: "active",
          expected_updated_at: lifecycleMatter.updated_at,
        },
      },
    );
    await expectStatus(genericReopen, 409, "reject generic disposed -> active patch");
    expect((await getMatter(lifecycleMatter.id)).status).toBe("disposed");

    for (const [label, path, data] of [
      [
        "task",
        "tasks",
        { title: `Rejected task ${RUN_ID}`, due_on: today },
      ],
      [
        "deadline",
        "deadlines",
        { title: `Rejected deadline ${RUN_ID}`, kind: "filing", due_on: future },
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
      const response = await context.request.post(
        `${PROD_API_BASE_URL}/api/matters/${lifecycleMatter.id}/${path}`,
        { headers: await authHeaders(), data },
      );
      await expectStatus(response, 409, `reject ${label} on disposed matter`);
    }
    expect((await getMatter(lifecycleMatter.id)).status).toBe("disposed");

    const todayResponse = await context.request.get(
      `${PROD_API_BASE_URL}/api/me/today`,
      { headers: await authHeaders() },
    );
    await expectStatus(todayResponse, 200, "read Today after disposal");
    expect(JSON.stringify(await todayResponse.json())).not.toContain(
      lifecycleMatter.id,
    );

    const calendarResponse = await context.request.get(
      `${PROD_API_BASE_URL}/api/calendar/events`,
      {
        headers: await authHeaders(),
        params: { from: today, to: future },
      },
    );
    await expectStatus(calendarResponse, 200, "read calendar after disposal");
    const calendar = (await calendarResponse.json()) as {
      events: Array<{ matter_id: string }>;
    };
    expect(calendar.events.map((event) => event.matter_id)).not.toContain(
      lifecycleMatter.id,
    );

    await page.reload();
    await expect(page.getByTestId("matter-edit-open")).toHaveCount(0);
    await page.getByTestId("matter-reopen-trigger").click();
    await page
      .getByTestId("matter-lifecycle-reason")
      .fill("Fresh client instructions justify controlled reopening.");
    const reopenResponsePromise = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname ===
          `/api/matters/${lifecycleMatter.id}/lifecycle/status` &&
        response.request().method() === "PATCH",
    );
    await page.getByTestId("matter-lifecycle-confirm").click();
    const reopenResponse = await reopenResponsePromise;
    expect(reopenResponse.status(), await reopenResponse.text()).toBe(200);
    lifecycleMatter = (await reopenResponse.json()) as MatterRecord;
    expect(lifecycleMatter.status).toBe("intake");

    const tasksAfterReopen = await context.request.get(
      `${PROD_API_BASE_URL}/api/matters/${lifecycleMatter.id}/tasks`,
      { headers: await authHeaders() },
    );
    await expectStatus(tasksAfterReopen, 200, "read tasks after controlled reopen");
    const reopenedTask = (
      (await tasksAfterReopen.json()) as {
        tasks: Array<{ id: string; status: string }>;
      }
    ).tasks.find((task) => task.id === preTaskRecord.id);
    expect(reopenedTask?.status).toBe("cancelled");

    const deadlinesAfterReopen = await context.request.get(
      `${PROD_API_BASE_URL}/api/matters/${lifecycleMatter.id}/deadlines`,
      { headers: await authHeaders() },
    );
    await expectStatus(
      deadlinesAfterReopen,
      200,
      "read deadlines after controlled reopen",
    );
    const reopenedDeadline = (
      (await deadlinesAfterReopen.json()) as {
        deadlines: Array<{ id: string; status: string }>;
      }
    ).deadlines.find((deadline) => deadline.id === preDeadlineRecord.id);
    expect(reopenedDeadline?.status).toBe("cancelled");

    const workspaceAfterReopen = await context.request.get(
      `${PROD_API_BASE_URL}/api/matters/${lifecycleMatter.id}/workspace`,
      { headers: await authHeaders() },
    );
    await expectStatus(
      workspaceAfterReopen,
      200,
      "read hearing history after controlled reopen",
    );
    const reopenedHearing = (
      (await workspaceAfterReopen.json()) as {
        hearings: Array<{ id: string; status: string }>;
      }
    ).hearings.find((hearing) => hearing.id === preHearingRecord.id);
    expect(reopenedHearing?.status).toBe("cancelled");

    for (const [label, path, data] of [
      ["lifecycle-cancelled task", `tasks/${preTaskRecord.id}`, { status: "todo" }],
      [
        "lifecycle-cancelled deadline",
        `deadlines/${preDeadlineRecord.id}`,
        { status: "open" },
      ],
      [
        "lifecycle-cancelled hearing",
        `hearings/${preHearingRecord.id}`,
        { status: "scheduled" },
      ],
    ] as const) {
      const response = await context.request.patch(
        `${PROD_API_BASE_URL}/api/matters/${lifecycleMatter.id}/${path}`,
        { headers: await authHeaders(), data },
      );
      await expectStatus(response, 409, `reject resurrection of ${label}`);
    }

    const todayAfterReopen = await context.request.get(
      `${PROD_API_BASE_URL}/api/me/today`,
      { headers: await authHeaders() },
    );
    await expectStatus(todayAfterReopen, 200, "read Today after controlled reopen");
    const todayAfterReopenJson = JSON.stringify(await todayAfterReopen.json());
    expect(todayAfterReopenJson).not.toContain(preTaskRecord.id);
    expect(todayAfterReopenJson).not.toContain(preDeadlineRecord.id);
    expect(todayAfterReopenJson).not.toContain(preHearingRecord.id);

    lifecycleMatter = await getMatter(lifecycleMatter.id);
    const activate = await context.request.patch(
      `${PROD_API_BASE_URL}/api/matters/${lifecycleMatter.id}`,
      {
        headers: await authHeaders(),
        data: {
          status: "active",
          expected_updated_at: lifecycleMatter.updated_at,
        },
      },
    );
    await expectStatus(activate, 200, "activate reopened matter without conflict gate");
    lifecycleMatter = (await activate.json()) as MatterRecord;
    expect(lifecycleMatter.status).toBe("active");

    // Safe cleanup keeps the two test matters out of every operational view.
    lifecycleMatter = await transitionLifecycle(
      lifecycleMatter,
      "disposed",
      "Production regression complete; return test matter to terminal state.",
    );
    linkedMatter = await transitionLifecycle(
      await getMatter(linkedMatter.id),
      "disposed",
      "Production regression complete; return linked test matter to terminal state.",
    );
    expect(lifecycleMatter.status).toBe("disposed");
    expect(linkedMatter.status).toBe("disposed");
  });
});
