/** IPLF-065B exact-release production acceptance for governed AI feedback. */

import { expect, test, type APIRequestContext } from "@playwright/test";

import { expectStatus } from "./support/iplf058b";

const WEB = (process.env.PROD_BASE_URL ?? "https://caseops.ai").trim();
const API = (process.env.PROD_API_BASE_URL ?? "https://api.caseops.ai").trim();
const SLUG = (process.env.CASEOPS_IP_QA_SLUG ?? "caseops-ip-qa").trim();
const EMAIL = (
  process.env.CASEOPS_IP_QA_EMAIL ?? "ip-qa-bot@caseops.ai"
).trim();
const CLEANUP_TIMEOUT_MS = 90_000;
const CLEANUP_REQUEST_TIMEOUT_MS = 10_000;

type FeedbackRecord = {
  id: string;
  submitted_by_membership_id: string;
  target_type: string;
  status: "open" | "in_review" | "resolved" | "dismissed";
  created_at: string;
  updated_at: string;
};

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
  startedAt: number;
  runId: string;
  membershipId: string;
  headers: { Authorization: string };
  feedbackIds: Set<string>;
  matter: MatterRecord | null;
  originalPolicy: TenantPolicy | null;
  enabledPolicy: TenantPolicy | null;
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

async function resolveCreatedFeedback(
  api: APIRequestContext,
  state: CleanupState,
) {
  const listed = await api.get(`${API}/api/admin/ai-feedback`, {
    headers: state.headers,
    params: { limit: 100 },
    timeout: CLEANUP_REQUEST_TIMEOUT_MS,
  });
  await expectStatus(listed, 200, "recover production feedback for cleanup");
  const body: { items: FeedbackRecord[]; has_more: boolean } =
    await listed.json();
  const records = body.items.filter(
    (record) =>
      state.feedbackIds.has(record.id) ||
      (record.submitted_by_membership_id === state.membershipId &&
        Date.parse(record.created_at) >= state.startedAt - 1_000 &&
        [
          "product_guide_command",
          "product_guide_no_match",
          "assistant_turn",
        ].includes(record.target_type)),
  );
  const recoveredIds = new Set(records.map((record) => record.id));
  for (const feedbackId of state.feedbackIds) {
    expect(
      recoveredIds.has(feedbackId),
      `cleanup could not recover production feedback ${feedbackId}`,
    ).toBe(true);
  }
  for (const record of records) {
    if (record.status === "resolved" || record.status === "dismissed") continue;
    const resolved = await api.patch(
      `${API}/api/admin/ai-feedback/${record.id}`,
      {
        headers: state.headers,
        timeout: CLEANUP_REQUEST_TIMEOUT_MS,
        data: {
          expected_updated_at: record.updated_at,
          status: "resolved",
          review_notes: "Closed after exact-release production acceptance.",
        },
      },
    );
    await expectStatus(
      resolved,
      200,
      `resolve production feedback ${record.id}`,
    );
  }
}

async function disposeCreatedMatter(
  api: APIRequestContext,
  state: CleanupState,
) {
  if (!state.matter) return;
  const currentResponse = await api.get(
    `${API}/api/matters/${state.matter.id}`,
    {
      headers: state.headers,
      timeout: CLEANUP_REQUEST_TIMEOUT_MS,
    },
  );
  await expectStatus(
    currentResponse,
    200,
    "read production feedback Matter for cleanup",
  );
  const current: MatterRecord = await currentResponse.json();
  expect(current.id).toBe(state.matter.id);
  expect(current.matter_code).toBe(state.matter.matter_code);
  expect(current.title).toBe(state.matter.title);
  if (current.status === "disposed") return;
  const disposed = await api.patch(
    `${API}/api/matters/${current.id}/lifecycle/status`,
    {
      headers: state.headers,
      timeout: CLEANUP_REQUEST_TIMEOUT_MS,
      data: {
        to_status: "disposed",
        expected_from_status: current.status,
        expected_updated_at: current.updated_at,
        reason: "Dispose the isolated IPLF-065B production acceptance fixture.",
      },
    },
  );
  await expectStatus(disposed, 200, "dispose production feedback Matter");
  expect(((await disposed.json()) as MatterRecord).status).toBe("disposed");
}

async function restoreTenantPolicy(
  api: APIRequestContext,
  state: CleanupState,
) {
  if (!state.originalPolicy || !state.enabledPolicy) return;
  const currentResponse = await api.get(`${API}/api/admin/tenant-ai-policy`, {
    headers: state.headers,
    timeout: CLEANUP_REQUEST_TIMEOUT_MS,
  });
  await expectStatus(
    currentResponse,
    200,
    "read production assistant policy for cleanup",
  );
  const current: TenantPolicy = await currentResponse.json();
  if (samePolicy(current, state.originalPolicy)) return;
  expect(
    samePolicy(current, state.enabledPolicy),
    "cleanup refuses to overwrite a concurrently changed tenant AI policy",
  ).toBe(true);
  const restored = await api.patch(`${API}/api/admin/tenant-ai-policy`, {
    headers: state.headers,
    timeout: CLEANUP_REQUEST_TIMEOUT_MS,
    data: {
      expected_version: current.policy_version,
      workspace_assistant_enabled:
        state.originalPolicy.workspace_assistant_enabled,
      assistant_retention_days: state.originalPolicy.assistant_retention_days,
      allowed_models_assistant: state.originalPolicy.allowed_models_assistant,
    },
  });
  await expectStatus(restored, 200, "restore production assistant policy");
  expect(samePolicy(await restored.json(), state.originalPolicy)).toBe(true);
}

test.afterEach(async ({ request }, testInfo) => {
  const state = cleanupState;
  cleanupState = undefined;
  if (!state) return;
  testInfo.setTimeout(CLEANUP_TIMEOUT_MS);
  const failures: string[] = [];
  for (const [name, cleanup] of [
    ["feedback", resolveCreatedFeedback],
    ["matter", disposeCreatedMatter],
    ["tenant_policy", restoreTenantPolicy],
  ] as const) {
    try {
      await cleanup(request, state);
    } catch (error) {
      console.error(`[IPLF-065B] cleanup failed; phase=${name}`, error);
      failures.push(name);
    }
  }
  if (failures.length) {
    throw new Error(
      `IPLF-065B production cleanup failed: ${failures.join(", ")}`,
    );
  }
});

test("IPLF-065B production proves exact feedback and review behavior", async ({
  page,
}) => {
  test.setTimeout(240_000);
  const expectedSha = required("CASEOPS_EXPECTED_RELEASE_SHA");
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
  const runId = `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  const state: CleanupState = {
    startedAt: Date.now(),
    runId,
    membershipId: identity.membership.id,
    headers,
    feedbackIds: new Set(),
    matter: null,
    originalPolicy: null,
    enabledPolicy: null,
  };
  cleanupState = state;

  const originalPolicyResponse = await page.request.get(
    `${API}/api/admin/tenant-ai-policy`,
    {
      headers,
    },
  );
  await expectStatus(
    originalPolicyResponse,
    200,
    "read production assistant policy",
  );
  state.originalPolicy = await originalPolicyResponse.json();
  const enabledResponse = await page.request.patch(
    `${API}/api/admin/tenant-ai-policy`,
    {
      headers,
      data: {
        expected_version: state.originalPolicy!.policy_version,
        workspace_assistant_enabled: true,
        assistant_retention_days:
          state.originalPolicy!.assistant_retention_days,
        allowed_models_assistant: [],
      },
    },
  );
  await expectStatus(
    enabledResponse,
    200,
    "enable production assistant feedback",
  );
  state.enabledPolicy = await enabledResponse.json();

  const matterResponse = await page.request.post(`${API}/api/matters/`, {
    headers,
    data: {
      matter_code: `AI-FEEDBACK-PROD-${runId}`,
      title: `Production AI feedback ${runId}`,
      practice_area: "Intellectual Property",
      forum_level: "high_court",
    },
  });
  await expectStatus(matterResponse, 200, "production feedback Matter");
  state.matter = await matterResponse.json();

  await page.goto(WEB, { waitUntil: "domcontentloaded", timeout: 30_000 });
  await page.evaluate(
    (context) =>
      window.localStorage.setItem(
        "caseops.session.context",
        JSON.stringify(context),
      ),
    {
      company: identity.company,
      user: identity.user,
      membership: identity.membership,
      capabilities: identity.capabilities,
    },
  );

  await page.goto(`${WEB}/guide`, {
    waitUntil: "load",
    timeout: 30_000,
  });
  const matchedSearch = await page.request.get(
    `${API}/api/product-guide/search`,
    {
      headers,
      params: { q: "deadline control", limit: 5 },
      timeout: 20_000,
    },
  );
  await expectStatus(matchedSearch, 200, "matched production guide search");
  expect((await matchedSearch.json()).status).toBe("matched");
  const search = page.getByRole("searchbox", {
    name: "Search the CaseOps guide",
  });
  await search.fill("deadline control");
  await page.getByRole("button", { name: "Search" }).click();
  const guideCommand = page.getByTestId(
    "product-guide-feedback-command-deadline-control",
  );
  await expect(guideCommand).toBeVisible({ timeout: 20_000 });
  const [guideRating] = await Promise.all([
    page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === "/api/ai-feedback/product-guide" &&
        response.request().method() === "POST",
      { timeout: 20_000 },
    ),
    guideCommand.getByRole("button", { name: "Mark as helpful" }).click(),
  ]);
  expect(guideRating.status()).toBe(201);
  const ratingRecord: FeedbackRecord = await guideRating.json();
  state.feedbackIds.add(ratingRecord.id);

  const noMatchSearch = await page.request.get(
    `${API}/api/product-guide/search`,
    {
      headers,
      params: { q: "xylophone nebula quasar", limit: 5 },
      timeout: 20_000,
    },
  );
  await expectStatus(noMatchSearch, 200, "no-match production guide search");
  expect((await noMatchSearch.json()).status).toBe("no_match");
  await search.fill("xylophone nebula quasar");
  await page.getByRole("button", { name: "Search" }).click();
  const noMatch = page.getByTestId("product-guide-feedback-no-match");
  await expect(noMatch).toBeVisible({ timeout: 10_000 });
  await noMatch.getByRole("button", { name: "Report an issue" }).click();
  await noMatch
    .getByLabel("Issue", { exact: true })
    .selectOption("missing_guidance");
  await noMatch
    .getByLabel("Note", { exact: true })
    .fill(`Production guide review ${runId}`);
  const [guideReport] = await Promise.all([
    page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === "/api/ai-feedback/product-guide" &&
        response.request().method() === "POST",
      { timeout: 20_000 },
    ),
    noMatch.getByRole("button", { name: "Submit report" }).click(),
  ]);
  expect(guideReport.status()).toBe(201);
  const reportRecord: FeedbackRecord = await guideReport.json();
  state.feedbackIds.add(reportRecord.id);

  await page.goto(`${WEB}/app/assistant`, {
    waitUntil: "load",
    timeout: 30_000,
  });
  await page
    .getByRole("textbox", { name: "Find workspace records" })
    .fill(`AI-FEEDBACK-PROD-${runId}`);
  await page.getByRole("button", { name: "Find permitted records" }).click();
  await page
    .getByRole("button", { name: `Add Production AI feedback ${runId}` })
    .click();
  await page.getByRole("button", { name: "Start conversation" }).click();
  await page
    .getByRole("textbox", { name: "Ask this workspace" })
    .fill("What is this matter's current status?");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  const assistantFeedback = page
    .locator('[data-testid^="workspace-assistant-feedback-"]')
    .last();
  await expect(assistantFeedback).toBeVisible({ timeout: 30_000 });
  const [assistantRating] = await Promise.all([
    page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname ===
          "/api/ai-feedback/workspace-assistant" &&
        response.request().method() === "POST",
      { timeout: 20_000 },
    ),
    assistantFeedback
      .getByRole("button", { name: "Mark as not helpful" })
      .click(),
  ]);
  expect(assistantRating.status()).toBe(201);
  const assistantRecord: FeedbackRecord = await assistantRating.json();
  state.feedbackIds.add(assistantRecord.id);

  await page.goto(`${WEB}/app/admin/ai-feedback`, {
    waitUntil: "load",
    timeout: 30_000,
  });
  const reportRow = page.locator(`[data-feedback-id="${reportRecord.id}"]`);
  await expect(reportRow).toContainText(`Production guide review ${runId}`);
  await reportRow
    .getByRole("textbox", { name: "Review notes" })
    .fill("Production acceptance reviewed.");
  const [reviewed] = await Promise.all([
    page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname ===
          `/api/admin/ai-feedback/${reportRecord.id}` &&
        response.request().method() === "PATCH",
      { timeout: 20_000 },
    ),
    reportRow.getByRole("button", { name: "Save" }).click(),
  ]);
  expect(reviewed.status()).toBe(200);
  await expect(reportRow).toContainText("In Review");

  await page.setViewportSize({ width: 360, height: 800 });
  await page.reload({ waitUntil: "load", timeout: 30_000 });
  await expect(
    page.getByRole("heading", { name: "Feedback review" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth >
        document.documentElement.clientWidth + 1,
    ),
  ).toBe(false);
});
