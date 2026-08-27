/**
 * Ram 2026-07-22 deployed-production regression.
 *
 * This suite signs in with tester credentials supplied through environment
 * variables, creates uniquely named Matter records in the authorized tenant,
 * proves conflict review is optional on both status-edit surfaces, and leaves
 * every created Matter in the terminal Disposed state.
 *
 * Run only after the candidate commit is deployed:
 *
 *   npx playwright test --config playwright.prod-ram.config.ts \
 *     tests/e2e/ram-2026-07-22-prod.spec.ts --project tester-prod-chromium
 */
import {
  expect,
  test,
  type BrowserContext,
  type Browser,
  type Page,
} from "@playwright/test";

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
const IDEMPOTENT_NETWORK_RETRIES = 2;
const RUN_ID = `${Date.now().toString(36)}-${Math.random()
  .toString(36)
  .slice(2, 8)}`.toUpperCase();

type HttpResponse = {
  status(): number;
  text(): Promise<string>;
};

type MatterRecord = {
  id: string;
  matter_code: string;
  status: "intake" | "active" | "on_hold" | "disposed";
  updated_at: string;
  lifecycle_version: number;
};

type AuthContext = {
  company: { slug: string };
  user: { email: string };
  capabilities: string[];
};

let context: BrowserContext;
let page: Page;
let intakeMatter: MatterRecord | undefined;
let onHoldMatter: MatterRecord | undefined;
const overlapName = `Conflict Review ${RUN_ID}`;
const clearedPartyName = `Cleared Counterparty ${RUN_ID}`;

function requiredPassword(): string {
  const value = process.env.CASEOPS_RAM_PROD_PASSWORD?.trim() ?? "";
  if (!value) {
    throw new Error(
      "CASEOPS_RAM_PROD_PASSWORD is required for the July 22 production regression.",
    );
  }
  return value;
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function uniqueCode(prefix: string): string {
  return `${prefix}-${RUN_ID}`.replace(/[^A-Z0-9-]/g, "").slice(0, 78);
}

async function expectStatus(
  response: HttpResponse,
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
  expect(csrf, "caseops_csrf cookie must exist after sign-in").toBeTruthy();
  return {
    Accept: "application/json",
    Cookie: cookieHeader,
    "Content-Type": "application/json",
    "X-CSRF-Token": csrf!,
  };
}

async function signInAsTester(): Promise<void> {
  await context.clearCookies();
  await page.goto(`${PROD_BASE_URL}/sign-in`);
  await page.locator("#company-slug").fill(COMPANY_SLUG);
  await page.locator("#email").fill(TESTER_EMAIL);
  await page.locator("#password").fill(requiredPassword());
  const loginPromise = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/api/auth/login" &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  await expectStatus(await loginPromise, 200, "sign in as July 22 tester");
  await page.waitForURL(
    new RegExp(`${escapeRegExp(PROD_BASE_URL)}/app(?:[/?]|$)`),
  );

  const meResponse = await context.request.get(
    `${PROD_API_BASE_URL}/api/auth/me`,
    {
      headers: await authHeaders(),
      maxRetries: IDEMPOTENT_NETWORK_RETRIES,
    },
  );
  await expectStatus(meResponse, 200, "read tester auth context");
  const auth = (await meResponse.json()) as AuthContext;
  expect(auth.company.slug).toBe(COMPANY_SLUG);
  expect(auth.user.email.toLowerCase()).toBe(TESTER_EMAIL.toLowerCase());
  expect(auth.capabilities).toEqual(
    expect.arrayContaining([
      "matters:create",
      "matters:edit",
      "matters:archive",
      "conflicts:run",
      "conflicts:resolve",
    ]),
  );
}

async function createMatter(
  code: string,
  status: "intake" | "on_hold",
  clientName: string,
  opposingParty: string,
): Promise<MatterRecord> {
  const response = await context.request.post(
    `${PROD_API_BASE_URL}/api/matters/`,
    {
      headers: await authHeaders(),
      data: {
        title: `July 22 optional conflict review ${RUN_ID}`,
        matter_code: code,
        client_name: clientName,
        opposing_party: opposingParty,
        practice_area: "Commercial Litigation",
        forum_level: "high_court",
        court_name: "Delhi High Court",
        status,
        description: `Production regression ${RUN_ID}`,
      },
    },
  );
  let created: MatterRecord | undefined;
  if (response.status() >= 200 && response.status() < 300) {
    created = (await response.json()) as MatterRecord;
  }
  await expectStatus(response, 200, `create ${status} production matter`);
  expect(created, "created Matter must be available for cleanup").toBeDefined();
  return created!;
}

async function getMatter(matterId: string): Promise<MatterRecord> {
  const response = await context.request.get(
    `${PROD_API_BASE_URL}/api/matters/${matterId}`,
    {
      headers: await authHeaders(),
      maxRetries: IDEMPOTENT_NETWORK_RETRIES,
    },
  );
  await expectStatus(response, 200, `read matter ${matterId}`);
  return (await response.json()) as MatterRecord;
}

async function disposeMatter(matter: MatterRecord): Promise<void> {
  const current = await getMatter(matter.id);
  if (current.status === "disposed") return;
  const response = await context.request.patch(
    `${PROD_API_BASE_URL}/api/matters/${current.id}/lifecycle/status`,
    {
      headers: await authHeaders(),
      data: {
        to_status: "disposed",
        expected_from_status: current.status,
        expected_updated_at: current.updated_at,
        reason: "July 22 production regression cleanup completed.",
      },
    },
  );
  await expectStatus(response, 200, `dispose ${current.matter_code}`);
}

async function discoverRunMatters(): Promise<MatterRecord[]> {
  const response = await context.request.get(
    `${PROD_API_BASE_URL}/api/matters/`,
    {
      headers: await authHeaders(),
      maxRetries: IDEMPOTENT_NETWORK_RETRIES,
      params: { q: RUN_ID, limit: 100 },
    },
  );
  await expectStatus(response, 200, "discover July 22 production matters");
  return ((await response.json()) as { matters: MatterRecord[] }).matters;
}

test.describe.serial("Ram 2026-07-22 deployed optional conflict review", () => {
  test.setTimeout(180_000);

  test.beforeAll(async ({ browser }: { browser: Browser }) => {
    context = await browser.newContext({ storageState: { cookies: [], origins: [] } });
    page = await context.newPage();
    await signInAsTester();
  });

  test.afterAll(async () => {
    const cleanupFailures: string[] = [];
    if (context) {
      try {
        const discovered = await discoverRunMatters();
        const records = new Map<string, MatterRecord>();
        for (const matter of [intakeMatter, onHoldMatter, ...discovered]) {
          if (matter) records.set(matter.id, matter);
        }
        for (const matter of records.values()) {
          try {
            await disposeMatter(matter);
          } catch (error) {
            cleanupFailures.push(
              `${matter.matter_code}: ${error instanceof Error ? error.message : String(error)}`,
            );
          }
        }
      } catch (error) {
        cleanupFailures.push(
          `discovery: ${error instanceof Error ? error.message : String(error)}`,
        );
      }
      await context.close();
    }
    expect(
      cleanupFailures,
      "production regression cleanup must leave no test Matter operational",
    ).toEqual([]);
  });

  test("BUG-001 detail: Intake activates with no conflict check", async () => {
    intakeMatter = await createMatter(
      uniqueCode("RAM722-PROD-INTAKE"),
      "intake",
      overlapName,
      `Independent Opponent ${RUN_ID}`,
    );
    // Register this before navigation so a fast successful response cannot
    // race past the diagnostic.  This remains an end-user UI assertion below;
    // it additionally proves that the browser received the expected empty
    // payload if the card ever stays in its loading state.
    const initialConflictChecksPromise = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname ===
          `/api/matters/${intakeMatter!.id}/conflict-checks` &&
        response.request().method() === "GET",
    );
    await page.goto(`${PROD_BASE_URL}/app/matters/${intakeMatter.id}`);
    const initialConflictChecks = await initialConflictChecksPromise;
    await expectStatus(
      initialConflictChecks,
      200,
      "load the Intake Matter's empty conflict-check history",
    );
    const initialConflictPayload = (await initialConflictChecks.json()) as {
      matter_id: string;
      checks: unknown[];
    };
    expect(initialConflictPayload.matter_id).toBe(intakeMatter.id);
    expect(initialConflictPayload.checks).toEqual([]);

    const conflictCard = page.getByTestId("matter-conflict-card");
    await expect(conflictCard).toContainText("No conflict check has been run yet.");
    await page.getByTestId("matter-edit-open").click();
    await page.getByTestId("matter-edit-status").selectOption("active");

    const activationPromise = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === `/api/matters/${intakeMatter!.id}` &&
        response.request().method() === "PATCH",
    );
    await page.getByTestId("matter-edit-save").click();
    const activation = await activationPromise;
    await expectStatus(activation, 200, "activate production Intake matter");
    intakeMatter = (await activation.json()) as MatterRecord;
    expect(intakeMatter.status).toBe("active");
    await expect(page.getByTestId("matter-edit-form")).toBeHidden();
    await expect(page.getByTestId("matter-edit-active-conflict-hint")).toHaveCount(0);
    await expect(page.getByTestId("matter-edit-conflict-gate")).toHaveCount(0);
    intakeMatter = await getMatter(intakeMatter.id);
    expect(intakeMatter.status).toBe("active");
    await page.reload();
    await expect(page.getByText("active", { exact: true }).first()).toBeVisible();
  });

  test("BUG-001 lifecycle: pre-reopen clearance is historical and nonblocking", async () => {
    onHoldMatter = await createMatter(
      uniqueCode("RAM722-PROD-HOLD"),
      "on_hold",
      `Independent Client ${RUN_ID}`,
      clearedPartyName,
    );
    await page.goto(`${PROD_BASE_URL}/app/matters/${onHoldMatter.id}`);

    const conflictCard = page.getByTestId("matter-conflict-card");
    await conflictCard.getByTestId("conflict-run-open").click();
    await expect(page.getByTestId("conflict-run-opposing")).toHaveValue(
      clearedPartyName,
    );
    const runPromise = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname ===
          `/api/matters/${onHoldMatter!.id}/conflict-checks` &&
        response.request().method() === "POST",
    );
    await page.getByTestId("conflict-run-submit").click();
    const runResponse = await runPromise;
    await expectStatus(runResponse, 200, "run production conflict review");
    const clearedCheck = (await runResponse.json()) as {
      id: string;
      status: string;
      matter_lifecycle_version: number;
    };
    expect(clearedCheck).toMatchObject({
      status: "cleared",
      matter_lifecycle_version: onHoldMatter.lifecycle_version,
    });
    await expect(conflictCard.getByTestId("conflict-status-cleared")).toBeVisible();

    await page.goto(`${PROD_BASE_URL}/app/matters`);
    await page.locator("#matter-filter-q").fill(onHoldMatter.matter_code);
    await page.getByRole("button", { name: /Apply/i }).click();
    const statusSelect = page.getByLabel(`Status for ${onHoldMatter.matter_code}`);
    await expect(statusSelect).toHaveValue("on_hold");

    const onHoldActivationPromise = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === `/api/matters/${onHoldMatter!.id}` &&
        response.request().method() === "PATCH",
    );
    await statusSelect.selectOption("active");
    const onHoldActivation = await onHoldActivationPromise;
    await expectStatus(onHoldActivation, 200, "activate production On-hold matter");
    onHoldMatter = (await onHoldActivation.json()) as MatterRecord;
    expect(onHoldMatter.status).toBe("active");

    // This is a new page document, so capture the exact API result before
    // asserting its user-visible projection. If the cleared badge is absent,
    // this distinguishes a stale server record from a client rendering/query
    // issue without weakening the UI regression check.
    const reloadedConflictChecksPromise = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname ===
          `/api/matters/${onHoldMatter!.id}/conflict-checks` &&
        response.request().method() === "GET",
    );
    await page.goto(`${PROD_BASE_URL}/app/matters/${onHoldMatter.id}`);
    const reloadedConflictChecks = await reloadedConflictChecksPromise;
    await expectStatus(
      reloadedConflictChecks,
      200,
      "reload the cleared conflict-check history after ordinary activation",
    );
    const reloadedConflictPayload = (await reloadedConflictChecks.json()) as {
      matter_id: string;
      checks: Array<{
        id: string;
        status: string;
        matter_lifecycle_version: number;
      }>;
    };
    expect(reloadedConflictPayload.matter_id).toBe(onHoldMatter.id);
    expect(reloadedConflictPayload.checks).toContainEqual(
      expect.objectContaining({
        id: clearedCheck.id,
        status: "cleared",
        matter_lifecycle_version: onHoldMatter.lifecycle_version,
      }),
    );
    await expect(conflictCard.getByTestId("conflict-status-cleared")).toBeVisible();

    const beforeDispose = onHoldMatter;
    const disposePromise = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname ===
          `/api/matters/${onHoldMatter!.id}/lifecycle/status` &&
        response.request().method() === "PATCH",
    );
    await page.getByTestId("matter-dispose-trigger").click();
    await page
      .getByTestId("matter-lifecycle-reason")
      .fill("July 22 production regression verifies disposal before reopen.");
    await page.getByTestId("matter-lifecycle-confirm").click();
    const disposedResponse = await disposePromise;
    await expectStatus(disposedResponse, 200, "dispose production matter");
    expect(disposedResponse.request().postDataJSON()).toMatchObject({
      to_status: "disposed",
      expected_from_status: "active",
      expected_updated_at: beforeDispose.updated_at,
    });
    const disposedMatter = (await disposedResponse.json()) as MatterRecord;
    expect(disposedMatter.lifecycle_version).toBe(
      beforeDispose.lifecycle_version + 1,
    );
    onHoldMatter = disposedMatter;

    await expect(page.getByTestId("matter-reopen-trigger")).toBeVisible();
    const beforeReopen = onHoldMatter;
    const reopenPromise = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname ===
          `/api/matters/${onHoldMatter!.id}/lifecycle/status` &&
        response.request().method() === "PATCH",
    );
    await page.getByTestId("matter-reopen-trigger").click();
    await page
      .getByTestId("matter-lifecycle-reason")
      .fill("Fresh production-test instructions require reopen into Intake.");
    await page.getByTestId("matter-lifecycle-confirm").click();
    const reopenedResponse = await reopenPromise;
    await expectStatus(reopenedResponse, 200, "reopen production matter");
    expect(reopenedResponse.request().postDataJSON()).toMatchObject({
      to_status: "intake",
      expected_from_status: "disposed",
      expected_updated_at: beforeReopen.updated_at,
    });
    const reopenedMatter = (await reopenedResponse.json()) as MatterRecord;
    expect(reopenedMatter.status).toBe("intake");
    expect(reopenedMatter.lifecycle_version).toBe(
      beforeReopen.lifecycle_version + 1,
    );
    onHoldMatter = reopenedMatter;

    const historicalBadge = conflictCard.getByTestId("conflict-status-historical");
    await expect(historicalBadge).toContainText(/Historical \(stale\): Cleared/i);
    await expect(historicalBadge).toHaveAttribute("data-original-status", "cleared");
    await expect(conflictCard.getByTestId("conflict-status-cleared")).toHaveCount(0);
    await expect(conflictCard.getByTestId("conflict-historical-notice")).toContainText(
      /does not block status changes/i,
    );
    await expect(conflictCard.getByTestId("conflict-resolve-clear")).toHaveCount(0);

    await page.getByTestId("matter-edit-open").click();
    await page.getByTestId("matter-edit-status").selectOption("active");
    const reopenedActivationPromise = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === `/api/matters/${onHoldMatter!.id}` &&
        response.request().method() === "PATCH",
    );
    await page.getByTestId("matter-edit-save").click();
    const reopenedActivation = await reopenedActivationPromise;
    await expectStatus(reopenedActivation, 200, "activate reopened production matter");
    onHoldMatter = (await reopenedActivation.json()) as MatterRecord;
    expect(onHoldMatter.status).toBe("active");
    expect(onHoldMatter.lifecycle_version).toBe(reopenedMatter.lifecycle_version);
    onHoldMatter = await getMatter(onHoldMatter.id);
    expect(onHoldMatter.status).toBe("active");
    await page.reload();
    await expect(page.getByText("active", { exact: true }).first()).toBeVisible();
    await expect(conflictCard.getByTestId("conflict-status-historical")).toContainText(
      "Cleared",
    );
  });
});
