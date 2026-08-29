import { expect, test } from "@playwright/test";

import { apiBaseUrl } from "./support/env";
import { expectStatus } from "./support/iplf058b";

test("IPLF-UJ-23 runs scoped answers, abstention, and write-proposal exceptions", async ({
  page,
}) => {
  const runId = `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  const slug = `assistant-${runId}`;
  const email = `assistant-${runId}@example.com`;
  const password = "WorkspaceAssistant2026!";
  const bootstrap = await page.request.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: `Assistant ${runId}`,
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Assistant Owner",
      owner_email: email,
      owner_password: password,
    },
  });
  await expectStatus(bootstrap, 200, "assistant tenant bootstrap");
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
  await expectStatus(policy, 200, "enable scoped assistant policy");

  const matter = await page.request.post(`${apiBaseUrl}/api/matters`, {
    headers,
    data: {
      matter_code: `AI-${runId}`,
      title: `Aster assistant ${runId}`,
      practice_area: "Intellectual Property",
      forum_level: "high_court",
    },
  });
  await expectStatus(matter, 200, "assistant matter fixture");
  const matterRecord = await matter.json();

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
  await page.goto("/app/assistant");
  await expect(page.getByRole("heading", { name: "Ask this Workspace" })).toBeVisible();

  await page.getByRole("textbox", { name: "Find workspace records" }).fill(`AI-${runId}`);
  await page.getByRole("button", { name: "Find permitted records" }).click();
  await page.getByRole("button", { name: `Add Aster assistant ${runId}` }).click();
  await page.getByRole("button", { name: "Start conversation" }).click();
  await expect(page.getByTestId("assistant-active-scope")).toContainText(
    `Aster assistant ${runId}`,
  );

  await page
    .getByRole("textbox", { name: "Ask this workspace" })
    .fill("What is this matter's status and practice area?");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  const source = page.getByRole("link", { name: new RegExp(`AI-${runId}`, "i") });
  await expect(source).toHaveAttribute("href", `/app/matters/${matterRecord.id}`);
  await expect(page.getByText(/mock · caseops-mock-1/)).toBeVisible();

  await page
    .getByRole("textbox", { name: "Ask this workspace" })
    .fill("Create a task to review this matter tomorrow.");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  await expect(page.getByRole("button", { name: "Prepare a task proposal" })).toBeEnabled();
  const tasks = await page.request.get(
    `${apiBaseUrl}/api/matters/${matterRecord.id}/tasks`,
    { headers },
  );
  await expectStatus(tasks, 200, "matter tasks remain unchanged after proposal");
  expect((await tasks.json()).tasks).toEqual([]);

  await page
    .getByRole("textbox", { name: "Ask this workspace" })
    .fill("What does the law say under section 21 and which judgment controls?");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  await expect(
    page.getByText("I do not have enough permitted, verified evidence to answer that safely."),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: "Search verified legal sources" })).toHaveAttribute(
    "href",
    /\/app\/research\?query=/,
  );

  await page.setViewportSize({ width: 360, height: 800 });
  await expect(page.getByRole("textbox", { name: "Ask this workspace" })).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    ),
  ).toBe(false);
});
