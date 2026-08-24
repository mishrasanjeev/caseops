/** IPLF-049B / UJ-38: rectification, cancellation, and non-use proceedings. */

import { spawnSync } from "node:child_process";
import path from "node:path";

import {
  expect,
  request,
  test,
  type APIRequestContext,
  type Page,
} from "@playwright/test";

import { apiBaseUrl, e2eEnv, repoRoot } from "./support/env";

const PASSWORD = "PostRegistration2026!";

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
    "session.add(BillingSubscription(company_id=os.environ['CASEOPS_E2E_COMPANY_ID'],status='manual_active',segment='law_firm',source='iplf_049_playwright',externally_billable=False,entitlement_overrides_json={'ip_workspace': True}))",
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
      PYTHONPATH: [
        path.join(repoRoot, "apps", "api", "src"),
        process.env.PYTHONPATH,
      ]
        .filter(Boolean)
        .join(path.delimiter),
    },
  });
  expect(result.status, `${result.stdout}\n${result.stderr}`).toBe(0);
}

async function bootstrap(api: APIRequestContext) {
  const slug = `post-registration-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  const email = `owner-${slug}@example.com`;
  const response = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "IPLF 049 Post Registration LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Post Registration Partner",
      owner_email: email,
      owner_password: PASSWORD,
    },
  });
  expect(response.status(), await response.text()).toBe(200);
  const body = await response.json();
  grantIpEntitlement(body.company.id as string);
  return { ...body, slug, email };
}

async function enableWorkspace(
  api: APIRequestContext,
  tenant: { access_token: string; membership: { id: string } },
) {
  const headers = { Authorization: `Bearer ${tenant.access_token}` };
  const configured = await api.put(
    `${apiBaseUrl}/api/ip/workspace/configuration`,
    {
      headers,
      data: {
        expected_version: null,
        enabled_asset_types: ["trademark"],
        jurisdictions: ["IN"],
        offices: ["Trade Marks Registry Delhi"],
        timezone: "Asia/Kolkata",
        holiday_calendar_key: "post-registration-calendar",
        working_day_policy: { working_weekdays: [0, 1, 2, 3, 4] },
        document_taxonomy_version: "ip-taxonomy-2026.1",
        event_catalog_version: "ip-events-v1",
        deadline_rule_versions: { IN: "lawyer-reviewed-manual-only-v1" },
        notification_channels: ["in_app"],
        critical_event_policy: { escalation_after_minutes: 30 },
        escalation_owner_membership_id: tenant.membership.id,
        provider_keys: [],
        provider_terms_version: null,
        accept_provider_terms: false,
      },
    },
  );
  expect(configured.status(), await configured.text()).toBe(200);
  const enabled = await api.post(`${apiBaseUrl}/api/ip/workspace/enable`, {
    headers,
    data: {
      expected_config_version: (await configured.json()).configuration.version,
      enabled_automations: [],
    },
  });
  expect(enabled.status(), await enabled.text()).toBe(200);
  return headers;
}

async function createApplication(
  api: APIRequestContext,
  headers: Record<string, string>,
) {
  const response = await api.post(
    `${apiBaseUrl}/api/ip/trademark-applications/manual`,
    {
      headers,
      data: {
        title: "ASTER REGISTERED MARK",
        restricted: false,
        asset_title: "ASTER REGISTERED MARK",
        jurisdiction: "IN",
        office: "Trade Marks Registry Delhi",
        filing_phase: "draft",
        source_pending_identifier_allocation: false,
        application_number: {
          raw_value: "TM-APP-049-2026",
          source: "e2e registry fixture",
          effective_from: "2026-08-24",
          is_primary: true,
        },
        particulars: {
          form_key: "TM-A",
          form_version: "2026.1",
          mark_kind: "word",
          representation: { text: "ASTER", evidence_reference: "e2e:aster" },
          classes: [
            { class_number: 9, specification: "Downloadable legal software" },
          ],
          use_priority: null,
          parties: [
            { role: "applicant", name: "Registered Proprietor Limited" },
          ],
          agent: null,
          filing_manifest: [
            {
              key: "representation",
              label: "Mark representation",
              required: true,
              evidence_reference: "e2e:aster",
            },
          ],
        },
      },
    },
  );
  expect(response.status(), await response.text()).toBe(201);
  return response.json();
}

async function signIn(page: Page, slug: string, email: string): Promise<void> {
  await page.goto("/sign-in");
  await page.locator("#company-slug").fill(slug);
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(PASSWORD);
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  await page.waitForURL(/\/app(?:[/?]|$)/);
}

test("IPLF-049 completes UJ-38 and every governed exception path", async ({
  page,
}) => {
  test.setTimeout(300_000);
  page.setDefaultTimeout(20_000);
  const api = await request.newContext();
  const tenant = await bootstrap(api);
  const headers = await enableWorkspace(api, tenant);
  const application = await createApplication(api, headers);
  await signIn(page, tenant.slug, tenant.email);
  await page.goto(`/app/ip?docket=${application.docket.id}`);

  const workspace = page.getByTestId("ip-post-registration-workspace");
  await expect(workspace).toBeVisible();
  const create = workspace.getByTestId("ip-post-registration-create-form");
  await create.getByLabel("Proceeding type").selectOption("rectification");
  await create.getByLabel("Represented side").selectOption("claimant");
  await create.getByLabel("Proceeding number").fill("RECT-049-2026");
  await create
    .getByLabel("Number source")
    .fill("registry rectification record");
  const createdResponse = page.waitForResponse(
    (row) =>
      row
        .url()
        .endsWith(`/api/ip/dockets/${application.docket.id}/proceedings`) &&
      row.request().method() === "POST",
  );
  await create.getByRole("button", { name: "Create proceeding" }).click();
  const created = await createdResponse;
  expect(created.status(), await created.text()).toBe(201);
  const proceeding = await created.json();
  await expect(
    workspace.getByText("RECT-049-2026", { exact: true }),
  ).toBeVisible();

  const court = await api.post(
    `${apiBaseUrl}/api/ip/dockets/${application.docket.id}/proceedings`,
    {
      headers,
      data: {
        application_id: application.application.id,
        proceeding_kind: "court",
        side: "claimant",
        office: "Delhi High Court",
        jurisdiction: "IN",
        stage: "filed",
        origin_kind: "manual_intake",
      },
    },
  );
  expect(court.status(), await court.text()).toBe(201);
  const courtProceeding = await court.json();

  const profile = workspace.getByTestId("ip-post-registration-profile-form");
  await profile
    .getByLabel("Legal basis")
    .fill("Lawyer-confirmed statutory rectification basis.");
  await profile.getByLabel("Target right").fill("registration:TM-049-2026");
  await profile.getByLabel("Applicant").fill("Claimant Brands Private Limited");
  await profile.getByLabel("Respondent").fill("Registered Proprietor Limited");
  await profile.getByLabel("Class").fill("9");
  await profile
    .getByLabel("Challenged scope")
    .fill("Downloadable legal software");
  await profile
    .getByLabel("Grounds")
    .fill("Entry should be rectified on the confirmed basis.");
  await profile.getByLabel("Fee status").selectOption("paid");
  await profile.getByLabel("Fee reference").fill("fee-receipt:049");
  await profile.getByLabel("Service status").selectOption("served");
  await profile.getByLabel("Service reference").fill("service-proof:049");
  await profile
    .getByLabel("Legal authority")
    .fill("Trade Marks Act and Rules mapping:049");
  await profile.getByLabel("Legal source").fill("legal-source:049");
  await profile.getByText("Mutatis mutandis mapping").click();
  await profile
    .getByLabel("Mapped from rule")
    .fill("Opposition evidence provisions");
  await profile.getByLabel("Mapped provisions").fill("evidence sequence");
  await profile
    .getByLabel("Excluded provisions")
    .fill("opposition notice, opposition number");
  await profile
    .getByLabel("Lawyer confirmation")
    .fill("Counsel mapped only the provisions applicable to rectification.");
  await profile.getByLabel("Record source").fill("registry:rectification:049");
  await profile.getByLabel("Source documents").fill("document:petition:049");
  const savedResponse = page.waitForResponse(
    (row) =>
      row.url().endsWith("/post-registration-workspace") &&
      row.request().method() === "PUT",
  );
  await profile.getByRole("button", { name: "Confirm profile" }).click();
  const saved = await savedResponse;
  expect(saved.status(), await saved.text()).toBe(200);
  expect((await saved.json()).ready_for_stage_progression).toBe(true);
  await expect(
    workspace.getByText("Profile ready", { exact: true }),
  ).toBeVisible();

  const action = workspace.getByTestId("ip-post-registration-action-form");
  const recordAction = async (expectedStatus = 201) => {
    const response = page.waitForResponse(
      (row) =>
        row.url().endsWith("/post-registration-actions") &&
        row.request().method() === "POST",
    );
    await action.getByRole("button", { name: "Record action" }).click();
    const resolved = await response;
    expect(resolved.status(), await resolved.text()).toBe(expectedStatus);
    return resolved;
  };

  await action
    .getByLabel("Action", { exact: true })
    .selectOption("parallel_proceeding_link");
  await action
    .getByLabel("Parallel proceeding")
    .selectOption(courtProceeding.id);
  await action.getByLabel("Source reference").fill("court-link:049");
  await action.getByLabel("Source documents").fill("document:court-case:049");
  await recordAction();
  expect(proceeding.id).not.toBe(courtProceeding.id);

  await action
    .getByLabel("Action", { exact: true })
    .selectOption("stage_update");
  await action.getByLabel("Stage").selectOption("counterstatement_due");
  await action
    .getByLabel("Source reference")
    .fill("registry:counterstatement:049");
  await recordAction();
  await expect(
    workspace.getByText("Counterstatement Due", { exact: true }).first(),
  ).toBeVisible();

  await action
    .getByLabel("Action", { exact: true })
    .selectOption("interim_stay");
  await action.getByLabel("Source reference").fill("court:stay:049");
  await action
    .getByLabel("Authority reference")
    .fill("Delhi High Court interim stay order");
  await action.getByLabel("Source documents").fill("document:stay-order:049");
  await recordAction();
  await expect(
    workspace.getByText("Interim stay", { exact: true }),
  ).toBeVisible();

  await action
    .getByLabel("Action", { exact: true })
    .selectOption("disposition_candidate");
  await action
    .getByLabel("Candidate disposition")
    .selectOption("rectify_registration");
  await action
    .getByLabel("Legal effect")
    .fill("Rectify the challenged class 9 specification.");
  await action
    .getByLabel("Source reference")
    .fill("registry:disposition:blocked:049");
  await recordAction(409);

  await action
    .getByLabel("Action", { exact: true })
    .selectOption("stay_lifted");
  await action.getByLabel("Source reference").fill("court:stay-lifted:049");
  await action
    .getByLabel("Authority reference")
    .fill("Delhi High Court order lifting stay");
  await action
    .getByLabel("Source documents")
    .fill("document:stay-lift-order:049");
  await recordAction();
  await expect(
    workspace.getByText("Interim stay", { exact: true }),
  ).toHaveCount(0);

  await action
    .getByLabel("Action", { exact: true })
    .selectOption("disposition_candidate");
  await action
    .getByLabel("Candidate disposition")
    .selectOption("rectify_registration");
  await action
    .getByLabel("Legal effect")
    .fill("Rectify only the challenged class 9 specification.");
  await action
    .getByLabel("Source reference")
    .fill("registry:disposition:candidate:049");
  const candidateResponse = await recordAction();
  const candidateBody = await candidateResponse.json();
  const candidate = candidateBody.action_events.at(-1);
  expect(candidate.payload_json.registration_disposition_applied).toBe(false);

  await action
    .getByLabel("Action", { exact: true })
    .selectOption("disposition_review");
  await action.getByLabel("Disposition candidate").selectOption(candidate.id);
  await action.getByLabel("Review decision").selectOption("approved");
  await action
    .getByLabel("Authorized confirmation")
    .fill("Reviewing counsel approved the candidate legal effect.");
  await action.getByLabel("Source reference").fill("review:disposition:049");
  const reviewResponse = await recordAction();
  const reviewBody = await reviewResponse.json();
  expect(
    reviewBody.action_events.at(-1).payload_json
      .registration_disposition_applied,
  ).toBe(false);

  await action.getByLabel("Action", { exact: true }).selectOption("closure");
  await action.getByLabel("Stage").selectOption("settled");
  await action
    .getByLabel("Legal effect", { exact: true })
    .fill("Proceeding ends without automatic alteration of the register.");
  await action.getByLabel("Legal effect date").fill("2026-08-24");
  await action
    .getByLabel("Authorized confirmation")
    .fill("Counsel confirmed the executed settlement effect.");
  await action.getByLabel("Source reference").fill("settlement:049");
  await action.getByLabel("Source documents").fill("document:settlement:049");
  const closureResponse = await recordAction();
  expect((await closureResponse.json()).proceeding.stage).toBe("settled");

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(workspace).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await api.dispose();
});
