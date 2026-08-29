/** IPLF-064B / UJ-23 proposed-write preview and confirmation acceptance. */

import { expect, test } from "@playwright/test";

import { apiBaseUrl } from "./support/env";
import { expectStatus } from "./support/iplf058b";

test("IPLF-UJ-23-NORMAL and IPLF-UJ-23-EXC-03 enforce preview before writes", async ({
  page,
}) => {
  test.setTimeout(240_000);
  const runId = `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  const slug = `assistant-action-${runId}`;
  const email = `assistant-action-${runId}@example.com`;
  const password = "AssistantAction2026!";
  const bootstrap = await page.request.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: `Assistant Action ${runId}`,
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Assistant Action Owner",
      owner_email: email,
      owner_password: password,
    },
  });
  await expectStatus(bootstrap, 200, "assistant-action tenant bootstrap");
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
  await expectStatus(policy, 200, "enable assistant-action policy");
  const matterResponse = await page.request.post(`${apiBaseUrl}/api/matters`, {
    headers,
    data: {
      matter_code: `AI-ACTION-${runId}`,
      title: `Assistant action ${runId}`,
      practice_area: "Intellectual Property",
      forum_level: "high_court",
    },
  });
  await expectStatus(matterResponse, 200, "assistant-action Matter fixture");
  const matter = await matterResponse.json();

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
  await page.getByRole("textbox", { name: "Find workspace records" }).fill(`AI-ACTION-${runId}`);
  await page.getByRole("button", { name: "Find permitted records" }).click();
  await page.getByRole("button", { name: `Add Assistant action ${runId}` }).click();
  await page.getByRole("button", { name: "Start conversation" }).click();

  await page
    .getByRole("textbox", { name: "Ask this workspace" })
    .fill("Create a task to review the registry evidence.");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  const proposal = page.getByRole("button", { name: "Prepare a task proposal" });
  await expect(proposal).toBeEnabled();
  let tasksResponse = await page.request.get(`${apiBaseUrl}/api/matters/${matter.id}/tasks`, {
    headers,
  });
  await expectStatus(tasksResponse, 200, "tasks after proposal");
  expect((await tasksResponse.json()).tasks).toEqual([]);

  await page.setViewportSize({ width: 360, height: 800 });
  await proposal.click();
  await expect(page.getByRole("heading", { name: "Review task" })).toBeVisible();
  await page.getByRole("textbox", { name: "Task title" }).fill("Review registry evidence");
  await page.getByRole("textbox", { name: "Description" }).fill("Verify source links.");
  await page.getByRole("button", { name: "Review changes" }).click();
  await expect(page.getByText(/Create one task on/)).toBeVisible();
  await expect(
    page.getByText("Nothing is written until you confirm this exact preview."),
  ).toBeVisible();
  tasksResponse = await page.request.get(`${apiBaseUrl}/api/matters/${matter.id}/tasks`, {
    headers,
  });
  await expectStatus(tasksResponse, 200, "tasks after preview");
  expect((await tasksResponse.json()).tasks).toEqual([]);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    ),
  ).toBe(false);

  await page.getByRole("button", { name: "Confirm action" }).click();
  await expect(page.getByText("Action confirmed")).toBeVisible();
  await expect(page.getByRole("link", { name: /Open result/ })).toHaveAttribute(
    "href",
    `/app/matters/${matter.id}/tasks`,
  );
  tasksResponse = await page.request.get(`${apiBaseUrl}/api/matters/${matter.id}/tasks`, {
    headers,
  });
  await expectStatus(tasksResponse, 200, "tasks after confirmation");
  const tasks = (await tasksResponse.json()).tasks;
  expect(tasks).toHaveLength(1);
  expect(tasks[0]).toMatchObject({
    title: "Review registry evidence",
    description: "Verify source links.",
    status: "todo",
  });
  await page.getByRole("button", { name: "Close action review" }).click();

  await page
    .getByRole("textbox", { name: "Ask this workspace" })
    .fill("Update the client name on this matter.");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  await page.getByRole("button", { name: "Prepare a field-change proposal" }).click();
  await page.getByRole("combobox", { name: "Matter field" }).click();
  await page.getByRole("option", { name: "Client name" }).click();
  await page.getByRole("textbox", { name: "Proposed value" }).fill("Aster Brands Ltd");
  await page.getByRole("button", { name: "Review changes" }).click();

  const currentMatterResponse = await page.request.get(`${apiBaseUrl}/api/matters/${matter.id}`, {
    headers,
  });
  await expectStatus(currentMatterResponse, 200, "read current Matter version");
  const currentMatter = await currentMatterResponse.json();
  const changedMatter = await page.request.patch(`${apiBaseUrl}/api/matters/${matter.id}`, {
    headers,
    data: {
      description: "Concurrent user edit",
      expected_updated_at: currentMatter.updated_at,
    },
  });
  await expectStatus(changedMatter, 200, "create stale target exception");
  await page.getByRole("button", { name: "Confirm action" }).click();
  await expect(page.getByRole("alert")).toContainText("target changed");
  const unchangedClient = await page.request.get(`${apiBaseUrl}/api/matters/${matter.id}`, {
    headers,
  });
  await expectStatus(unchangedClient, 200, "read rejected field update");
  expect((await unchangedClient.json()).client_name).toBeNull();
});
