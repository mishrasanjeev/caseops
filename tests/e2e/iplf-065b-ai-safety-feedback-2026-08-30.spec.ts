import { expect, test } from "@playwright/test";

import { apiBaseUrl } from "./support/env";
import { expectStatus } from "./support/iplf058b";

test("IPLF-UJ-22 and IPLF-UJ-23 feedback is responsive and reviewable", async ({
  page,
}) => {
  const runId = `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  const slug = `ai-feedback-${runId}`;
  const bootstrap = await page.request.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: `AI Feedback ${runId}`,
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "AI Feedback Owner",
      owner_email: `owner-${runId}@example.com`,
      owner_password: "AIFeedback2026!",
    },
  });
  await expectStatus(bootstrap, 200, "AI feedback tenant bootstrap");
  const identity = await bootstrap.json();
  const headers = { Authorization: `Bearer ${identity.access_token}` };

  const policy = await page.request.patch(`${apiBaseUrl}/api/admin/tenant-ai-policy`, {
    headers,
    data: {
      expected_version: 1,
      workspace_assistant_enabled: true,
      assistant_retention_days: 30,
      allowed_models_assistant: ["caseops-mock-1"],
    },
  });
  await expectStatus(policy, 200, "enable assistant for feedback journey");
  const matter = await page.request.post(`${apiBaseUrl}/api/matters`, {
    headers,
    data: {
      matter_code: `FB-${runId}`,
      title: `Feedback matter ${runId}`,
      practice_area: "Intellectual Property",
      forum_level: "high_court",
    },
  });
  await expectStatus(matter, 200, "feedback assistant matter");

  await page.goto("/");
  await page.evaluate(
    (context) => window.localStorage.setItem("caseops.session.context", JSON.stringify(context)),
    {
      company: identity.company,
      user: identity.user,
      membership: identity.membership,
      capabilities: identity.capabilities,
    },
  );

  await page.goto("/guide");
  await page.getByRole("searchbox", { name: "Search the CaseOps guide" }).fill("deadline control");
  await page.getByRole("button", { name: "Search" }).click();
  const ratingResponse = page.waitForResponse(
    (response) =>
      response.url().includes("/api/ai-feedback/product-guide") &&
      response.request().method() === "POST",
  );
  await page
    .getByTestId("product-guide-feedback-command-deadline-control")
    .getByRole("button", { name: "Mark as helpful" })
    .click();
  const rating = await ratingResponse;
  expect(rating.status()).toBe(201);
  const ratingRecord = await rating.json();
  await expect(page.getByText("Feedback received")).toBeVisible();

  await page.getByRole("searchbox", { name: "Search the CaseOps guide" }).fill("xylophone nebula quasar");
  await page.getByRole("button", { name: "Search" }).click();
  const noMatch = page.getByTestId("product-guide-feedback-no-match");
  await noMatch.getByRole("button", { name: "Report an issue" }).click();
  await noMatch.getByLabel("Issue", { exact: true }).selectOption("missing_guidance");
  await noMatch.getByLabel("Note").fill("A trademark renewal checklist is missing.");
  const reportResponse = page.waitForResponse(
    (response) =>
      response.url().includes("/api/ai-feedback/product-guide") &&
      response.request().method() === "POST",
  );
  await noMatch.getByRole("button", { name: "Submit report" }).click();
  const report = await reportResponse;
  expect(report.status()).toBe(201);
  const reportRecord = await report.json();

  await page.goto("/app/assistant");
  await page.getByRole("textbox", { name: "Find workspace records" }).fill(`FB-${runId}`);
  await page.getByRole("button", { name: "Find permitted records" }).click();
  await page.getByRole("button", { name: `Add Feedback matter ${runId}` }).click();
  await page.getByRole("button", { name: "Start conversation" }).click();
  await page
    .getByRole("textbox", { name: "Ask this workspace" })
    .fill("What is this matter's status?");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  const assistantFeedback = page.locator('[data-testid^="workspace-assistant-feedback-"]').last();
  await expect(assistantFeedback).toBeVisible();
  const assistantResponse = page.waitForResponse(
    (response) =>
      response.url().includes("/api/ai-feedback/workspace-assistant") &&
      response.request().method() === "POST",
  );
  await assistantFeedback.getByRole("button", { name: "Mark as not helpful" }).click();
  expect((await assistantResponse).status()).toBe(201);

  await page.goto("/app/admin/ai-feedback");
  const queue = page.getByTestId("ai-feedback-queue");
  await expect(queue).toContainText("A trademark renewal checklist is missing.");
  const reportRow = page.locator(`[data-feedback-id="${reportRecord.id}"]`);
  await reportRow.getByRole("textbox", { name: "Review notes" }).fill("Assigned for guide coverage review.");
  const reviewResponse = page.waitForResponse(
    (response) =>
      response.url().includes(`/api/admin/ai-feedback/${reportRecord.id}`) &&
      response.request().method() === "PATCH",
  );
  await reportRow.getByRole("button", { name: "Save" }).click();
  expect((await reviewResponse).status()).toBe(200);
  await expect(reportRow).toContainText("In Review");

  const apiQueue = await page.request.get(
    `${apiBaseUrl}/api/admin/ai-feedback?status=open&limit=100`,
    { headers },
  );
  await expectStatus(apiQueue, 200, "bounded AI feedback queue");
  const queueBody = await apiQueue.json();
  expect(queueBody.items.some((item: { id: string }) => item.id === ratingRecord.id)).toBe(true);
  expect(queueBody.items.some((item: { id: string }) => item.id === reportRecord.id)).toBe(false);
  expect(queueBody.items.length).toBeLessThanOrEqual(100);

  await page.setViewportSize({ width: 360, height: 800 });
  await page.goto("/app/admin/ai-feedback");
  await expect(page.getByRole("heading", { name: "Feedback review" })).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    ),
  ).toBe(false);
});
