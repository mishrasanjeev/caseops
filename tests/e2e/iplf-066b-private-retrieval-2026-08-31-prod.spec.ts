/** IPLF-066B exact-release production acceptance for private revocation. */

import { expect, test, type APIRequestContext } from "@playwright/test";

import { expectStatus } from "./support/iplf058b";
import {
  selectPrivateReleaseFixture,
  verifyRetainedPrivateRevocation,
} from "./support/private-release-fixtures";

const WEB = (process.env.PROD_BASE_URL ?? "https://caseops.ai").trim();
const API = (process.env.PROD_API_BASE_URL ?? "https://api.caseops.ai").trim();
const SLUG = (process.env.CASEOPS_IP_QA_SLUG ?? "caseops-ip-qa").trim();
const EMAIL = (
  process.env.CASEOPS_IP_QA_EMAIL ?? "ip-qa-bot@caseops.ai"
).trim();

type MatterRecord = {
  id: string;
  matter_code: string;
  title: string;
  status: "intake" | "active" | "on_hold" | "disposed";
  updated_at: string;
};

type TenantPolicy = {
  policy_version: number;
  workspace_assistant_enabled: boolean;
  assistant_retention_days: number;
  allowed_models_assistant: string[];
};

type CleanupState = {
  headers: { Authorization: string };
  matter: MatterRecord;
  originalPolicy: TenantPolicy;
  enabledPolicy: TenantPolicy;
};

let cleanupState: CleanupState | undefined;

function required(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required.`);
  return value;
}

function sameStringSet(left: string[], right: string[]): boolean {
  return [...left].sort().join("\u0000") === [...right].sort().join("\u0000");
}

function samePolicy(left: TenantPolicy, right: TenantPolicy): boolean {
  return (
    left.workspace_assistant_enabled === right.workspace_assistant_enabled &&
    left.assistant_retention_days === right.assistant_retention_days &&
    sameStringSet(left.allowed_models_assistant, right.allowed_models_assistant)
  );
}

async function disposeFixture(
  api: APIRequestContext,
  state: CleanupState,
): Promise<void> {
  const response = await api.get(`${API}/api/matters/${state.matter.id}`, {
    headers: state.headers,
    timeout: 10_000,
  });
  await expectStatus(
    response,
    200,
    "read private retrieval fixture for cleanup",
  );
  const current: MatterRecord = await response.json();
  expect(current.matter_code).toBe(state.matter.matter_code);
  if (current.status === "disposed") return;
  const disposed = await api.patch(
    `${API}/api/matters/${current.id}/lifecycle/status`,
    {
      headers: state.headers,
      timeout: 10_000,
      data: {
        to_status: "disposed",
        expected_from_status: current.status,
        expected_updated_at: current.updated_at,
        reason: "Dispose the exact-release IPLF-066B synthetic QA fixture.",
      },
    },
  );
  await expectStatus(disposed, 200, "dispose private retrieval fixture");
  expect(((await disposed.json()) as MatterRecord).status).toBe("disposed");
}

async function restorePolicy(
  api: APIRequestContext,
  state: CleanupState,
): Promise<void> {
  const response = await api.get(`${API}/api/admin/tenant-ai-policy`, {
    headers: state.headers,
    timeout: 10_000,
  });
  await expectStatus(
    response,
    200,
    "read private retrieval policy for cleanup",
  );
  const current: TenantPolicy = await response.json();
  if (samePolicy(current, state.originalPolicy)) return;
  expect(
    samePolicy(current, state.enabledPolicy),
    "cleanup refuses to overwrite a concurrently changed tenant AI policy",
  ).toBe(true);
  const restored = await api.patch(`${API}/api/admin/tenant-ai-policy`, {
    headers: state.headers,
    timeout: 10_000,
    data: {
      expected_version: current.policy_version,
      workspace_assistant_enabled:
        state.originalPolicy.workspace_assistant_enabled,
      assistant_retention_days: state.originalPolicy.assistant_retention_days,
      allowed_models_assistant: state.originalPolicy.allowed_models_assistant,
    },
  });
  await expectStatus(restored, 200, "restore private retrieval tenant policy");
}

test.afterEach(async ({ request }, testInfo) => {
  const state = cleanupState;
  cleanupState = undefined;
  if (!state) return;
  testInfo.setTimeout(90_000);
  const failures: string[] = [];
  for (const [name, cleanup] of [
    ["matter", disposeFixture],
    ["tenant_policy", restorePolicy],
  ] as const) {
    try {
      await cleanup(request, state);
    } catch (error) {
      console.error(`[IPLF-066B] cleanup failed; phase=${name}`, error);
      failures.push(name);
    }
  }
  if (failures.length) {
    throw new Error(
      `IPLF-066B production cleanup failed: ${failures.join(", ")}`,
    );
  }
});

test("IPLF-066B production revokes private answers, citations and retrieval", async ({
  page,
}) => {
  test.setTimeout(300_000);
  const expectedSha = required("CASEOPS_EXPECTED_RELEASE_SHA");
  const releaseKey = expectedSha.slice(0, 12);
  const matterCodePrefix = `IPLF-066B-${releaseKey.toUpperCase()}`;
  const [apiIdentity, webIdentity] = await Promise.all([
    page.request.get(`${API}/api/build`),
    page.request.get(`${WEB}/api/release-identity`),
  ]);
  await expectStatus(apiIdentity, 200, "API release identity");
  await expectStatus(webIdentity, 200, "web release identity");
  expect((await apiIdentity.json()).release_sha).toBe(expectedSha);
  expect((await webIdentity.json()).release_sha).toBe(expectedSha);

  const login = await page.request.post(`${API}/api/auth/login`, {
    data: {
      company_slug: SLUG,
      email: EMAIL,
      password: required("CASEOPS_IP_QA_PASSWORD"),
    },
  });
  await expectStatus(login, 200, "IP QA sign-in");
  const identity = await login.json();
  const headers = { Authorization: `Bearer ${identity.access_token}` };

  const mattersResponse = await page.request.get(`${API}/api/matters/`, {
    headers,
    params: { q: matterCodePrefix, status: "active", limit: 10 },
  });
  await expectStatus(
    mattersResponse,
    200,
    "find exact private retrieval fixture",
  );
  let candidates = (await mattersResponse.json()).matters as MatterRecord[];
  if (candidates.length === 0) {
    const retired = await page.request.get(`${API}/api/matters/`, {
      headers,
      params: { q: matterCodePrefix, status: "disposed", limit: 100 },
    });
    await expectStatus(retired, 200, "find retired exact-release fixture");
    candidates = (await retired.json()).matters as MatterRecord[];
    expect(candidates.length, "fixture scan must remain bounded").toBeLessThan(100);
  }
  const matter = selectPrivateReleaseFixture(candidates, matterCodePrefix);
  const fixtureKey = matter.matter_code
    .slice("IPLF-066B-".length)
    .toLowerCase();
  const filename = `iplf-066b-${fixtureKey}-private-evidence.txt`;
  const evidenceToken = `Aurora-${fixtureKey}`;

  const originalPolicyResponse = await page.request.get(
    `${API}/api/admin/tenant-ai-policy`,
    { headers },
  );
  await expectStatus(
    originalPolicyResponse,
    200,
    "read production assistant policy",
  );
  const originalPolicy: TenantPolicy = await originalPolicyResponse.json();
  const enabledResponse = await page.request.patch(
    `${API}/api/admin/tenant-ai-policy`,
    {
      headers,
      data: {
        expected_version: originalPolicy.policy_version,
        workspace_assistant_enabled: true,
        assistant_retention_days: originalPolicy.assistant_retention_days,
        allowed_models_assistant: [],
      },
    },
  );
  await expectStatus(
    enabledResponse,
    200,
    "enable production private retrieval",
  );
  const enabledPolicy: TenantPolicy = await enabledResponse.json();
  cleanupState = { headers, matter, originalPolicy, enabledPolicy };

  await page.goto(WEB);
  await page.evaluate(
    (context) => window.localStorage.setItem("caseops.session.context", JSON.stringify(context)),
    {
      company: identity.company,
      user: identity.user,
      membership: identity.membership,
      capabilities: identity.capabilities,
    },
  );
  if (matter.status === "disposed") {
    await verifyRetainedPrivateRevocation(page, {
      api: API, web: WEB, headers, matter, filename, evidenceToken,
    });
    console.log("[IPLF-066B] verified retained revocation without reopening the terminal fixture.");
    return;
  }

  const before = await page.request.post(
    `${API}/api/private-retrieval/search`,
    {
      headers,
      data: {
        query: evidenceToken,
        source_types: ["matter_document"],
        scope_ids: { matter: [matter.id] },
        limit: 10,
      },
    },
  );
  await expectStatus(before, 200, "search current private projection");
  const beforeItems = (await before.json()).items as Array<{
    source_id: string;
    label: string;
    content: string;
  }>;
  expect(beforeItems).toHaveLength(1);
  expect(beforeItems[0].label).toBe(filename);
  expect(beforeItems[0].content).toContain(evidenceToken);

  await page.goto(`${WEB}/app/assistant`);
  await page
    .getByRole("textbox", { name: "Find workspace records" })
    .fill(filename);
  await page.getByRole("button", { name: "Find permitted records" }).click();
  await page.getByRole("button", { name: `Add ${filename}` }).click();
  await page.getByRole("button", { name: "Start conversation" }).click();
  await page
    .getByRole("textbox", { name: "Ask this workspace" })
    .fill(`What does the evidence say about ${evidenceToken}?`);
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  await expect(page.getByTestId("assistant-turns")).toContainText(
    evidenceToken,
  );
  await expect(page.getByRole("link", { name: filename })).toBeVisible();
  await expect(page.getByTestId("assistant-turns")).not.toContainText(
    "Ignore previous instructions",
  );

  await disposeFixture(page.request, cleanupState);
  await page.reload();
  await page
    .getByRole("button", { name: `Ask \u00b7 ${filename}`, exact: true })
    .click();
  await expect(page.getByTestId("assistant-turns")).toContainText(
    "This answer is hidden because access to one or more cited workspace records changed.",
  );
  await expect(
    page.locator('[data-turn-role="assistant"]').last(),
  ).not.toContainText(evidenceToken);
  await expect(page.getByRole("link", { name: filename })).toHaveCount(0);

  const after = await page.request.post(`${API}/api/private-retrieval/search`, {
    headers,
    data: {
      query: evidenceToken,
      source_types: ["matter_document"],
      scope_ids: { matter: [matter.id] },
      limit: 10,
    },
  });
  await expectStatus(after, 200, "search after private revocation");
  expect((await after.json()).items).toEqual([]);

  await page.setViewportSize({ width: 360, height: 800 });
  await expect(
    page.getByRole("textbox", { name: "Ask this workspace" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth >
        document.documentElement.clientWidth + 1,
    ),
  ).toBe(false);
});
