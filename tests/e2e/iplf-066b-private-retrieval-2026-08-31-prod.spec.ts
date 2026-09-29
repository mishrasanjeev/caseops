/** IPLF-066B exact-release production acceptance for private revocation. */

import { expect, test, type APIRequestContext } from "@playwright/test";
import { randomBytes } from "node:crypto";

import { noPaidProviderHeaders } from "./support/cost-controls";
import { expectStatus } from "./support/iplf058b";
import {
  assertPrivateAccessQaIdentity,
  PRIVATE_ACCESS_HIDDEN_NOTICE,
  selectPrivateAccessAnswer,
  verifyPrivateAccessAnswerHidden,
} from "./support/private-access-lock-proof";
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
  headers: Record<string, string>;
  matter: MatterRecord;
  originalPolicy: TenantPolicy;
  enabledPolicy: TenantPolicy;
  colleague?: { membership_id: string; email: string };
  wallId?: string;
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

async function removeAccessWall(api: APIRequestContext, state: CleanupState): Promise<void> {
  if (!state.wallId) return;
  const response = await api.delete(
    `${API}/api/matters/${state.matter.id}/access/walls/${state.wallId}`,
    { headers: state.headers, timeout: 10_000 },
  );
  await expectStatus(response, 204, "remove only this canary's ethical wall");
  state.wallId = undefined;
}

async function deactivateAccessColleague(api: APIRequestContext, state: CleanupState): Promise<void> {
  if (!state.colleague) return;
  const response = await api.patch(
    `${API}/api/companies/current/users/${state.colleague.membership_id}`,
    { headers: state.headers, timeout: 10_000, data: { is_active: false } },
  );
  await expectStatus(response, 200, "deactivate only this synthetic QA colleague");
  const colleague = await response.json();
  expect(colleague.membership_id).toBe(state.colleague.membership_id);
  expect(colleague.email).toBe(state.colleague.email);
  expect(colleague.membership_active).toBe(false);
  expect(colleague.user_active).toBe(false);
  state.colleague = undefined;
}

test.afterEach(async ({ request }, testInfo) => {
  const state = cleanupState;
  cleanupState = undefined;
  if (!state) return;
  testInfo.setTimeout(90_000);
  const failures: string[] = [];
  for (const [name, cleanup] of [
    ["ethical_wall", removeAccessWall],
    ["matter", disposeFixture],
    ["tenant_policy", restorePolicy],
    ["synthetic_colleague", deactivateAccessColleague],
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

test("IPLF-066B production locks answers after access restore and revokes private retrieval", async ({
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
    headers: noPaidProviderHeaders,
    data: {
      company_slug: SLUG,
      email: EMAIL,
      password: required("CASEOPS_IP_QA_PASSWORD"),
    },
  });
  await expectStatus(login, 200, "IP QA sign-in");
  const identity = await login.json();
  assertPrivateAccessQaIdentity(identity);
  const headers = { ...noPaidProviderHeaders, Authorization: `Bearer ${identity.access_token}` };

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
    .fill(`Show what the evidence says about ${evidenceToken}.`);
  const answerResponse = page.waitForResponse((response) =>
    response.url().startsWith(`${API}/api/workspace-assistant/sessions/`) &&
    response.url().endsWith("/ask") && response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  const answeredResponse = await answerResponse;
  expect(await answeredResponse.request().headerValue("X-CaseOps-Automated-Test")).toBe("no-paid-providers");
  expect(answeredResponse.status()).toBe(200);
  const answered = await answeredResponse.json();
  const sessionId = String(answered.session.id);
  const answer = selectPrivateAccessAnswer(
    [answered.assistant_turn], evidenceToken, beforeItems[0].source_id,
  );
  expect(answer.proposed_actions).toEqual([expect.objectContaining({
    action_type: "navigation", label: `Open ${filename}`,
    target_type: "matter_document", target_id: beforeItems[0].source_id,
    target_label: filename,
  })]);
  await expect(page.getByTestId("assistant-turns")).toContainText(
    evidenceToken,
  );
  await expect(page.getByRole("link", { name: filename, exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: `Open ${filename}`, exact: true })).toBeVisible();
  await expect(page.getByTestId("assistant-turns")).not.toContainText(
    "Ignore previous instructions",
  );

  const turnsResponse = await page.request.get(
    `${API}/api/workspace-assistant/sessions/${sessionId}/turns`, { headers },
  );
  await expectStatus(turnsResponse, 200, "capture the visible private answer and citation");
  const turns = await turnsResponse.json();
  expect(turns.has_more).toBe(false);
  expect(selectPrivateAccessAnswer(turns.items, evidenceToken, beforeItems[0].source_id).id).toBe(answer.id);
  const visibleCitation = await page.request.post(
    `${API}/api/workspace-assistant/sessions/${sessionId}/citations/${answer.citations[0].id}/open`,
    { headers },
  );
  await expectStatus(visibleCitation, 200, "the answer's citation opens before the access event");

  // The canonical seed has no colleague. A unique member belongs only to this
  // QA canary and is deactivated after disposal, never before the lock proof.
  const runId = `${Date.now()}-${randomBytes(8).toString("hex")}`;
  const colleagueEmail = `ip-qa-access-${runId}@caseops.ai`;
  const colleagueResponse = await page.request.post(`${API}/api/companies/current/users`, {
    headers,
    data: {
      full_name: `IPLF-066B Synthetic Access Colleague ${runId}`,
      email: colleagueEmail,
      password: `Qa1!${randomBytes(24).toString("hex")}`,
      role: "member",
    },
  });
  await expectStatus(colleagueResponse, 200, "create one dedicated synthetic QA colleague");
  const colleague = await colleagueResponse.json();
  cleanupState.colleague = { membership_id: String(colleague.membership_id), email: colleagueEmail };
  expect(colleague.email).toBe(colleagueEmail);
  expect(colleague.role).toBe("member");
  expect(colleague.membership_active).toBe(true);
  expect(colleague.user_active).toBe(true);
  expect(colleague.membership_id).not.toBe(identity.membership.id);
  const wallResponse = await page.request.post(`${API}/api/matters/${matter.id}/access/walls`, {
    headers,
    data: {
      excluded_membership_id: colleague.membership_id,
      reason: "Exact-release IPLF-066B synthetic access-lock canary.",
    },
  });
  await expectStatus(wallResponse, 200, "change access without excluding the answer's author");
  cleanupState.wallId = String((await wallResponse.json()).id);
  const proof = {
    apiBase: API, headers, sessionId, answerId: answer.id,
    citationId: answer.citations[0].id, evidenceToken,
  };
  const assertAuthorStillReadsMatter = async () => {
    const response = await page.request.get(`${API}/api/matters/${matter.id}`, { headers });
    await expectStatus(response, 200, "the answer's author still reads the active Matter");
    const current = await response.json();
    expect(current.id).toBe(matter.id);
    expect(current.matter_code).toBe(matter.matter_code);
    expect(current.status).toBe("active");
  };
  await assertAuthorStillReadsMatter();
  await verifyPrivateAccessAnswerHidden(page.request, proof);
  await removeAccessWall(page.request, cleanupState);
  await assertAuthorStillReadsMatter();
  await verifyPrivateAccessAnswerHidden(page.request, proof);

  for (const width of [1280, 360]) {
    await page.setViewportSize({ width, height: 800 });
    await page.reload();
    await page.getByRole("button", { name: `Ask \u00b7 ${filename}`, exact: true }).click();
    const savedAnswer = page.locator('[data-turn-role="assistant"]').last();
    await expect(savedAnswer).toContainText(PRIVATE_ACCESS_HIDDEN_NOTICE);
    await expect(savedAnswer).not.toContainText(evidenceToken);
    await expect(page.getByRole("link", { name: filename })).toHaveCount(0);
    await expect(page.getByRole("link", { name: `Open ${filename}`, exact: true })).toHaveCount(0);
    await expect(page.getByRole("textbox", { name: "Ask this workspace" })).toBeVisible();
    expect(await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    )).toBe(false);
    await verifyPrivateAccessAnswerHidden(page.request, proof);
  }

  const [currentApiIdentity, currentWebIdentity] = await Promise.all([
    page.request.get(`${API}/api/build`, { headers }),
    page.request.get(`${WEB}/api/release-identity`, { headers: noPaidProviderHeaders }),
  ]);
  await expectStatus(currentApiIdentity, 200, "API release identity before disposal");
  await expectStatus(currentWebIdentity, 200, "web release identity before disposal");
  expect((await currentApiIdentity.json()).release_sha).toBe(expectedSha);
  expect((await currentWebIdentity.json()).release_sha).toBe(expectedSha);

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
