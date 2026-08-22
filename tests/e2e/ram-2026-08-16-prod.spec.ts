/**
 * PR #237 / 2026-08-16 deployed-production UX acceptance.
 *
 * Production safety boundaries are explicit:
 * - authentication, release identity, navigation, directory, and non-billing
 *   page data are read from the deployed services;
 * - every browser billing GET is fulfilled from an in-spec fixture because a
 *   nominally read-only billing request can lazily create an account or expire
 *   credits server-side;
 * - the partial-acknowledgement coverage GET and POST are both browser stubs.
 *   The POST is never forwarded and returns a deterministic concurrency
 *   rejection; no production IP row is read or changed;
 * - mutation guards abort any other browser API write after authentication.
 *
 * Run only after the candidate is deployed, with the canonical tester project:
 *
 *   npx playwright test --config playwright.prod-ram.config.ts \
 *     tests/e2e/ram-2026-08-16-prod.spec.ts --project tester-prod-chromium
 *
 * The dedicated QA tenant must have the capabilities exercised below and at
 * least one active directory member. No billing or IP-coverage seed is needed.
 */
import {
  expect,
  test,
  type APIResponse,
  type Page,
  type Route,
} from "@playwright/test";

const envOr = (key: string, fallback: string): string => {
  const value = (process.env[key] ?? "").trim();
  return value || fallback;
};

const LOCAL_BOOTSTRAP = process.env.CASEOPS_PR237_LOCAL_BOOTSTRAP === "1";
const PROD_BASE_URL = envOr("PROD_BASE_URL", "https://caseops.ai");
const PROD_API_BASE_URL = envOr(
  "PROD_API_BASE_URL",
  "https://api.caseops.ai",
);

function isHttpLoopback(rawUrl: string): boolean {
  try {
    const url = new URL(rawUrl);
    return (
      url.protocol === "http:" &&
      ["localhost", "127.0.0.1", "[::1]", "::1"].includes(
        url.hostname.toLowerCase(),
      )
    );
  } catch {
    return false;
  }
}

if (
  LOCAL_BOOTSTRAP &&
  (!isHttpLoopback(PROD_BASE_URL) || !isHttpLoopback(PROD_API_BASE_URL))
) {
  throw new Error(
    "CASEOPS_PR237_LOCAL_BOOTSTRAP=1 is allowed only when both PROD_BASE_URL " +
      "and PROD_API_BASE_URL are explicit http loopback URLs.",
  );
}
const COMPANY_SLUG = LOCAL_BOOTSTRAP
  ? "pr237-ux-proof"
  : envOr("CASEOPS_RAM_PROD_SLUG", "legal");
const TESTER_EMAIL = LOCAL_BOOTSTRAP
  ? "owner-pr237-ux-proof@example.com"
  : envOr("CASEOPS_RAM_PROD_EMAIL", "hari.gupta@gmail.com");
const LOCAL_PASSWORD = "Pr237UxProof2026!Strong";

type AuthContext = {
  company: { slug: string };
  user: { email: string };
  membership: { id: string; role: string };
  capabilities: string[];
};

type CompanyUser = {
  membership_id: string;
  email: string;
  full_name: string;
  role: string;
  membership_active: boolean;
  user_active: boolean;
};

type CompanyUsersResponse = {
  company_slug: string;
  users: CompanyUser[];
};

type CoverageRow = {
  coverage_id: string;
  docket_title: string;
  docket_identifier: string | null;
  deadline_title: string | null;
  due_on: string | null;
  transfer_pending: boolean;
  reassignment_version: number;
  [key: string]: unknown;
};

type CoverageResponse = { coverages: CoverageRow[] };

const SAFE_USAGE_SNAPSHOT = {
  ai_credits_included: 100,
  ai_credits_used: 0,
  ai_credits_remaining: 100,
  topup_credits_available: 0,
  tracked_cases_used: 0,
  tracked_cases_limit: 100,
  manual_refreshes_used_today: 0,
  manual_refreshes_limit_daily: 10,
  storage_used_bytes: 0,
  storage_limit_bytes: 1_073_741_824,
  users_internal_used: 1,
  users_internal_limit: 5,
  users_viewer_used: 0,
  users_viewer_limit: 0,
  matters_active_used: 0,
  matters_active_limit: 100,
};

const SAFE_BILLING_RESPONSES: Readonly<Record<string, unknown>> = {
  "/api/billing/current": {
    billing_account: null,
    subscription: null,
    entitlements: {},
    usage: SAFE_USAGE_SNAPSHOT,
    payment_provider: { mode: "disabled", ready: false },
  },
  "/api/billing/plans": {
    version: "pr237-production-safe-fixture",
    plans: [],
    add_ons: [],
  },
  "/api/billing/add-ons": {
    version: "pr237-production-safe-fixture",
    plans: [],
    add_ons: [],
  },
  "/api/billing/invoices": { invoices: [] },
  "/api/billing/credit-ledger": { rows: [] },
  "/api/billing/usage": {
    period_start: null,
    period_end: null,
    snapshot: SAFE_USAGE_SNAPSHOT,
    by_feature: [],
    by_user: [],
    by_matter: [],
    by_tracked_case: [],
    daily: [],
    blocked_events: [],
  },
  "/api/billing/reports/spend": {
    period_start: null,
    period_end: null,
    snapshot: SAFE_USAGE_SNAPSHOT,
    by_feature: [],
    by_user: [],
    by_matter: [],
    by_tracked_case: [],
    daily: [],
    blocked_events: [],
  },
};

const SAFE_ACK_COVERAGE: CoverageRow = {
  coverage_id: "23700000-0000-4237-8237-000000000001",
  docket_id: "23700000-0000-4237-8237-000000000002",
  docket_title: "PR 237 SAFE ACKNOWLEDGEMENT",
  docket_identifier: "TM 237",
  deadline_title: "Production-safe concurrency proof",
  due_on: "2026-08-20",
  days_until_due: 4,
  critical: true,
  acknowledged: false,
  coverage_status: "pending",
  transfer_pending: false,
  reassignment_version: 7,
};

type NavItem = {
  label: string;
  href: string;
  capability?: string;
};

const NAV_GROUPS: ReadonlyArray<{
  label: string;
  items: readonly NavItem[];
}> = [
  {
    label: "Overview",
    items: [
      { label: "Home", href: "/app" },
      { label: "Today", href: "/app/today" },
    ],
  },
  {
    label: "Schedule",
    items: [
      { label: "Hearings", href: "/app/hearings" },
      { label: "Cause list", href: "/app/cause-list" },
      { label: "Calendar", href: "/app/calendar" },
    ],
  },
  {
    label: "Casework",
    items: [
      { label: "Matters", href: "/app/matters" },
      { label: "Import activity", href: "/app/imports" },
      { label: "Notices", href: "/app/notices" },
      { label: "Intake", href: "/app/intake", capability: "intake:submit" },
      { label: "Mailbox", href: "/app/mailbox" },
      { label: "Drive", href: "/app/drive" },
      { label: "Contracts", href: "/app/contracts" },
      { label: "Clients", href: "/app/clients", capability: "clients:view" },
      { label: "Outside Counsel", href: "/app/outside-counsel" },
    ],
  },
  {
    label: "Intellectual property",
    items: [
      { label: "IP docket", href: "/app/ip", capability: "ip:read" },
      {
        label: "Trademark portfolio",
        href: "/app/ip/portfolio",
        capability: "ip:read",
      },
      {
        label: "Deadline control",
        href: "/app/ip/docket",
        capability: "ip:read",
      },
      {
        label: "Trademark renewals",
        href: "/app/ip/renewals",
        capability: "ip:read",
      },
    ],
  },
  {
    label: "Intelligence",
    items: [
      { label: "Research", href: "/app/research" },
      { label: "Drafting", href: "/app/drafting" },
      { label: "Recommendations", href: "/app/recommendations" },
      { label: "Portfolio", href: "/app/portfolio" },
      { label: "Courts", href: "/app/courts" },
      { label: "Statutes", href: "/app/statutes" },
      {
        label: "Case tracking",
        href: "/app/case-tracking",
        capability: "authorities:search",
      },
    ],
  },
  {
    label: "Workspace",
    items: [
      { label: "Admin", href: "/app/admin", capability: "workspace:admin" },
      {
        label: "Billing",
        href: "/app/admin/billing",
        capability: "workspace:admin",
      },
      {
        label: "Integrations",
        href: "/app/admin/integrations",
        capability: "workspace:admin",
      },
      {
        label: "Microsoft 365",
        href: "/app/admin/microsoft365",
        capability: "workspace:admin",
      },
      {
        label: "Inbound email",
        href: "/app/admin/inbound-email",
        capability: "workspace:admin",
      },
      {
        label: "Matter billing",
        href: "/app/admin/matter-billing",
        capability: "workspace:admin",
      },
      {
        label: "Judge aliases",
        href: "/app/admin/judge-aliases",
        capability: "workspace:admin",
      },
      {
        label: "Platform admin",
        href: "/app/platform-admin",
        capability: "platform:admin",
      },
      {
        label: "Platform costs",
        href: "/app/platform-admin/costs",
        capability: "platform:admin",
      },
      { label: "Notifications", href: "/app/notification-preferences" },
      { label: "User guide", href: "/guide" },
    ],
  },
];

function required(key: string): string {
  const value = (process.env[key] ?? "").trim();
  if (!value) throw new Error(`${key} is required for the August 16 production proof.`);
  return value;
}

function testerPassword(): string {
  return LOCAL_BOOTSTRAP
    ? LOCAL_PASSWORD
    : required("CASEOPS_RAM_PROD_PASSWORD");
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

async function responseBody(response: APIResponse): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return await response.text();
  }
}

async function expectStatus(
  response: APIResponse,
  expected: number,
  operation: string,
): Promise<void> {
  expect(
    response.status(),
    `${operation}: ${JSON.stringify(await responseBody(response))}`,
  ).toBe(expected);
}

async function assertExactRelease(page: Page): Promise<void> {
  const expectedSha = required("CASEOPS_EXPECTED_RELEASE_SHA").toLowerCase();
  expect(expectedSha).toMatch(/^[0-9a-f]{40}$/);
  const [apiResponse, webResponse] = await Promise.all([
    page.request.get(`${PROD_API_BASE_URL}/api/build`),
    page.request.get(`${PROD_BASE_URL}/api/release-identity`),
  ]);
  await expectStatus(apiResponse, 200, "read API release identity");
  await expectStatus(webResponse, 200, "read web release identity");
  expect((await apiResponse.json()).release_sha).toBe(expectedSha);
  expect((await webResponse.json()).release_sha).toBe(expectedSha);
}

async function signIn(page: Page): Promise<AuthContext> {
  await page.goto(`${PROD_BASE_URL}/sign-in`);
  await page.locator("#company-slug").fill(COMPANY_SLUG);
  await page.locator("#email").fill(TESTER_EMAIL);
  await page.locator("#password").fill(testerPassword());
  const loginPromise = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/api/auth/login" &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  const login = await loginPromise;
  expect(login.status(), await login.text()).toBe(200);
  const auth = (await login.json()) as AuthContext;
  expect(auth.company.slug).toBe(COMPANY_SLUG);
  expect(auth.user.email.toLowerCase()).toBe(TESTER_EMAIL.toLowerCase());
  await page.waitForURL(
    new RegExp(`${escapeRegExp(PROD_BASE_URL)}/app(?:[/?]|$)`),
  );
  return auth;
}

function expectCapabilities(auth: AuthContext, capabilities: string[]): void {
  expect(auth.capabilities).toEqual(expect.arrayContaining(capabilities));
}

function expectedGroups(capabilities: readonly string[]) {
  const allowed = new Set(capabilities);
  return NAV_GROUPS.map((group) => ({
    label: group.label,
    items: group.items
      .filter((item) => !item.capability || allowed.has(item.capability))
      .map(({ label, href }) => ({ label, href })),
  })).filter((group) => group.items.length > 0);
}

function deferred(): { promise: Promise<void>; release: () => void } {
  let release!: () => void;
  const promise = new Promise<void>((resolve) => {
    release = resolve;
  });
  return { promise, release };
}

function observedRequest(): {
  promise: Promise<void>;
  observed: () => void;
} {
  let observed!: () => void;
  const promise = new Promise<void>((resolve) => {
    observed = resolve;
  });
  return { promise, observed };
}

async function delayedPassThrough(
  route: Route,
  gate: Promise<void>,
  onResponse: (status: number) => void,
  onObserved: () => void,
): Promise<void> {
  const liveResponse = await route.fetch();
  onResponse(liveResponse.status());
  onObserved();
  await gate;
  await route.fulfill({ response: liveResponse });
}

async function installProductionMutationGuard(page: Page): Promise<string[]> {
  const blocked: string[] = [];
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    if (["GET", "HEAD", "OPTIONS"].includes(request.method())) {
      await route.fallback();
      return;
    }
    blocked.push(`${request.method()} ${new URL(request.url()).pathname}`);
    await route.abort("blockedbyclient");
  });
  return blocked;
}

async function installSafeBillingGetStubs(
  page: Page,
  options: {
    heldPath?: string;
    gate?: Promise<void>;
    onObserved?: () => void;
  } = {},
): Promise<string[]> {
  const blocked: string[] = [];
  await page.route("**/api/billing/**", async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname.replace(/\/$/, "");
    if (request.method() !== "GET") {
      blocked.push(`${request.method()} ${pathname}`);
      await route.abort("blockedbyclient");
      return;
    }
    const body = SAFE_BILLING_RESPONSES[pathname];
    if (body === undefined) {
      blocked.push(`UNSTUBBED GET ${pathname}`);
      await route.abort("blockedbyclient");
      return;
    }
    if (pathname === options.heldPath) {
      options.onObserved?.();
      await options.gate;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      json: body,
    });
  });
  return blocked;
}

function acknowledgementLabel(row: CoverageRow): string {
  const docket = row.docket_identifier
    ? `${row.docket_title} (${row.docket_identifier})`
    : row.docket_title;
  const deadline = row.deadline_title?.trim() || "Untitled deadline";
  const due = row.due_on
    ? `due ${new Intl.DateTimeFormat("en-IN", {
        day: "numeric",
        month: "short",
        year: "numeric",
      }).format(new Date(`${row.due_on}T00:00:00`))}`
    : "no due date recorded";
  return `${docket} · ${deadline} · ${due}`;
}

test.describe("Ram 2026-08-16 PR #237 production-safe UX proof", () => {
  test.setTimeout(360_000);

  test.beforeAll(async ({ request }) => {
    if (!LOCAL_BOOTSTRAP) return;
    const response = await request.post(
      `${PROD_API_BASE_URL}/api/bootstrap/company`,
      {
        data: {
          company_name: "PR 237 UX Proof LLP",
          company_slug: COMPANY_SLUG,
          company_type: "law_firm",
          owner_full_name: "PR 237 Proof Owner",
          owner_email: TESTER_EMAIL,
          owner_password: LOCAL_PASSWORD,
        },
      },
    );
    expect(
      [200, 409],
      `bootstrap local UX tenant: ${JSON.stringify(await responseBody(response))}`,
    ).toContain(response.status());
  });

  test.beforeEach(async ({ page }) => {
    await assertExactRelease(page);
  });

  test("every capability-visible grouped action remains reachable and clickable at 360px", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 360, height: 800 });
    const auth = await signIn(page);
    const unexpectedMutations = await installProductionMutationGuard(page);
    const unsafeBillingRequests = await installSafeBillingGetStubs(page);
    await page.goto(`${PROD_BASE_URL}/app`);

    await expect(
      page.locator('aside[aria-label="Primary navigation"]'),
    ).toBeHidden();
    const trigger = page.getByTestId("mobile-nav-trigger");
    await expect(trigger).toBeVisible();
    await trigger.click();
    const drawer = page.getByRole("dialog", { name: /workspace navigation/i });
    await expect(drawer).toBeVisible();

    const actualGroups = await drawer.locator("nav").evaluate((nav) =>
      Array.from(nav.children).flatMap((group) => {
        const links = Array.from(group.querySelectorAll("ul a[href]"));
        if (links.length === 0) return [];
        return [
          {
            label: group.firstElementChild?.textContent?.trim() ?? "",
            items: links.map((link) => ({
              label: link.getAttribute("aria-label") ?? "",
              href: link.getAttribute("href") ?? "",
            })),
          },
        ];
      }),
    );
    const expected = expectedGroups(auth.capabilities);
    expect(actualGroups).toEqual(expected);

    const actions = expected.flatMap((group) =>
      group.items.map((item) => ({ ...item, group: group.label })),
    );
    expect(actions.at(-1)).toEqual({
      group: "Workspace",
      label: "User guide",
      href: "/guide",
    });

    for (const action of actions) {
      if (!(await drawer.isVisible())) {
        await expect(trigger).toBeVisible();
        await trigger.click();
        await expect(drawer).toBeVisible();
      }
      const groupHeading = drawer.getByText(action.group, { exact: true });
      await groupHeading.scrollIntoViewIfNeeded();
      await expect(groupHeading).toBeVisible();
      const group = groupHeading.locator("..");
      const link = group.getByRole("link", {
        name: action.label,
        exact: true,
      });
      await link.scrollIntoViewIfNeeded();
      await expect(link).toBeVisible();
      await link.click({ trial: true });

      const box = await link.boundingBox();
      expect(box, `${action.label} must render a click target`).not.toBeNull();
      expect(box!.height, `${action.label} click target height`).toBeGreaterThanOrEqual(32);
      expect(box!.x, `${action.label} must not overflow left`).toBeGreaterThanOrEqual(0);
      expect(
        box!.x + box!.width,
        `${action.label} must not overflow right`,
      ).toBeLessThanOrEqual(361);
      const navWidth = await drawer.locator("nav").evaluate((node) => ({
        clientWidth: node.clientWidth,
        scrollWidth: node.scrollWidth,
      }));
      expect(navWidth.scrollWidth).toBeLessThanOrEqual(navWidth.clientWidth + 1);

      await link.click();
      await expect(drawer).toBeHidden();
      const expectedPath = new URL(action.href, PROD_BASE_URL).pathname;
      await expect
        .poll(() => new URL(page.url()).pathname, {
          message: `${action.label} must navigate to ${expectedPath}`,
        })
        .toBe(expectedPath);
      await expect(page.locator("h1").first()).toBeVisible();
    }
    expect(unexpectedMutations, "navigation must not issue API writes").toEqual([]);
    expect(unsafeBillingRequests, "every billing request must use a safe GET fixture").toEqual(
      [],
    );
  });

  test("manager selection shows live colleagues by name and email without exposing UUIDs", async ({
    page,
  }) => {
    const auth = await signIn(page);
    expectCapabilities(auth, ["workspace:admin"]);
    const directoryResponse = await page.request.get(
      `${PROD_API_BASE_URL}/api/companies/current/users`,
    );
    await expectStatus(directoryResponse, 200, "read tenant colleague directory");
    const directory = (await directoryResponse.json()) as CompanyUsersResponse;
    expect(directory.company_slug).toBe(COMPANY_SLUG);
    const activeUsers = directory.users
      .filter((user) => user.membership_active && user.user_active)
      .sort(
        (left, right) =>
          left.full_name.localeCompare(right.full_name) ||
          left.email.localeCompare(right.email),
      );
    expect(
      activeUsers.length,
      "The QA tenant needs at least one active directory member.",
    ).toBeGreaterThan(0);

    await page.goto(`${PROD_BASE_URL}/app/admin/employees`);
    await expect(
      page.getByRole("heading", { name: "Employee directory" }),
    ).toBeVisible();
    await page.getByTestId("new-employee-trigger").first().click();
    const dialog = page.getByRole("dialog", { name: "Add employee" });
    await expect(dialog).toBeVisible();
    const manager = dialog.getByLabel("Manager", { exact: true });
    await expect(manager).toBeEnabled();

    const options = await manager.locator("option").evaluateAll((nodes) =>
      nodes.map((node) => ({
        value: (node as HTMLOptionElement).value,
        text: node.textContent?.trim() ?? "",
      })),
    );
    for (const user of activeUsers) {
      expect(options).toContainEqual({
        value: user.membership_id,
        text: `${user.full_name} — ${user.email}`,
      });
    }
    for (const option of options.filter((row) => row.value)) {
      expect(option.text).not.toContain(option.value);
    }
    await dialog.getByRole("button", { name: "Cancel" }).click();
    await expect(dialog).toBeHidden();
  });

  test("billing overview loading is announced and suppresses premature empty states", async ({
    page,
  }) => {
    const auth = await signIn(page);
    expectCapabilities(auth, ["workspace:admin"]);

    const invoiceGate = deferred();
    const invoiceObserved = observedRequest();
    const unexpectedMutations = await installProductionMutationGuard(page);
    const unsafeBillingRequests = await installSafeBillingGetStubs(page, {
      heldPath: "/api/billing/invoices",
      gate: invoiceGate.promise,
      onObserved: invoiceObserved.observed,
    });
    try {
      await page.goto(`${PROD_BASE_URL}/app/admin/billing`);
      await invoiceObserved.promise;
      const loading = page.getByTestId("billing-page-loading");
      await expect(loading).toBeVisible();
      await expect(loading).toHaveAttribute("role", "status");
      await expect(loading).toHaveAttribute("aria-live", "polite");
      await expect(loading).toHaveAttribute("aria-busy", "true");
      await expect(loading).toContainText(
        "Loading plan, usage, invoices, and credits.",
      );
      await expect(page.getByText("No SaaS invoices yet.")).toHaveCount(0);
      await expect(page.getByText("No credit activity yet.")).toHaveCount(0);
    } finally {
      invoiceGate.release();
    }
    await expect(page.getByTestId("billing-page-loading")).toBeHidden();
    await expect(
      page.getByRole("heading", { name: "Invoices and downloads" }),
    ).toBeVisible();
    expect(unexpectedMutations).toEqual([]);
    expect(unsafeBillingRequests).toEqual([]);
  });

  test("usage-report loading is announced and suppresses premature empty tables", async ({
    page,
  }) => {
    const auth = await signIn(page);
    expectCapabilities(auth, ["workspace:admin"]);
    const spendGate = deferred();
    const spendObserved = observedRequest();
    const unexpectedMutations = await installProductionMutationGuard(page);
    const unsafeBillingRequests = await installSafeBillingGetStubs(page, {
      heldPath: "/api/billing/reports/spend",
      gate: spendGate.promise,
      onObserved: spendObserved.observed,
    });
    try {
      await page.goto(`${PROD_BASE_URL}/app/admin/billing/usage`);
      await spendObserved.promise;
      const loading = page.getByTestId("billing-usage-loading");
      await expect(loading).toBeVisible();
      await expect(loading).toHaveAttribute("role", "status");
      await expect(loading).toHaveAttribute("aria-live", "polite");
      await expect(loading).toHaveAttribute("aria-busy", "true");
      await expect(loading).toContainText("Loading usage and spend report.");
      await expect(page.getByText("No usage in this period.")).toHaveCount(0);
      await expect(page.getByText("No active quota warnings.")).toHaveCount(0);
    } finally {
      spendGate.release();
    }
    await expect(page.getByTestId("billing-usage-loading")).toBeHidden();
    await expect(
      page.getByRole("heading", { name: "Usage and spend report" }),
    ).toBeVisible();
    expect(unexpectedMutations).toEqual([]);
    expect(unsafeBillingRequests).toEqual([]);
  });

  test("IP deadline loading states are announced before live empty results can render", async ({
    page,
  }) => {
    const auth = await signIn(page);
    expectCapabilities(auth, ["ip:read", "ip:write"]);

    const gate = deferred();
    const docketObserved = observedRequest();
    const mineObserved = observedRequest();
    const queuesObserved = observedRequest();
    const unexpectedMutations = await installProductionMutationGuard(page);
    let docketStatus: number | undefined;
    let mineStatus: number | undefined;
    let queuesStatus: number | undefined;
    await page.route("**/api/ip/daily-docket**", (route) =>
      delayedPassThrough(
        route,
        gate.promise,
        (status) => {
          docketStatus = status;
        },
        docketObserved.observed,
      ),
    );
    await page.route("**/api/ip/deadline-coverages/mine**", (route) =>
      delayedPassThrough(
        route,
        gate.promise,
        (status) => {
          mineStatus = status;
        },
        mineObserved.observed,
      ),
    );
    await page.route("**/api/ip/docket-queues**", (route) =>
      delayedPassThrough(
        route,
        gate.promise,
        (status) => {
          queuesStatus = status;
        },
        queuesObserved.observed,
      ),
    );
    try {
      await page.goto(`${PROD_BASE_URL}/app/ip/docket`);
      await Promise.all([
        docketObserved.promise,
        mineObserved.promise,
        queuesObserved.promise,
      ]);
      const capacity = page.getByTestId("ip-docket-capacity-loading");
      const escalations = page.getByTestId("ip-docket-escalations-loading");
      const acknowledgements = page.getByTestId(
        "ip-docket-acknowledgements-loading",
      );
      const savedQueues = page.getByTestId("ip-docket-saved-queues-loading");
      for (const loading of [
        capacity,
        escalations,
        acknowledgements,
        savedQueues,
      ]) {
        await expect(loading).toBeVisible();
        await expect(loading).toHaveAttribute("role", "status");
        await expect(loading).toHaveAttribute("aria-live", "polite");
        await expect(loading).toHaveAttribute("aria-busy", "true");
      }
      await expect(capacity).toContainText("Loading workload and capacity.");
      await expect(escalations).toContainText("Loading deadline escalations.");
      await expect(acknowledgements).toContainText(
        "Loading your unacknowledged deadlines.",
      );
      await expect(savedQueues).toContainText("Loading saved queues.");
      await expect(
        page.getByText(/No deadline coverage is assigned in this view\./),
      ).toHaveCount(0);
      await expect(page.getByText(/Nothing is escalating\./)).toHaveCount(0);
      await expect(
        page.getByText(/You have acknowledged every deadline you hold\./),
      ).toHaveCount(0);
      await expect(page.getByText(/No saved queues yet\./)).toHaveCount(0);
    } finally {
      gate.release();
    }
    expect(docketStatus).toBe(200);
    expect(mineStatus).toBe(200);
    expect(queuesStatus).toBe(200);
    await expect(page.getByTestId("ip-docket-capacity-loading")).toBeHidden();
    await expect(
      page.getByTestId("ip-docket-escalations-loading"),
    ).toBeHidden();
    await expect(
      page.getByTestId("ip-docket-acknowledgements-loading"),
    ).toBeHidden();
    await expect(page.getByTestId("ip-docket-saved-queues-loading")).toBeHidden();
    expect(unexpectedMutations).toEqual([]);
  });

  test("a partial acknowledgement keeps the selected human label after the stubbed row disappears", async ({
    page,
  }) => {
    const auth = await signIn(page);
    expectCapabilities(auth, ["ip:read", "ip:write"]);

    const unexpectedMutations = await installProductionMutationGuard(page);
    let reads = 0;
    let removeSelectedOnRefetch = false;
    await page.route("**/api/ip/deadline-coverages/mine**", async (route) => {
      reads += 1;
      const delivered: CoverageResponse = {
        coverages: removeSelectedOnRefetch ? [] : [SAFE_ACK_COVERAGE],
      };
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        json: delivered,
      });
    });

    let postCalls = 0;
    let postBody: {
      coverage_ids?: string[];
      expected_versions?: Record<string, number>;
    } = {};
    await page.route(
      "**/api/ip/deadline-coverages/bulk-acknowledge",
      async (route) => {
        postCalls += 1;
        postBody = route.request().postDataJSON();
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          json: {
            acknowledged_count: 0,
            rejected_count: 1,
            outcomes: [
              {
                coverage_id: SAFE_ACK_COVERAGE.coverage_id,
                acknowledged: false,
                reason: "version_conflict",
                reassignment_version: SAFE_ACK_COVERAGE.reassignment_version + 1,
              },
            ],
          },
        });
      },
    );

    await page.goto(`${PROD_BASE_URL}/app/ip/docket`);
    const row = page.getByTestId(
      `ip-docket-ack-${SAFE_ACK_COVERAGE.coverage_id}`,
    );
    await expect(row).toBeVisible();
    await row.getByRole("checkbox").check();
    const frozenLabel = acknowledgementLabel(SAFE_ACK_COVERAGE);
    removeSelectedOnRefetch = true;
    await page.getByRole("button", { name: "Acknowledge selected" }).click();

    await expect.poll(() => postCalls).toBe(1);
    expect(postBody).toEqual({
      coverage_ids: [SAFE_ACK_COVERAGE.coverage_id],
      expected_versions: {
        [SAFE_ACK_COVERAGE.coverage_id]: SAFE_ACK_COVERAGE.reassignment_version,
      },
    });
    await expect.poll(() => reads).toBeGreaterThanOrEqual(2);
    await expect(row).toHaveCount(0);
    const rejected = page.getByTestId("ip-docket-ack-rejected");
    await expect(rejected).toBeVisible();
    await expect(rejected).toContainText(frozenLabel);
    await expect(rejected).toContainText("Changed since you loaded this page");
    await expect(rejected).not.toContainText(SAFE_ACK_COVERAGE.coverage_id);
    expect(unexpectedMutations).toEqual([]);
  });
});
