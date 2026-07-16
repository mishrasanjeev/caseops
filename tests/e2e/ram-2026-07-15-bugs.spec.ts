import { expect, request, test } from "@playwright/test";
import type { APIRequestContext, APIResponse, Page } from "@playwright/test";
import { readFile } from "node:fs/promises";

import { apiBaseUrl } from "./support/env";
import { makeUploadFixture } from "./support/helpers";

const COMPANY_SLUG = "legal";
const OWNER_EMAIL = "hari.gupta@gmail.com";
// Normal regression runs use an isolated synthetic password. The July 15
// workstation replay sets CASEOPS_RAM_LOCAL_PASSWORD to the supplied tester
// password so the local account has the exact requested credentials without
// committing the secret to source control.
const OWNER_PASSWORD =
  process.env.CASEOPS_RAM_LOCAL_PASSWORD ?? "RamLocalRegression0715!";

type MatterRecord = {
  id: string;
  matter_code: string;
  title: string;
  status: string;
  updated_at: string;
};

let api: APIRequestContext;
let token = "";
let firstMatter: MatterRecord;
let secondMatter: MatterRecord;

function uniqueCode(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random()
    .toString(36)
    .slice(2, 6)}`.toUpperCase();
}

async function expectStatus(
  response: APIResponse,
  status: number,
  label: string,
): Promise<void> {
  expect(
    response.status(),
    `${label}: expected ${status}; received ${response.status()} ${await response.text()}`,
  ).toBe(status);
}

function authHeaders(): Record<string, string> {
  return { Authorization: `Bearer ${token}` };
}

async function signIn(page: Page): Promise<void> {
  await page.goto("/sign-in");
  await page.locator("#company-slug").fill(COMPANY_SLUG);
  await page.locator("#email").fill(OWNER_EMAIL);
  await page.locator("#password").fill(OWNER_PASSWORD);
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  await page.waitForURL(/\/app/);
}

async function getMatter(matterId: string): Promise<MatterRecord> {
  const response = await api.get(`${apiBaseUrl}/api/matters/${matterId}`, {
    headers: authHeaders(),
  });
  await expectStatus(response, 200, "read matter");
  return (await response.json()) as MatterRecord;
}

async function createApiMatter(
  code: string,
  options: {
    status?: "active" | "intake";
    opposingParty?: string;
  } = {},
): Promise<MatterRecord> {
  const response = await api.post(`${apiBaseUrl}/api/matters/`, {
    headers: authHeaders(),
    data: {
      title: `Ram July 15 ${code}`,
      matter_code: code,
      client_name: "Ram Regression Client",
      opposing_party: options.opposingParty ?? `Independent Opponent ${code}`,
      practice_area: "Litigation",
      forum_level: "high_court",
      court_name: "Delhi High Court",
      ...(options.status ? { status: options.status } : {}),
    },
  });
  await expectStatus(response, 200, "create API matter");
  return (await response.json()) as MatterRecord;
}

async function runClearedConflictCheck(
  matterId: string,
  opposingPartyName: string,
  label: string,
): Promise<{ id: string; status: string }> {
  const response = await api.post(
    `${apiBaseUrl}/api/matters/${matterId}/conflict-checks`,
    {
      headers: authHeaders(),
      data: {
        opposing_party_name: opposingPartyName,
        related_party_names: [],
      },
    },
  );
  await expectStatus(response, 200, label);
  let check = (await response.json()) as { id: string; status: string };

  if (check.status === "pending") {
    const resolution = await api.patch(
      `${apiBaseUrl}/api/conflict-checks/${check.id}`,
      {
        headers: authHeaders(),
        data: {
          status: "cleared",
          resolution_note:
            "Owner reviewed the test overlap and confirmed no real conflict.",
        },
      },
    );
    await expectStatus(resolution, 200, `${label} resolution`);
    check = (await resolution.json()) as { id: string; status: string };
  }

  expect(check.status).toBe("cleared");
  return check;
}

test.describe.serial("Ram 2026-07-15 workbook and case-reopening regressions", () => {
  test.setTimeout(180_000);

  test.beforeAll(async () => {
    api = await request.newContext();
    const response = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
      data: {
        company_name: "Legal - Ram July 15 local regression",
        company_slug: COMPANY_SLUG,
        company_type: "law_firm",
        owner_full_name: "Hari Gupta",
        owner_email: OWNER_EMAIL,
        owner_password: OWNER_PASSWORD,
      },
    });
    await expectStatus(response, 200, "bootstrap local legal tenant");
    token = ((await response.json()) as { access_token: string }).access_token;
  });

  test.afterAll(async () => {
    await api?.dispose();
  });

  test("BUG-002: New Matter defaults to Active and direct creation needs no conflict gate", async ({
    page,
  }) => {
    await signIn(page);
    await page.goto("/app/matters");
    await page.locator("main").getByTestId("new-matter-trigger").first().click();

    const dialog = page.getByRole("dialog", { name: /New matter/i });
    await expect(dialog).toBeVisible();
    const statusSelect = dialog.getByRole("combobox", { name: "Status" });
    await expect(statusSelect).toHaveText(/^Active$/);
    await statusSelect.click();
    await expect(page.getByRole("option", { name: "Dispose" })).toHaveCount(0);
    await page.keyboard.press("Escape");
    await expect(dialog).toContainText(/not an intake gate/i);

    const code = uniqueCode("RAM715A");
    await dialog.getByLabel("Title").fill("Ram default Active matter");
    await dialog.getByLabel("Matter code").fill(code);
    await dialog.getByLabel("Practice area").fill("Commercial Litigation");
    await dialog.getByLabel("Client name").fill("Ram Regression Client");
    await dialog.getByLabel("Opposing party").fill("Ram Regression Opponent");
    await expect(page.getByTestId("new-matter-forum-state")).toHaveValue("Delhi");

    const createResponse = page.waitForResponse(
      (response) =>
        response.url().endsWith("/api/matters/") &&
        response.request().method() === "POST",
    );
    await dialog.getByRole("button", { name: /Create matter/i }).click();
    const response = await createResponse;
    expect(response.status(), await response.text()).toBe(200);
    firstMatter = (await response.json()) as MatterRecord;
    expect(firstMatter.status).toBe("active");
    await expect(dialog).toBeHidden();
    await expect(page.getByText(code).first()).toBeVisible();

    // Omitted API status follows the same product default; this guards clients
    // outside the React form and the bulk/default policy seam.
    secondMatter = await createApiMatter(uniqueCode("RAM715B"));
    expect(secondMatter.status).toBe("active");
  });

  test("BUG-001: global Notices supports unlinked received and multi-matter sent workflows", async ({
    page,
  }) => {
    await signIn(page);
    const noticesLink = page.getByRole("link", { name: "Notices", exact: true });
    await expect(noticesLink).toBeVisible();
    await noticesLink.click();
    await expect(page).toHaveURL(/\/app\/notices$/);
    await expect(
      page.getByRole("heading", { name: "Notice management" }),
    ).toBeVisible();

    const receivedSubject = `Standalone regulator notice ${Date.now()}`;
    await page.getByRole("button", { name: "New notice" }).first().click();
    let dialog = page.getByTestId("create-notice-dialog");
    await dialog.getByLabel("Subject").fill(receivedSubject);
    await dialog.getByLabel("Authority / counterparty").fill("Tax Authority");
    await dialog.getByLabel("Received from").fill("Assessment Division");
    await expect(dialog.getByText(/link matters \(optional\)/i)).toBeVisible();
    await expect(dialog.getByLabel("Owner")).toContainText("Hari Gupta");
    await dialog.getByLabel("Owner").selectOption({ label: "Hari Gupta" });

    const receivedCreate = page.waitForResponse(
      (response) =>
        response.url().endsWith("/api/notices/") &&
        response.request().method() === "POST",
    );
    await dialog.getByRole("button", { name: "Create notice" }).click();
    const receivedResponse = await receivedCreate;
    expect(receivedResponse.status(), await receivedResponse.text()).toBe(201);
    const receivedNotice = (await receivedResponse.json()) as {
      id: string;
      owner_membership_id: string | null;
      matter_links: unknown[];
    };
    expect(receivedNotice.matter_links).toEqual([]);
    expect(receivedNotice.owner_membership_id).toBeTruthy();

    const receivedRow = page.getByTestId(`notice-row-${receivedNotice.id}`);
    await expect(receivedRow).toContainText(receivedSubject);
    await expect(receivedRow).toContainText("Standalone");
    await expect(receivedRow).toContainText("Hari Gupta");

    const statusUpdate = page.waitForResponse(
      (response) =>
        response.url().endsWith(`/api/notices/${receivedNotice.id}`) &&
        response.request().method() === "PATCH",
    );
    await receivedRow
      .getByLabel(`Status for ${receivedSubject}`)
      .selectOption("Under Review");
    expect((await statusUpdate).status()).toBe(200);

    await page.locator("#notice-search").fill("Standalone regulator");
    await page.getByLabel("Filter by status").fill("Under Review");
    await expect(receivedRow).toBeVisible();
    await page.getByRole("button", { name: "Reset" }).click();

    const sentSubject = `Multi-matter response ${Date.now()}`;
    await page.getByRole("button", { name: "New notice" }).first().click();
    dialog = page.getByTestId("create-notice-dialog");
    await dialog.getByLabel("Direction").selectOption("sent");
    await dialog.getByLabel("Subject").fill(sentSubject);
    await dialog.getByLabel("Owner").selectOption({ label: "Hari Gupta" });
    await dialog
      .getByRole("checkbox", { name: new RegExp(firstMatter.matter_code) })
      .check();
    await dialog
      .getByRole("checkbox", { name: new RegExp(secondMatter.matter_code) })
      .check();
    const sentFileBody =
      "Ram July 15 multi-matter sent notice regression document.";
    const filePath = makeUploadFixture(
      `ram-0715-${Date.now()}-sent-notice.txt`,
      sentFileBody,
    );
    await dialog.getByLabel("Notice document (optional)").setInputFiles(filePath);

    const sentCreate = page.waitForResponse(
      (response) =>
        response.url().endsWith("/api/notices/") &&
        response.request().method() === "POST",
    );
    const sentUpload = page.waitForResponse(
      (response) =>
        /\/api\/notices\/[^/]+\/file$/.test(new URL(response.url()).pathname) &&
        response.request().method() === "POST",
    );
    await dialog.getByRole("button", { name: "Create notice" }).click();
    const sentResponse = await sentCreate;
    expect(sentResponse.status(), await sentResponse.text()).toBe(201);
    const sentNotice = (await sentResponse.json()) as {
      id: string;
      matter_links: Array<{ matter_id: string }>;
    };
    expect(new Set(sentNotice.matter_links.map((link) => link.matter_id))).toEqual(
      new Set([firstMatter.id, secondMatter.id]),
    );
    const uploadResponse = await sentUpload;
    expect(uploadResponse.status(), await uploadResponse.text()).toBe(200);

    await page.getByTestId("notices-sent-tab").click();
    const sentRow = page.getByTestId(`notice-row-${sentNotice.id}`);
    await expect(sentRow).toContainText(sentSubject);
    await expect(sentRow).toContainText(firstMatter.matter_code);
    await expect(sentRow).toContainText(secondMatter.matter_code);
    const downloadButton = sentRow.getByRole("button", { name: /Download/i });
    await expect(downloadButton).toBeVisible();
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      downloadButton.click(),
    ]);
    const downloadedPath = await download.path();
    expect(downloadedPath).toBeTruthy();
    expect(await readFile(downloadedPath!, "utf8")).toBe(sentFileBody);

    // Matter links are not immutable creation metadata. Exercise the manage
    // dialog so a mistaken link can be removed without recreating the notice.
    await sentRow.getByRole("button", { name: "Manage details & links" }).click();
    const manageDialog = page.getByRole("dialog", { name: "Manage notice" });
    await expect(
      manageDialog.getByRole("checkbox", {
        name: new RegExp(secondMatter.matter_code),
      }),
    ).toBeChecked();
    await manageDialog
      .getByRole("checkbox", { name: new RegExp(secondMatter.matter_code) })
      .uncheck();
    const linkUpdate = page.waitForResponse(
      (response) =>
        response.url().endsWith(`/api/notices/${sentNotice.id}`) &&
        response.request().method() === "PATCH",
    );
    await manageDialog.getByRole("button", { name: "Save changes" }).click();
    expect((await linkUpdate).status()).toBe(200);
    await expect(manageDialog).toBeHidden();
    await expect(sentRow).toContainText(firstMatter.matter_code);
    await expect(sentRow).not.toContainText(secondMatter.matter_code);

    // The same source record is visible from the linked matter workspace;
    // this must not create a second matter-attachment row or file copy.
    await page.goto(`/app/matters/${firstMatter.id}/notices`);
    const matterSentTab = page.getByTestId("notice-sent-tab");
    await expect(matterSentTab).toContainText("1");
    await matterSentTab.click();
    await expect(
      page.getByTestId(`matter-global-notice-${sentNotice.id}`),
    ).toContainText(sentSubject);

    await page.goto("/app/notices");
    await page.getByTestId("notices-sent-tab").click();
    await page.locator("#notice-search").fill("Multi-matter response");
    await page.getByLabel("Filter by matter").selectOption(firstMatter.id);
    await expect(page.getByTestId(`notice-row-${sentNotice.id}`)).toBeVisible();
  });

  test("disposed matters resist stale edits and background/operational reopening, then reopen only to Intake", async ({
    page,
  }) => {
    // Establish a valid clearance before disposal. It must not be reusable
    // after the explicit reopen.
    await runClearedConflictCheck(
      firstMatter.id,
      "Ram Regression Opponent",
      "run pre-disposal conflict check",
    );

    const today = new Date().toISOString().slice(0, 10);
    const tomorrowDate = new Date();
    tomorrowDate.setUTCDate(tomorrowDate.getUTCDate() + 1);
    const tomorrow = tomorrowDate.toISOString().slice(0, 10);
    const taskResponse = await api.post(
      `${apiBaseUrl}/api/matters/${firstMatter.id}/tasks`,
      {
        headers: authHeaders(),
        data: { title: "Must disappear after disposal", due_on: today },
      },
    );
    await expectStatus(taskResponse, 200, "create pre-disposal task");
    const preDisposalTask = (await taskResponse.json()) as {
      id: string;
      status: string;
    };
    const deadlineResponse = await api.post(
      `${apiBaseUrl}/api/matters/${firstMatter.id}/deadlines`,
      {
        headers: authHeaders(),
        data: {
          title: "Disposed matter deadline",
          due_on: tomorrow,
          kind: "filing",
        },
      },
    );
    await expectStatus(deadlineResponse, 200, "create pre-disposal deadline");
    const preDisposalDeadline = (await deadlineResponse.json()) as {
      id: string;
    };
    const hearingResponse = await api.post(
      `${apiBaseUrl}/api/matters/${firstMatter.id}/hearings`,
      {
        headers: authHeaders(),
        data: {
          hearing_on: tomorrow,
          forum_name: "Delhi High Court",
          purpose: "Disposed matter hearing",
        },
      },
    );
    await expectStatus(hearingResponse, 200, "create pre-disposal hearing");
    const preDisposalHearing = (await hearingResponse.json()) as {
      id: string;
    };

    await signIn(page);
    await page.goto(`/app/matters/${firstMatter.id}`);
    await page.getByTestId("matter-edit-open").click();
    await page.getByTestId("matter-edit-title").fill("Stale editor title must fail");

    const beforeDispose = await getMatter(firstMatter.id);
    const disposeResponse = await api.patch(
      `${apiBaseUrl}/api/matters/${firstMatter.id}/lifecycle/status`,
      {
        headers: authHeaders(),
        data: {
          to_status: "disposed",
          expected_from_status: "active",
          expected_updated_at: beforeDispose.updated_at,
          reason: "Final order closed the matter for regression testing.",
        },
      },
    );
    await expectStatus(disposeResponse, 200, "dispose matter");

    const staleSave = page.waitForResponse(
      (response) =>
        response.url().endsWith(`/api/matters/${firstMatter.id}`) &&
        response.request().method() === "PATCH",
    );
    await page.getByTestId("matter-edit-save").click();
    expect((await staleSave).status()).toBe(409);
    await expect(page.getByTestId("matter-edit-stale-write")).toContainText(
      /changed in another session/i,
    );
    expect((await getMatter(firstMatter.id)).status).toBe("disposed");

    const todayResponse = await api.get(`${apiBaseUrl}/api/me/today`, {
      headers: authHeaders(),
    });
    await expectStatus(todayResponse, 200, "read Today after disposal");
    const todayPayload = (await todayResponse.json()) as Record<string, unknown>;
    const todayMatterIds = Object.values(todayPayload)
      .flatMap((value) => (Array.isArray(value) ? value : []))
      .map((item) =>
        item && typeof item === "object" && "matter" in item
          ? (item as { matter?: { id?: string } }).matter?.id
          : undefined,
      );
    expect(todayMatterIds).not.toContain(firstMatter.id);

    const calendarResponse = await api.get(`${apiBaseUrl}/api/calendar/events`, {
      headers: authHeaders(),
      params: { from: today, to: tomorrow },
    });
    await expectStatus(calendarResponse, 200, "read calendar after disposal");
    const calendar = (await calendarResponse.json()) as {
      events: Array<{ matter_id: string }>;
    };
    expect(calendar.events.map((event) => event.matter_id)).not.toContain(firstMatter.id);

    const rejectedTask = await api.post(
      `${apiBaseUrl}/api/matters/${firstMatter.id}/tasks`,
      {
        headers: authHeaders(),
        data: { title: "Post-disposal work must fail", due_on: today },
      },
    );
    await expectStatus(rejectedTask, 409, "reject task on disposed matter");

    await page.reload();
    await expect(page.getByTestId("matter-edit-open")).toHaveCount(0);
    await page.getByTestId("matter-reopen-trigger").click();
    await page
      .getByTestId("matter-lifecycle-reason")
      .fill("Fresh client instructions justify controlled reopening.");
    const reopenResponse = page.waitForResponse(
      (response) =>
        response.url().endsWith(`/api/matters/${firstMatter.id}/lifecycle/status`) &&
        response.request().method() === "PATCH",
    );
    await page.getByTestId("matter-lifecycle-confirm").click();
    const reopened = await reopenResponse;
    expect(reopened.status(), await reopened.text()).toBe(200);
    expect(((await reopened.json()) as MatterRecord).status).toBe("intake");

    const tasksAfterReopen = await api.get(
      `${apiBaseUrl}/api/matters/${firstMatter.id}/tasks`,
      { headers: authHeaders() },
    );
    await expectStatus(tasksAfterReopen, 200, "read tasks after controlled reopen");
    const reopenedTask = (
      (await tasksAfterReopen.json()) as {
        tasks: Array<{ id: string; status: string }>;
      }
    ).tasks.find((task) => task.id === preDisposalTask.id);
    expect(reopenedTask?.status).toBe("cancelled");

    const deadlinesAfterReopen = await api.get(
      `${apiBaseUrl}/api/matters/${firstMatter.id}/deadlines`,
      { headers: authHeaders() },
    );
    await expectStatus(
      deadlinesAfterReopen,
      200,
      "read deadlines after controlled reopen",
    );
    const reopenedDeadline = (
      (await deadlinesAfterReopen.json()) as {
        deadlines: Array<{ id: string; status: string }>;
      }
    ).deadlines.find((deadline) => deadline.id === preDisposalDeadline.id);
    expect(reopenedDeadline?.status).toBe("cancelled");

    const workspaceAfterReopen = await api.get(
      `${apiBaseUrl}/api/matters/${firstMatter.id}/workspace`,
      { headers: authHeaders() },
    );
    await expectStatus(
      workspaceAfterReopen,
      200,
      "read hearing history after controlled reopen",
    );
    const reopenedHearing = (
      (await workspaceAfterReopen.json()) as {
        hearings: Array<{ id: string; status: string }>;
      }
    ).hearings.find((hearing) => hearing.id === preDisposalHearing.id);
    expect(reopenedHearing?.status).toBe("cancelled");

    for (const [label, path, data] of [
      [
        "lifecycle-cancelled task",
        `tasks/${preDisposalTask.id}`,
        { status: "todo" },
      ],
      [
        "lifecycle-cancelled deadline",
        `deadlines/${preDisposalDeadline.id}`,
        { status: "open" },
      ],
      [
        "lifecycle-cancelled hearing",
        `hearings/${preDisposalHearing.id}`,
        { status: "scheduled" },
      ],
    ] as const) {
      const response = await api.patch(
        `${apiBaseUrl}/api/matters/${firstMatter.id}/${path}`,
        { headers: authHeaders(), data },
      );
      await expectStatus(response, 409, `reject resurrection of ${label}`);
    }

    const todayAfterReopen = await api.get(`${apiBaseUrl}/api/me/today`, {
      headers: authHeaders(),
    });
    await expectStatus(todayAfterReopen, 200, "read Today after controlled reopen");
    const todayAfterReopenPayload = JSON.stringify(await todayAfterReopen.json());
    expect(todayAfterReopenPayload).not.toContain(preDisposalTask.id);
    expect(todayAfterReopenPayload).not.toContain(preDisposalDeadline.id);
    expect(todayAfterReopenPayload).not.toContain(preDisposalHearing.id);

    let current = await getMatter(firstMatter.id);
    const staleClearanceActivation = await api.patch(
      `${apiBaseUrl}/api/matters/${firstMatter.id}`,
      {
        headers: authHeaders(),
        data: { status: "active", expected_updated_at: current.updated_at },
      },
    );
    await expectStatus(
      staleClearanceActivation,
      409,
      "reject pre-reopen conflict clearance",
    );
    expect((await getMatter(firstMatter.id)).status).toBe("intake");

    await runClearedConflictCheck(
      firstMatter.id,
      "Ram Regression Opponent",
      "run post-reopen conflict check",
    );
    current = await getMatter(firstMatter.id);
    const freshActivation = await api.patch(
      `${apiBaseUrl}/api/matters/${firstMatter.id}`,
      {
        headers: authHeaders(),
        data: { status: "active", expected_updated_at: current.updated_at },
      },
    );
    await expectStatus(freshActivation, 200, "activate after fresh conflict check");
    expect(((await freshActivation.json()) as MatterRecord).status).toBe("active");
  });
});
