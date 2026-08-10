import { expect, test, type Page } from "@playwright/test";

const PROD_BASE_URL = process.env.PROD_BASE_URL ?? "https://caseops.ai";
const PROD_API_BASE_URL =
  process.env.PROD_API_BASE_URL ?? "https://api.caseops.ai";
type ProdCredentials = {
  companySlug: string;
  email: string;
  passwordEnvironmentVariable: string;
};

const RAM_PROD_CREDENTIALS: ProdCredentials = {
  companySlug: process.env.CASEOPS_RAM_PROD_SLUG ?? "legal",
  email: process.env.CASEOPS_RAM_PROD_EMAIL ?? "hari.gupta@gmail.com",
  passwordEnvironmentVariable: "CASEOPS_RAM_PROD_PASSWORD",
};
const IP_QA_CREDENTIALS: ProdCredentials = {
  companySlug: process.env.CASEOPS_IP_QA_SLUG ?? "caseops-ip-qa",
  email: process.env.CASEOPS_IP_QA_EMAIL ?? "ip-qa-bot@caseops.ai",
  passwordEnvironmentVariable: "CASEOPS_IP_QA_PASSWORD",
};

function requiredPassword(environmentVariable: string): string {
  const password = process.env[environmentVariable]?.trim() ?? "";
  if (!password)
    throw new Error(
      `${environmentVariable} is required for production proof.`,
    );
  return password;
}

async function signIn(
  page: Page,
  credentials: ProdCredentials = RAM_PROD_CREDENTIALS,
): Promise<{ membership: { id: string } }> {
  await page.goto(`${PROD_BASE_URL}/sign-in`);
  await page.locator("#company-slug").fill(credentials.companySlug);
  await page.locator("#email").fill(credentials.email);
  await page
    .locator("#password")
    .fill(requiredPassword(credentials.passwordEnvironmentVariable));
  const login = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/api/auth/login" &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  const loginResponse = await login;
  expect(loginResponse.status(), await loginResponse.text()).toBe(200);
  await page.waitForURL(new RegExp(`${PROD_BASE_URL}/app(?:[/?]|$)`));
  return (await loginResponse.json()) as { membership: { id: string } };
}

async function csrfHeaders(page: Page): Promise<Record<string, string>> {
  const cookies = await page.context().cookies();
  const csrf = cookies.find((cookie) => cookie.name === "caseops_csrf")?.value;
  expect(csrf, "caseops_csrf cookie must exist after sign-in").toBeTruthy();
  return { "X-CSRF-Token": csrf! };
}

test("IPLF-025A/025B production serves the exact shared-work contract and a ready tenant reconciliation", async ({
  page,
}) => {
  test.setTimeout(120_000);
  const unauthenticated = await fetch(
    `${PROD_API_BASE_URL}/api/ip/shared-work/foundation-contract`,
  );
  expect(unauthenticated.status).toBe(401);

  await signIn(page);
  const contract = await page.request.get(
    `${PROD_API_BASE_URL}/api/ip/shared-work/foundation-contract`,
  );
  expect(contract.status(), await contract.text()).toBe(200);
  expect(await contract.json()).toMatchObject({
    contract_version: "IPLF-025B/2026-08-10",
    migration_heads: [
      "20260810_0001",
      "20260810_0002",
      "20260810_0003",
      "20260810_0004",
    ],
    target_rule:
      "Exactly one of matter_id or ip_docket_id on target-owned rows.",
    forbidden_duplicates: [
      "ip_tasks",
      "ip_hearings",
      "ip_operational_deadlines",
      "ip_calendar_events",
      "ip_notification_intents",
    ],
  });

  const reconciliation = await page.request.get(
    `${PROD_API_BASE_URL}/api/ip/shared-work/reconciliation`,
  );
  expect(reconciliation.status(), await reconciliation.text()).toBe(200);
  const report = await reconciliation.json();
  expect(report).toMatchObject({
    contract_version: "IPLF-025B/2026-08-10",
    release_blocking: true,
    ready: true,
    notification_tenant_mismatch_rows: 0,
  });
  expect(report.owners).toHaveLength(6);
  for (const owner of report.owners as Array<{
    ready: boolean;
    invalid_target_rows: number;
    tenant_mismatch_rows: number;
  }>) {
    expect(owner.ready).toBe(true);
    expect(owner.invalid_target_rows).toBe(0);
    expect(owner.tenant_mismatch_rows).toBe(0);
  }
});

test("IPLF-025B production schedules, supersedes, and cancels unknown-time reminders at 360px", async ({
  page,
}) => {
  test.setTimeout(180_000);
  const identity = await signIn(page, IP_QA_CREDENTIALS);
  const headers = await csrfHeaders(page);
  const configurationResponse = await page.request.get(
    `${PROD_API_BASE_URL}/api/ip/workspace/configuration`,
  );
  expect(
    configurationResponse.status(),
    await configurationResponse.text(),
  ).toBe(200);
  let configurationStatus = (await configurationResponse.json()) as {
    configuration: { version: number; workspace_enabled: boolean } | null;
  };
  if (configurationStatus.configuration === null) {
    const configured = await page.request.put(
      `${PROD_API_BASE_URL}/api/ip/workspace/configuration`,
      {
        headers,
        data: {
          expected_version: null,
          enabled_asset_types: ["trademark"],
          jurisdictions: ["IN"],
          offices: ["IP India"],
          timezone: "Asia/Kolkata",
          holiday_calendar_key: "test-calendar",
          working_day_policy: { working_weekdays: [0, 1, 2, 3, 4] },
          document_taxonomy_version: "ip-taxonomy-2026.1",
          event_catalog_version: "ip-events-v1",
          deadline_rule_versions: { IN: "2026.1" },
          notification_channels: ["in_app", "email"],
          critical_event_policy: { escalation_after_minutes: 30 },
          escalation_owner_membership_id: identity.membership.id,
          provider_keys: [],
          provider_terms_version: null,
          accept_provider_terms: false,
        },
      },
    );
    expect(configured.status(), await configured.text()).toBe(200);
    configurationStatus = (await configured.json()) as typeof configurationStatus;
  }
  if (!configurationStatus.configuration?.workspace_enabled) {
    const enabled = await page.request.post(
      `${PROD_API_BASE_URL}/api/ip/workspace/enable`,
      {
        headers,
        data: {
          expected_config_version: configurationStatus.configuration!.version,
          enabled_automations: [],
        },
      },
    );
    expect(enabled.status(), await enabled.text()).toBe(200);
  }
  const readiness = await page.request.get(
    `${PROD_API_BASE_URL}/api/ip/readiness`,
  );
  expect(readiness.status(), await readiness.text()).toBe(200);
  expect(await readiness.json()).toMatchObject({ workspace_available: true });
  const canary = Date.now();
  const hearingOn = new Date(Date.now() + 180 * 24 * 60 * 60 * 1000);
  const rescheduledOn = new Date(hearingOn.getTime() + 24 * 60 * 60 * 1000);
  const hearingDate = hearingOn.toISOString().slice(0, 10);
  const rescheduledDate = rescheduledOn.toISOString().slice(0, 10);

  const createdDocket = await page.request.post(
    `${PROD_API_BASE_URL}/api/ip/dockets`,
    {
      headers,
      data: {
        title: `IPLF-025B production calendar canary ${canary}`,
        primary_identifier: `TM-IPLF-025B-PROD-${canary}`,
        particulars: {
          form_key: "TM-A",
          form_version: "2026.1",
          mark_kind: "word",
          representation: {
            text: "CALENDAR CANARY",
            evidence_reference: "qa:iplf-025b-production-calendar-canary",
          },
          classes: [
            { class_number: 42, specification: "Legal workflow software" },
          ],
          use_priority: null,
          parties: [{ role: "applicant", name: "CaseOps QA Bot LLP" }],
          agent: null,
          filing_manifest: [
            {
              key: "representation",
              label: "Mark representation",
              required: true,
              evidence_reference: "qa:iplf-025b-production-calendar-canary",
            },
          ],
        },
      },
    },
  );
  expect(createdDocket.status(), await createdDocket.text()).toBe(201);
  const docketId = (await createdDocket.json()).id as string;

  await page.setViewportSize({ width: 360, height: 900 });
  await page.goto(
    `${PROD_BASE_URL}/app/ip?docket=${encodeURIComponent(docketId)}`,
  );
  await expect(
    page.getByRole("heading", {
      name: "Hearings, reminders, and calendar copies",
    }),
  ).toBeVisible();
  await expect(page.getByLabel("Hearing date")).toBeVisible();
  await expect(page.getByLabel("Time precision")).toBeVisible();
  await expect(page.getByLabel("Virtual hearing link")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Preview recipients and policy" }),
  ).toBeVisible();
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(360);

  await page.getByLabel("Hearing date").fill(hearingDate);
  await page.getByLabel("Location").fill("Production QA registry room");
  await page
    .getByLabel("Virtual hearing link")
    .fill("https://meet.example.test/qa-hearing");
  await page
    .getByRole("button", { name: "Preview recipients and policy" })
    .click();
  const preview = page.getByTestId("ip-hearing-preview");
  await expect(preview).toContainText(
    "Date-based reminder only; no hearing time will be invented.",
  );
  await expect(preview).toContainText("48, 24 hours");
  await expect(preview).toContainText("email, in_app");

  const creation = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/api/ip/hearings" &&
      response.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Confirm hearing and reminders" })
    .click();
  const creationResponse = await creation;
  expect(creationResponse.status(), await creationResponse.text()).toBe(201);
  const hearingId = ((await creationResponse.json()) as { id: string }).id;
  const outcomes = page.getByLabel("Reminder delivery for Hearing");
  await expect(outcomes.getByText(/email .* queued/).first()).toBeVisible();
  await expect(outcomes.getByText(/in_app .* queued/).first()).toBeVisible();

  const initial = await page.request.get(
    `${PROD_API_BASE_URL}/api/ip/hearings?docket_id=${encodeURIComponent(docketId)}`,
  );
  expect(initial.status(), await initial.text()).toBe(200);
  const initialHearing = (await initial.json()).hearings.find(
    (row: { id: string }) => row.id === hearingId,
  );
  expect(initialHearing.hearing_time).toBeNull();
  expect(initialHearing.reminders).toHaveLength(4);
  expect(
    new Set(
      initialHearing.reminders.map((row: { channel: string }) => row.channel),
    ),
  ).toEqual(new Set(["email", "in_app"]));

  await page.getByLabel("Reschedule Hearing").fill(rescheduledDate);
  const reschedule = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === `/api/ip/hearings/${hearingId}` &&
      response.request().method() === "PATCH",
  );
  await page.getByRole("button", { name: "Reschedule" }).click();
  expect((await reschedule).status()).toBe(200);

  const afterReschedule = await page.request.get(
    `${PROD_API_BASE_URL}/api/ip/hearings?docket_id=${encodeURIComponent(docketId)}`,
  );
  expect(afterReschedule.status(), await afterReschedule.text()).toBe(200);
  const rescheduledHearing = (await afterReschedule.json()).hearings.find(
    (row: { id: string }) => row.id === hearingId,
  );
  const reminders = rescheduledHearing.reminders as Array<{
    status: string;
    schedule_generation: number;
  }>;
  expect(reminders.filter((row) => row.status === "cancelled")).toHaveLength(4);
  expect(reminders.filter((row) => row.status === "queued")).toHaveLength(4);
  expect(
    new Set(
      reminders
        .filter((row) => row.status === "cancelled")
        .map((row) => row.schedule_generation),
    ),
  ).toEqual(new Set([1]));
  expect(
    new Set(
      reminders
        .filter((row) => row.status === "queued")
        .map((row) => row.schedule_generation),
    ),
  ).toEqual(new Set([2]));

  const cancellation = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === `/api/ip/hearings/${hearingId}` &&
      response.request().method() === "PATCH",
  );
  await page.getByRole("button", { name: "Cancel hearing" }).click();
  expect((await cancellation).status()).toBe(200);
  const afterCancellation = await page.request.get(
    `${PROD_API_BASE_URL}/api/ip/hearings?docket_id=${encodeURIComponent(docketId)}`,
  );
  expect(afterCancellation.status(), await afterCancellation.text()).toBe(200);
  const cancelledHearing = (await afterCancellation.json()).hearings.find(
    (row: { id: string }) => row.id === hearingId,
  );
  expect(cancelledHearing.status).toBe("cancelled");
  expect(
    cancelledHearing.reminders.every(
      (row: { status: string }) => row.status === "cancelled",
    ),
  ).toBe(true);
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(360);
});
