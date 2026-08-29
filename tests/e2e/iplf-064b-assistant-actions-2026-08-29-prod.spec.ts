/** IPLF-064B exact-release production acceptance for UJ-23 proposed writes. */

import { expect, test } from "@playwright/test";

import { expectStatus } from "./support/iplf058b";

const WEB = (process.env.PROD_BASE_URL ?? "https://caseops.ai").trim();
const API = (process.env.PROD_API_BASE_URL ?? "https://api.caseops.ai").trim();
const SLUG = (process.env.CASEOPS_IP_QA_SLUG ?? "caseops-ip-qa").trim();
const EMAIL = (process.env.CASEOPS_IP_QA_EMAIL ?? "ip-qa-bot@caseops.ai").trim();

function required(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required.`);
  return value;
}

test("IPLF-064B production proves exact preview-confirm behavior", async ({ page }) => {
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
  const originalPolicyResponse = await page.request.get(`${API}/api/admin/tenant-ai-policy`, {
    headers,
  });
  await expectStatus(originalPolicyResponse, 200, "read production assistant policy");
  const originalPolicy = await originalPolicyResponse.json();
  const enabledResponse = await page.request.patch(`${API}/api/admin/tenant-ai-policy`, {
    headers,
    data: {
      expected_version: originalPolicy.policy_version,
      workspace_assistant_enabled: true,
      assistant_retention_days: originalPolicy.assistant_retention_days,
      allowed_models_assistant: [],
    },
  });
  await expectStatus(enabledResponse, 200, "enable production assistant actions");
  const enabledPolicy = await enabledResponse.json();

  try {
    const runId = `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
    const matterResponse = await page.request.post(`${API}/api/matters/`, {
      headers,
      data: {
        matter_code: `AI-ACTION-PROD-${runId}`,
        title: `Production assistant action ${runId}`,
        practice_area: "Intellectual Property",
        forum_level: "high_court",
      },
    });
    await expectStatus(matterResponse, 200, "production assistant-action Matter");
    const matter = await matterResponse.json();

    await page.goto(WEB);
    await page.evaluate(
      (context) =>
        window.localStorage.setItem("caseops.session.context", JSON.stringify(context)),
      {
        company: identity.company,
        user: identity.user,
        membership: identity.membership,
        capabilities: identity.capabilities,
      },
    );
    await page.goto(`${WEB}/app/assistant`);
    await page
      .getByRole("textbox", { name: "Find workspace records" })
      .fill(`AI-ACTION-PROD-${runId}`);
    await page.getByRole("button", { name: "Find permitted records" }).click();
    await page
      .getByRole("button", { name: `Add Production assistant action ${runId}` })
      .click();
    await page.getByRole("button", { name: "Start conversation" }).click();
    await page
      .getByRole("textbox", { name: "Ask this workspace" })
      .fill("Create a task to review production evidence.");
    await page.getByRole("button", { name: "Ask", exact: true }).click();
    await page.getByRole("button", { name: "Prepare a task proposal" }).click();
    await page.getByRole("textbox", { name: "Task title" }).fill("Production review task");
    await page.getByRole("button", { name: "Review changes" }).click();

    let tasksResponse = await page.request.get(`${API}/api/matters/${matter.id}/tasks`, {
      headers,
    });
    await expectStatus(tasksResponse, 200, "production tasks after preview");
    expect((await tasksResponse.json()).tasks).toEqual([]);
    await page.getByRole("button", { name: "Confirm action" }).click();
    await expect(page.getByText("Action confirmed")).toBeVisible();
    tasksResponse = await page.request.get(`${API}/api/matters/${matter.id}/tasks`, {
      headers,
    });
    await expectStatus(tasksResponse, 200, "production tasks after confirmation");
    const tasks = (await tasksResponse.json()).tasks;
    expect(tasks).toHaveLength(1);
    expect(tasks[0].title).toBe("Production review task");

    await page.setViewportSize({ width: 360, height: 800 });
    await expect(page.getByTestId("assistant-action-dialog")).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
      ),
    ).toBe(false);
  } finally {
    const restore = await page.request.patch(`${API}/api/admin/tenant-ai-policy`, {
      headers,
      data: {
        expected_version: enabledPolicy.policy_version,
        workspace_assistant_enabled: originalPolicy.workspace_assistant_enabled,
        assistant_retention_days: originalPolicy.assistant_retention_days,
        allowed_models_assistant: originalPolicy.allowed_models_assistant,
      },
    });
    await expectStatus(restore, 200, "restore production assistant policy");
  }
});
