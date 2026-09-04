import { spawnSync } from "node:child_process";

import {
  expect,
  request as playwrightRequest,
  test,
  type APIRequestContext,
  type Page,
} from "@playwright/test";

import { noPaidProviderHeaders } from "./support/cost-controls";
import { repoRoot } from "./support/env";
import { plusDays } from "./support/helpers";

const envOr = (key: string, fallback: string): string =>
  (process.env[key] ?? "").trim() || fallback;
const BASE_URL = envOr(
  "PROD_BASE_URL",
  envOr("CASEOPS_WEB_BASE_URL", "http://127.0.0.1:3100"),
);
const IS_LOCAL = ["127.0.0.1", "localhost"].includes(
  new URL(BASE_URL).hostname,
);
const HAS_DOCKER_POLL = Boolean(
  envOr("CASEOPS_E2E_DOCKER_PROJECT", "") &&
    envOr("CASEOPS_E2E_DOCKER_COMPOSE_FILE", ""),
);
const API_BASE_URL = envOr(
  "PROD_API_BASE_URL",
  IS_LOCAL
    ? `http://127.0.0.1:${envOr("CASEOPS_E2E_API_PORT", "8000")}`
    : "https://api.caseops.ai",
);
const RUN_ID = `${Date.now().toString(36)}-${Math.random()
  .toString(36)
  .slice(2, 8)}`.toLowerCase();
const COMPANY_SLUG = envOr(
  "CASEOPS_RAM_PROD_SLUG",
  IS_LOCAL ? `ram-sep04-${RUN_ID}` : "legal",
);
const TESTER_EMAIL = envOr(
  "CASEOPS_RAM_PROD_EMAIL",
  IS_LOCAL ? `ram-sep04-${RUN_ID}@example.com` : "hari.gupta@gmail.com",
);
const LOCAL_PASSWORD = "RamSep04Local!";

type Identity = {
  access_token: string;
};

type Matter = {
  id: string;
  matter_code: string;
  status: string;
  is_active: boolean;
  lifecycle_version: number;
  updated_at: string;
  next_hearing_on: string | null;
};

let api: APIRequestContext;
let identity: Identity;

function password(): string {
  const value = envOr(
    "CASEOPS_RAM_PROD_PASSWORD",
    envOr("CASEOPS_RAM_LOCAL_PASSWORD", IS_LOCAL ? LOCAL_PASSWORD : ""),
  );
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
  expect(response.status(), `${label}: ${await response.text()}`).toBe(
    expected,
  );
}

async function signIn(page: Page): Promise<void> {
  await page.goto(`${BASE_URL}/sign-in`);
  await page.locator("#company-slug").fill(COMPANY_SLUG);
  await page.locator("#email").fill(TESTER_EMAIL);
  await page.locator("#password").fill(password());
  const login = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/api/auth/login" &&
      response.request().method() === "POST",
  );
  await page.locator('button[type="submit"]').click();
  const response = await login;
  await expectStatus(response, 200, "sign in");
  identity = (await response.json()) as Identity;
  await page.waitForURL(/\/app(?:[/?]|$)/);
}

function runDockerPoll(): void {
  const project = envOr("CASEOPS_E2E_DOCKER_PROJECT", "");
  const composeFile = envOr("CASEOPS_E2E_DOCKER_COMPOSE_FILE", "");
  if (!project || !composeFile) {
    throw new Error(
      "Docker project and compose file are required for the local poll.",
    );
  }
  const result = spawnSync(
    "docker",
    [
      "compose",
      "--project-name",
      project,
      "--file",
      composeFile,
      "exec",
      "-T",
      "api",
      "caseops-poll-tracked-cases",
      "--force",
    ],
    { cwd: repoRoot, encoding: "utf8", timeout: 120_000 },
  );
  if (result.status !== 0) {
    throw new Error(
      `Case-tracking poll failed (${result.status}).\n${result.stdout}\n${result.stderr}`,
    );
  }
}

test.describe.serial("Ram 2026-09-04 automatic next-hearing sync", () => {
  test.setTimeout(240_000);

  test.beforeAll(async () => {
    api = await playwrightRequest.newContext({
      extraHTTPHeaders: noPaidProviderHeaders,
    });
    if (IS_LOCAL) {
      const bootstrap = await api.post(
        `${API_BASE_URL}/api/bootstrap/company`,
        {
          data: {
            company_name: `Automatic Hearing ${RUN_ID}`,
            company_slug: COMPANY_SLUG,
            company_type: "law_firm",
            owner_full_name: "Automatic Hearing Owner",
            owner_email: TESTER_EMAIL,
            owner_password: LOCAL_PASSWORD,
          },
        },
      );
      await expectStatus(bootstrap, 200, "local tenant bootstrap");
      identity = (await bootstrap.json()) as Identity;
    }
  });

  test.afterAll(async () => {
    await api.dispose();
  });

  test("older eligible matter is linked and updated by the Docker poll without lifecycle mutation", async ({
    page,
  }) => {
    test.skip(
      !HAS_DOCKER_POLL,
      "The paid-call-free behavioral proof requires the Docker provider emulator.",
    );
    const matterCode = `NHD-${RUN_ID}`.toUpperCase().slice(0, 78);
    const create = await api.post(`${API_BASE_URL}/api/matters/`, {
      headers: headers(),
      data: {
        title: `Automatic next hearing ${RUN_ID}`,
        matter_code: matterCode,
        practice_area: "litigation",
        forum_level: "high_court",
        court_name: "Delhi High Court",
        client_name: "Local Docker Petitioner",
        opposing_party: "Local Docker Respondent",
        next_hearing_on: plusDays(2),
        status: "active",
      },
    });
    await expectStatus(create, 200, "create pre-existing matter");
    const original = (await create.json()) as Matter;

    const addIdentity = await api.patch(
      `${API_BASE_URL}/api/matters/${original.id}`,
      {
        headers: headers(),
        data: {
          case_number: "WP(C) 9123/2026",
          cnr_number: "DLHC010091232026",
          expected_updated_at: original.updated_at,
        },
      },
    );
    await expectStatus(addIdentity, 200, "add reliable court identity");
    const before = (await addIdentity.json()) as Matter;

    const beforeBookmarks = await api.get(
      `${API_BASE_URL}/api/case-tracking/bookmarks`,
      { headers: headers() },
    );
    await expectStatus(beforeBookmarks, 200, "bookmarks before backfill");
    expect((await beforeBookmarks.json()).bookmarks).toHaveLength(0);

    runDockerPoll();

    const read = await api.get(`${API_BASE_URL}/api/matters/${original.id}`, {
      headers: headers(),
    });
    await expectStatus(read, 200, "matter after automatic poll");
    const after = (await read.json()) as Matter;
    expect(after.next_hearing_on).toBe(plusDays(21));
    expect(after.status).toBe("active");
    expect(after.is_active).toBe(true);
    expect(after.lifecycle_version).toBe(before.lifecycle_version);

    const bookmarks = await api.get(
      `${API_BASE_URL}/api/case-tracking/bookmarks`,
      {
        headers: headers(),
      },
    );
    await expectStatus(bookmarks, 200, "bookmarks after backfill");
    const rows = (await bookmarks.json()).bookmarks as Array<{
      id: string;
      matter_id: string;
      tracked_case: { next_hearing_on: string | null };
    }>;
    expect(rows).toHaveLength(1);
    expect(rows[0].matter_id).toBe(original.id);
    expect(rows[0].tracked_case.next_hearing_on).toBe(plusDays(21));

    await signIn(page);
    await page.goto(`${BASE_URL}/app/matters`);
    await page.locator("#matter-filter-q").fill(matterCode);
    await page.getByRole("button", { name: /Apply/i }).click();
    await expect(page.getByText(matterCode)).toBeVisible();
    await expect(page.getByText(/Next hearing/i).first()).toBeVisible();

    await page.goto(`${BASE_URL}/app/case-tracking`);
    const bookmark = page.getByTestId(`case-tracking-bookmark-${rows[0].id}`);
    await expect(bookmark).toBeVisible();
    const refreshed = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname ===
          `/api/case-tracking/bookmarks/${rows[0].id}/refresh` &&
        response.request().method() === "POST",
    );
    await bookmark.getByRole("button", { name: /^Refresh$/ }).click();
    await expectStatus(
      await refreshed,
      200,
      "manual Sync Now through Docker emulator",
    );

    const finalRead = await api.get(
      `${API_BASE_URL}/api/matters/${original.id}`,
      {
        headers: headers(),
      },
    );
    const finalMatter = (await finalRead.json()) as Matter;
    expect(finalMatter.next_hearing_on).toBe(after.next_hearing_on);
    expect(finalMatter.lifecycle_version).toBe(after.lifecycle_version);
  });

  test("production surface is exact-release ready and regular verification spends zero provider credits", async ({
    page,
  }) => {
    test.skip(
      IS_LOCAL,
      "Production-only exact-release and paid-provider isolation proof.",
    );
    await signIn(page);

    const status = await page.request.get(
      `${API_BASE_URL}/api/case-tracking/status`,
      {
        headers: headers(),
      },
    );
    await expectStatus(status, 200, "case-tracking status");
    expect((await status.json()).configured).toBe(true);

    await page.goto(`${BASE_URL}/app/matters`);
    await expect(page.getByText(/Next hearing/i).first()).toBeVisible();
    await page.goto(`${BASE_URL}/app/case-tracking`);
    await expect(page.getByTestId("case-tracking-search")).toBeVisible();
    await expect(page.getByTestId("case-tracking-disabled")).toHaveCount(0);

    const blocked = await page.request.post(
      `${API_BASE_URL}/api/case-tracking/search`,
      {
        headers: headers(),
        data: { cnr_number: "DLHC010091232026" },
      },
    );
    await expectStatus(blocked, 409, "regular test paid-provider boundary");
    expect((await blocked.json()).code).toBe("paid_provider_blocked_for_test");

    const apiRelease = await page.request.get(
      `${API_BASE_URL}/api/build`,
    );
    const webRelease = await page.request.get(
      `${BASE_URL}/api/release-identity`,
    );
    await expectStatus(apiRelease, 200, "API release identity");
    await expectStatus(webRelease, 200, "web release identity");
    const expected = envOr("CASEOPS_EXPECTED_RELEASE_SHA", "");
    if (expected) {
      expect((await apiRelease.json()).release_sha).toBe(expected);
      expect((await webRelease.json()).release_sha).toBe(expected);
    }
  });
});
