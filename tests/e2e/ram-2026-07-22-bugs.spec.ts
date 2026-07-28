import { expect, request, test } from "@playwright/test";
import type { APIRequestContext, Page } from "@playwright/test";

import { apiBaseUrl } from "./support/env";
import {
  authenticateOrBootstrapLocalLegalTenant,
  LOCAL_LEGAL_COMPANY_SLUG,
  LOCAL_LEGAL_OWNER_EMAIL,
  LOCAL_LEGAL_PASSWORD,
} from "./support/local-legal-tenant";

const LOCAL_PASSWORD = LOCAL_LEGAL_PASSWORD;

type MatterRecord = {
  id: string;
  matter_code: string;
  status: "intake" | "active" | "on_hold" | "disposed";
  updated_at: string;
  lifecycle_version: number;
};

type HttpResponse = {
  status(): number;
  text(): Promise<string>;
};

let api: APIRequestContext;
let token = "";
const companySlug = LOCAL_LEGAL_COMPANY_SLUG;
const ownerEmail = LOCAL_LEGAL_OWNER_EMAIL;
let clearedPartyName = "";
let intakeMatter: MatterRecord;
let onHoldMatter: MatterRecord;

function unique(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random()
    .toString(36)
    .slice(2, 8)}`;
}

function authHeaders(): Record<string, string> {
  return { Authorization: `Bearer ${token}` };
}

async function expectStatus(
  response: HttpResponse,
  expected: number,
  label: string,
): Promise<void> {
  const body = response.status() === expected ? "" : ` ${await response.text()}`;
  expect(
    response.status(),
    `${label}: expected HTTP ${expected}, received ${response.status()}.${body}`,
  ).toBe(expected);
}

async function createMatter(
  code: string,
  status: "intake" | "on_hold",
  clientName: string,
  opposingParty: string,
): Promise<MatterRecord> {
  const response = await api.post(`${apiBaseUrl}/api/matters/`, {
    headers: authHeaders(),
    data: {
      title: `Ram July 22 ${code}`,
      matter_code: code,
      client_name: clientName,
      opposing_party: opposingParty,
      practice_area: "Commercial Litigation",
      forum_level: "high_court",
      court_name: "Delhi High Court",
      status,
      description: "Regression coverage for optional conflict review.",
    },
  });
  await expectStatus(response, 200, `create ${status} matter`);
  return (await response.json()) as MatterRecord;
}

async function getMatter(matterId: string): Promise<MatterRecord> {
  const response = await api.get(`${apiBaseUrl}/api/matters/${matterId}`, {
    headers: authHeaders(),
  });
  await expectStatus(response, 200, `read matter ${matterId}`);
  return (await response.json()) as MatterRecord;
}

async function disposeMatter(matter: MatterRecord | undefined): Promise<void> {
  if (!matter) return;
  const current = await getMatter(matter.id);
  if (current.status === "disposed") return;
  const response = await api.patch(
    `${apiBaseUrl}/api/matters/${current.id}/lifecycle/status`,
    {
      headers: authHeaders(),
      data: {
        to_status: "disposed",
        expected_from_status: current.status,
        expected_updated_at: current.updated_at,
        reason: "July 22 local regression cleanup completed.",
      },
    },
  );
  await expectStatus(response, 200, `dispose ${current.matter_code}`);
}

async function signIn(page: Page): Promise<void> {
  await page.goto("/sign-in");
  await page.locator("#company-slug").fill(companySlug);
  await page.locator("#email").fill(ownerEmail);
  await page.locator("#password").fill(LOCAL_PASSWORD);
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  await page.waitForURL(/\/app(?:[/?]|$)/);
}

test.describe.serial("Ram 2026-07-22 optional conflict-review regressions", () => {
  test.setTimeout(180_000);

  test.beforeAll(async () => {
    api = await request.newContext();
    clearedPartyName = unique("Cleared Counterparty");
    token = await authenticateOrBootstrapLocalLegalTenant(api, {
      companyName: `Ram July 22 ${companySlug}`,
      ownerFullName: "Ram July 22 Owner",
    });

    intakeMatter = await createMatter(
      unique("RAM722-INTAKE").toUpperCase(),
      "intake",
      "Independent Intake Client",
      "Independent Intake Opponent",
    );
    onHoldMatter = await createMatter(
      unique("RAM722-HOLD").toUpperCase(),
      "on_hold",
      "Independent On-hold Client",
      clearedPartyName,
    );
  });

  test.afterAll(async () => {
    await disposeMatter(intakeMatter);
    await disposeMatter(onHoldMatter);
    await api?.dispose();
  });

  test("BUG-001 detail: Intake activates without any conflict check", async ({ page }) => {
    await signIn(page);
    await page.goto(`/app/matters/${intakeMatter.id}`);

    const conflictCard = page.getByTestId("matter-conflict-card");
    await expect(conflictCard).toContainText("No conflict check has been run yet.");
    await expect(conflictCard).toContainText(/risk profile/i);

    await page.getByTestId("matter-edit-open").click();
    await page.getByTestId("matter-edit-status").selectOption("active");
    await expect(page.getByTestId("matter-edit-active-conflict-hint")).toHaveCount(0);

    const activationPromise = page.waitForResponse(
      (response) =>
        response.url().endsWith(`/api/matters/${intakeMatter.id}`) &&
        response.request().method() === "PATCH",
    );
    await page.getByTestId("matter-edit-save").click();
    const activation = await activationPromise;
    await expectStatus(activation, 200, "activate Intake matter from detail editor");
    intakeMatter = (await activation.json()) as MatterRecord;
    expect(intakeMatter.status).toBe("active");
    await expect(page.getByTestId("matter-edit-form")).toBeHidden();
    await expect(page.getByTestId("matter-edit-conflict-gate")).toHaveCount(0);
    intakeMatter = await getMatter(intakeMatter.id);
    expect(intakeMatter.status).toBe("active");
    await page.reload();
    await expect(page.getByText("active", { exact: true }).first()).toBeVisible();
  });

  test("BUG-001 lifecycle: a pre-reopen clearance becomes historical and stays nonblocking", async ({
    page,
  }) => {
    await signIn(page);
    await page.goto(`/app/matters/${onHoldMatter.id}`);

    const conflictCard = page.getByTestId("matter-conflict-card");
    await conflictCard.getByTestId("conflict-run-open").click();
    await expect(page.getByTestId("conflict-run-opposing")).toHaveValue(
      clearedPartyName,
    );
    const runPromise = page.waitForResponse(
      (response) =>
        response.url().includes(`/api/matters/${onHoldMatter.id}/conflict-checks`) &&
        response.request().method() === "POST",
    );
    await page.getByTestId("conflict-run-submit").click();
    const runResponse = await runPromise;
    await expectStatus(runResponse, 200, "run optional conflict review");
    const clearedCheck = (await runResponse.json()) as {
      status: string;
      matter_lifecycle_version: number;
    };
    expect(clearedCheck).toMatchObject({
      status: "cleared",
      matter_lifecycle_version: onHoldMatter.lifecycle_version,
    });
    await expect(conflictCard.getByTestId("conflict-status-cleared")).toBeVisible();
    await expect(conflictCard.getByTestId("conflict-status-historical")).toHaveCount(0);

    await page.goto("/app/matters");
    await page.locator("#matter-filter-q").fill(onHoldMatter.matter_code);
    await page.getByRole("button", { name: /Apply/i }).click();
    const statusSelect = page.getByLabel(`Status for ${onHoldMatter.matter_code}`);
    await expect(statusSelect).toHaveValue("on_hold");

    const onHoldActivationPromise = page.waitForResponse(
      (response) =>
        response.url().endsWith(`/api/matters/${onHoldMatter.id}`) &&
        response.request().method() === "PATCH",
    );
    await statusSelect.selectOption("active");
    const onHoldActivation = await onHoldActivationPromise;
    await expectStatus(onHoldActivation, 200, "activate On-hold matter from portfolio");
    onHoldMatter = (await onHoldActivation.json()) as MatterRecord;
    expect(onHoldMatter.status).toBe("active");

    await page.goto(`/app/matters/${onHoldMatter.id}`);
    await expect(conflictCard.getByTestId("conflict-status-cleared")).toBeVisible();

    const beforeDispose = onHoldMatter;
    const disposePromise = page.waitForResponse(
      (response) =>
        response.url().endsWith(
          `/api/matters/${onHoldMatter.id}/lifecycle/status`,
        ) && response.request().method() === "PATCH",
    );
    await page.getByTestId("matter-dispose-trigger").click();
    await page
      .getByTestId("matter-lifecycle-reason")
      .fill("July 22 regression verifies terminal disposal before reopen.");
    await page.getByTestId("matter-lifecycle-confirm").click();
    const disposedResponse = await disposePromise;
    await expectStatus(disposedResponse, 200, "dispose matter through lifecycle UI");
    expect(disposedResponse.request().postDataJSON()).toMatchObject({
      to_status: "disposed",
      expected_from_status: "active",
      expected_updated_at: beforeDispose.updated_at,
    });
    const disposedMatter = (await disposedResponse.json()) as MatterRecord;
    expect(disposedMatter.status).toBe("disposed");
    expect(disposedMatter.lifecycle_version).toBe(
      beforeDispose.lifecycle_version + 1,
    );
    onHoldMatter = disposedMatter;

    await expect(page.getByTestId("matter-reopen-trigger")).toBeVisible();
    const beforeReopen = onHoldMatter;
    const reopenPromise = page.waitForResponse(
      (response) =>
        response.url().endsWith(
          `/api/matters/${onHoldMatter.id}/lifecycle/status`,
        ) && response.request().method() === "PATCH",
    );
    await page.getByTestId("matter-reopen-trigger").click();
    await page
      .getByTestId("matter-lifecycle-reason")
      .fill("Fresh instructions require a controlled reopen into Intake.");
    await page.getByTestId("matter-lifecycle-confirm").click();
    const reopenedResponse = await reopenPromise;
    await expectStatus(reopenedResponse, 200, "reopen matter through lifecycle UI");
    expect(reopenedResponse.request().postDataJSON()).toMatchObject({
      to_status: "intake",
      expected_from_status: "disposed",
      expected_updated_at: beforeReopen.updated_at,
    });
    const reopenedMatter = (await reopenedResponse.json()) as MatterRecord;
    expect(reopenedMatter.status).toBe("intake");
    expect(reopenedMatter.lifecycle_version).toBe(
      beforeReopen.lifecycle_version + 1,
    );
    onHoldMatter = reopenedMatter;

    const historicalBadge = conflictCard.getByTestId("conflict-status-historical");
    await expect(historicalBadge).toContainText(/Historical \(stale\): Cleared/i);
    await expect(historicalBadge).toHaveAttribute("data-original-status", "cleared");
    await expect(conflictCard.getByTestId("conflict-status-cleared")).toHaveCount(0);
    await expect(conflictCard.getByTestId("conflict-historical-notice")).toContainText(
      /does not block status changes/i,
    );
    await expect(conflictCard.getByTestId("conflict-resolve-clear")).toHaveCount(0);

    await page.getByTestId("matter-edit-open").click();
    await page.getByTestId("matter-edit-status").selectOption("active");
    const reopenedActivationPromise = page.waitForResponse(
      (response) =>
        response.url().endsWith(`/api/matters/${onHoldMatter.id}`) &&
        response.request().method() === "PATCH",
    );
    await page.getByTestId("matter-edit-save").click();
    const reopenedActivation = await reopenedActivationPromise;
    await expectStatus(reopenedActivation, 200, "activate reopened Intake matter");
    onHoldMatter = (await reopenedActivation.json()) as MatterRecord;
    expect(onHoldMatter.status).toBe("active");
    expect(onHoldMatter.lifecycle_version).toBe(reopenedMatter.lifecycle_version);
    onHoldMatter = await getMatter(onHoldMatter.id);
    expect(onHoldMatter.status).toBe("active");
    await page.reload();
    await expect(page.getByText("active", { exact: true }).first()).toBeVisible();
    await expect(conflictCard.getByTestId("conflict-status-historical")).toContainText(
      "Cleared",
    );
  });
});
