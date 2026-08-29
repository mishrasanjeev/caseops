/** IPLF-065B exact-release production acceptance for governed AI feedback. */

import { expect, test } from "@playwright/test";

import { expectStatus } from "./support/iplf058b";

const WEB = (process.env.PROD_BASE_URL ?? "https://caseops.ai").trim();
const API = (process.env.PROD_API_BASE_URL ?? "https://api.caseops.ai").trim();
const SLUG = (process.env.CASEOPS_IP_QA_SLUG ?? "caseops-ip-qa").trim();
const EMAIL = (process.env.CASEOPS_IP_QA_EMAIL ?? "ip-qa-bot@caseops.ai").trim();

type FeedbackRecord = { id: string; updated_at: string };

function required(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required.`);
  return value;
}

test("IPLF-065B production proves exact feedback and review behavior", async ({ page }) => {
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
  await expectStatus(enabledResponse, 200, "enable production assistant feedback");
  const enabledPolicy = await enabledResponse.json();
  const createdFeedback: FeedbackRecord[] = [];

  try {
    const runId = `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
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

    await page.goto(`${WEB}/guide`);
    await page
      .getByRole("searchbox", { name: "Search the CaseOps guide" })
      .fill("deadline control");
    await page.getByRole("button", { name: "Search" }).click();
    const guideRatingResponse = page.waitForResponse(
      (response) =>
        response.url().includes("/api/ai-feedback/product-guide") &&
        response.request().method() === "POST",
    );
    await page
      .getByTestId("product-guide-feedback-command-deadline-control")
      .getByRole("button", { name: "Mark as helpful" })
      .click();
    const guideRating = await guideRatingResponse;
    expect(guideRating.status()).toBe(201);
    createdFeedback.push(await guideRating.json());

    await page
      .getByRole("searchbox", { name: "Search the CaseOps guide" })
      .fill(`missing production guide ${runId}`);
    await page.getByRole("button", { name: "Search" }).click();
    const noMatch = page.getByTestId("product-guide-feedback-no-match");
    await noMatch.getByRole("button", { name: "Report an issue" }).click();
    await noMatch.getByLabel("Issue", { exact: true }).selectOption("missing_guidance");
    await noMatch.getByLabel("Note").fill(`Production guide review ${runId}`);
    const guideReportResponse = page.waitForResponse(
      (response) =>
        response.url().includes("/api/ai-feedback/product-guide") &&
        response.request().method() === "POST",
    );
    await noMatch.getByRole("button", { name: "Submit report" }).click();
    const guideReport = await guideReportResponse;
    expect(guideReport.status()).toBe(201);
    const reportRecord: FeedbackRecord = await guideReport.json();
    createdFeedback.push(reportRecord);

    await page.goto(`${WEB}/app/assistant`);
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
    const assistantFeedback = page.locator('[data-testid^="workspace-assistant-feedback-"]').last();
    await expect(assistantFeedback).toBeVisible();
    const assistantRatingResponse = page.waitForResponse(
      (response) =>
        response.url().includes("/api/ai-feedback/workspace-assistant") &&
        response.request().method() === "POST",
    );
    await assistantFeedback.getByRole("button", { name: "Mark as not helpful" }).click();
    const assistantRating = await assistantRatingResponse;
    expect(assistantRating.status()).toBe(201);
    createdFeedback.push(await assistantRating.json());

    await page.goto(`${WEB}/app/admin/ai-feedback`);
    const reportRow = page.locator(`[data-feedback-id="${reportRecord.id}"]`);
    await expect(reportRow).toContainText(`Production guide review ${runId}`);
    await reportRow.getByRole("textbox", { name: "Review notes" }).fill("Production acceptance reviewed.");
    const reviewResponse = page.waitForResponse(
      (response) =>
        response.url().includes(`/api/admin/ai-feedback/${reportRecord.id}`) &&
        response.request().method() === "PATCH",
    );
    await reportRow.getByRole("button", { name: "Save" }).click();
    const reviewed = await reviewResponse;
    expect(reviewed.status()).toBe(200);
    const reviewedRecord: FeedbackRecord = await reviewed.json();
    createdFeedback.splice(
      createdFeedback.findIndex((record) => record.id === reviewedRecord.id),
      1,
      reviewedRecord,
    );
    await expect(reportRow).toContainText("In Review");

    await page.setViewportSize({ width: 360, height: 800 });
    await page.reload();
    await expect(page.getByRole("heading", { name: "Feedback review" })).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
      ),
    ).toBe(false);
  } finally {
    for (const record of createdFeedback) {
      const resolved = await page.request.patch(`${API}/api/admin/ai-feedback/${record.id}`, {
        headers,
        data: {
          expected_updated_at: record.updated_at,
          status: "resolved",
          review_notes: "Closed after exact-release production acceptance.",
        },
      });
      await expectStatus(resolved, 200, `resolve production feedback ${record.id}`);
    }
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
