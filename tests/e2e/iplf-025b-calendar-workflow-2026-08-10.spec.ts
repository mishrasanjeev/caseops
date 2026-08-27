import { spawnSync } from "node:child_process";
import path from "node:path";

import { expect, request, test, type APIRequestContext, type Page } from "@playwright/test";

import { apiBaseUrl, e2eEnv, repoRoot } from "./support/env";

const PASSWORD = "CalendarWorkflow2026!";

function grantIpEntitlement(companyId: string): void {
  const python =
    process.platform === "win32"
      ? path.join(repoRoot, "apps", "api", ".venv", "Scripts", "python.exe")
      : path.join(repoRoot, "apps", "api", ".venv", "bin", "python");
  const script = [
    "import os",
    "from caseops_api.db.models import BillingSubscription",
    "from caseops_api.db.session import get_session_factory",
    "session=get_session_factory()()",
    "session.add(BillingSubscription(company_id=os.environ['CASEOPS_E2E_COMPANY_ID'],status='manual_active',segment='law_firm',source='iplf_025b_playwright',externally_billable=False,entitlement_overrides_json={'ip_workspace': True}))",
    "session.commit()",
    "session.close()",
  ].join("; ");
  const result = spawnSync(python, ["-c", script], {
    cwd: repoRoot,
    encoding: "utf8",
    env: {
      ...process.env,
      ...e2eEnv,
      CASEOPS_E2E_COMPANY_ID: companyId,
      PYTHONPATH: [path.join(repoRoot, "apps", "api", "src"), process.env.PYTHONPATH]
        .filter(Boolean)
        .join(path.delimiter),
    },
  });
  expect(result.status, `${result.stdout}\n${result.stderr}`).toBe(0);
}

async function bootstrap(api: APIRequestContext) {
  const slug = `calendar-workflow-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  const email = `owner-${slug}@example.com`;
  const response = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "IPLF 025B Calendar Workflow LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Calendar Workflow Owner",
      owner_email: email,
      owner_password: PASSWORD,
    },
  });
  expect(response.status(), await response.text()).toBe(200);
  const body = await response.json();
  grantIpEntitlement(body.company.id as string);
  return { ...body, slug, email };
}

async function signIn(page: Page, slug: string, email: string): Promise<void> {
  const login = await page.request.post(`${apiBaseUrl}/api/auth/login`, {
    data: { company_slug: slug, email, password: PASSWORD },
  });
  expect(login.status(), await login.text()).toBe(200);
  const session = (await login.json()) as {
    access_token: string;
    company: unknown;
    user: unknown;
    membership: unknown;
    capabilities?: unknown;
  };
  await page.context().addCookies([{
    name: "caseops_session",
    value: session.access_token,
    url: apiBaseUrl,
    httpOnly: true,
    secure: false,
    sameSite: "Lax",
  }]);
  await page.addInitScript((context) => {
    window.localStorage.setItem("caseops.session.context", JSON.stringify(context));
  }, {
    company: session.company,
    user: session.user,
    membership: session.membership,
    capabilities: session.capabilities,
  });
}

test("IPLF-025B schedules unknown-time reminders, exposes outcomes, and supersedes on 360px", async ({
  page,
}) => {
  test.setTimeout(150_000);
  const api = await request.newContext();
  const tenant = await bootstrap(api);
  const headers = { Authorization: `Bearer ${tenant.access_token as string}` };

  const configured = await api.put(`${apiBaseUrl}/api/ip/workspace/configuration`, {
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
      escalation_owner_membership_id: tenant.membership.id,
      provider_keys: [],
      provider_terms_version: null,
      accept_provider_terms: false,
    },
  });
  expect(configured.status(), await configured.text()).toBe(200);
  const configVersion = (await configured.json()).configuration.version as number;
  const enabled = await api.post(`${apiBaseUrl}/api/ip/workspace/enable`, {
    headers,
    data: { expected_config_version: configVersion, enabled_automations: [] },
  });
  expect(enabled.status(), await enabled.text()).toBe(200);

  const docket = await api.post(`${apiBaseUrl}/api/ip/dockets`, {
    headers,
    data: {
      title: "IPLF 025B hearing docket",
      primary_identifier: `TM-CALENDAR-${Date.now()}`,
      particulars: {
        form_key: "TM-A",
        form_version: "2026.1",
        mark_kind: "word",
        representation: {
          text: "CALENDAR WORKFLOW",
          evidence_reference: "attachment:calendar-workflow",
        },
        classes: [{ class_number: 42, specification: "Legal workflow software" }],
        use_priority: null,
        parties: [{ role: "applicant", name: "Calendar Workflow LLP" }],
        agent: null,
        filing_manifest: [
          {
            key: "representation",
            label: "Mark representation",
            required: true,
            evidence_reference: "attachment:calendar-workflow",
          },
        ],
      },
    },
  });
  expect(docket.status(), await docket.text()).toBe(201);
  const docketId = (await docket.json()).id as string;

  await page.setViewportSize({ width: 360, height: 820 });
  await signIn(page, tenant.slug as string, tenant.email as string);
  await page.goto(`/app/ip?docket=${encodeURIComponent(docketId)}`);
  await page.getByRole("tab", { name: "Hearings and deadlines" }).click();
  await expect(page.getByRole("heading", { name: "Hearings, reminders, and calendar copies" })).toBeVisible();
  await expect(page.getByLabel("Hearing date")).toBeVisible();
  await expect(page.getByLabel("Time precision")).toBeVisible();
  await expect(page.getByLabel("Virtual hearing link")).toBeVisible();
  await expect(page.getByRole("button", { name: "Preview recipients and policy" })).toBeVisible();

  await page.getByLabel("Hearing date").fill("2026-12-15");
  await page.getByLabel("Location").fill("Registry hearing room 2");
  await page.getByLabel("Virtual hearing link").fill("https://meet.example.test/ip-hearing");
  await page.getByRole("button", { name: "Preview recipients and policy" }).click();
  const preview = page.getByTestId("ip-hearing-preview");
  await expect(preview).toContainText("Date-based reminder only; no hearing time will be invented.");
  await expect(preview).toContainText("48, 24 hours");
  await expect(preview).toContainText("email, in_app");

  const creation = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/api/ip/hearings" &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Confirm hearing and reminders" }).click();
  expect((await creation).status()).toBe(201);
  await expect(page.getByRole("heading", { name: "Hearing", exact: true })).toBeVisible();
  await expect(page.getByLabel("Reminder delivery for Hearing").getByText(/email · queued/).first()).toBeVisible();
  await expect(page.getByLabel("Reminder delivery for Hearing").getByText(/in_app · queued/).first()).toBeVisible();

  const listed = await api.get(`${apiBaseUrl}/api/ip/hearings?docket_id=${docketId}`, {
    headers,
  });
  expect(listed.status(), await listed.text()).toBe(200);
  const initial = (await listed.json()).hearings[0];
  expect(initial.hearing_time).toBeNull();
  expect(initial.time_confirmation_required).toBe(true);
  expect(initial.current_schedule_generation).toBe(1);
  expect(initial.reminders).toHaveLength(4);
  expect(new Set(initial.reminders.map((row: { channel: string }) => row.channel))).toEqual(
    new Set(["email", "in_app"]),
  );

  await page.getByLabel("Reschedule Hearing").fill("2026-12-16");
  const reschedule = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === `/api/ip/hearings/${initial.id}` &&
      response.request().method() === "PATCH",
  );
  await page.getByRole("button", { name: "Reschedule" }).click();
  expect((await reschedule).status()).toBe(200);
  const after = await api.get(`${apiBaseUrl}/api/ip/hearings?docket_id=${docketId}`, {
    headers,
  });
  const reminders = (await after.json()).hearings[0].reminders as Array<{
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

  // IPLF-UJ-10-EXC-01/02: uncertainty remains explicit, and the user can
  // inspect the immutable replacement chain before recording a published time.
  await expect(page.getByText(/Time confirmation pending/)).toBeVisible();
  await expect(page.getByText("Superseded by generation 2")).toBeVisible();
  await expect(page.getByText("Current schedule")).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    ),
  ).toBeLessThanOrEqual(1);
  const confirmTime = page.getByRole("button", { name: "Confirm published time" });
  await expect(confirmTime).toBeDisabled();
  await page.getByLabel("Published time for Hearing").fill("14:30");
  const timeConfirmation = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === `/api/ip/hearings/${initial.id}` &&
      response.request().method() === "PATCH",
  );
  await confirmTime.click();
  expect((await timeConfirmation).status()).toBe(200);

  const afterTimeConfirmation = await api.get(
    `${apiBaseUrl}/api/ip/hearings?docket_id=${docketId}`,
    { headers },
  );
  expect(afterTimeConfirmation.status(), await afterTimeConfirmation.text()).toBe(200);
  const confirmed = (await afterTimeConfirmation.json()).hearings[0];
  expect(confirmed.time_status).toBe("exact");
  expect(confirmed.hearing_time).toBe("14:30:00");
  expect(confirmed.time_confirmation_required).toBe(false);
  expect(confirmed.current_schedule_generation).toBe(3);
  expect(
    confirmed.reminders.filter(
      (row: { schedule_generation: number; is_superseded: boolean }) =>
        row.schedule_generation < 3 && row.is_superseded,
    ),
  ).toHaveLength(8);
  expect(
    confirmed.reminders.filter(
      (row: { schedule_generation: number; status: string }) =>
        row.schedule_generation === 3 && row.status === "queued",
    ),
  ).toHaveLength(4);

  await api.dispose();
});
