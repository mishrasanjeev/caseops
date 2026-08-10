import { spawnSync } from "node:child_process";
import path from "node:path";

import { expect, request, test, type APIRequestContext } from "@playwright/test";

import { apiBaseUrl, e2eEnv, repoRoot } from "./support/env";

const PASSWORD = "SharedWorkFoundation2026!";

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
    "session.add(BillingSubscription(company_id=os.environ['CASEOPS_E2E_COMPANY_ID'],status='manual_active',segment='law_firm',source='iplf_025a_playwright',externally_billable=False,entitlement_overrides_json={'ip_workspace': True}))",
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
  const slug = `shared-work-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  const response = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "IPLF 025A Shared Work LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Shared Work Owner",
      owner_email: `owner-${slug}@example.com`,
      owner_password: PASSWORD,
    },
  });
  expect(response.status(), await response.text()).toBe(200);
  const body = await response.json();
  grantIpEntitlement(body.company.id as string);
  return body;
}

test("IPLF-025A uses one tenant-safe shared owner for IP tasks, hearings, and deadlines", async () => {
  test.setTimeout(120_000);
  const api = await request.newContext();
  const tenant = await bootstrap(api);
  const headers = { Authorization: `Bearer ${tenant.access_token as string}` };

  const contract = await api.get(`${apiBaseUrl}/api/ip/shared-work/foundation-contract`, {
    headers,
  });
  expect(contract.status(), await contract.text()).toBe(200);
  expect(await contract.json()).toMatchObject({
    contract_version: "IPLF-025A/2026-08-10",
    migration_heads: ["20260810_0001", "20260810_0002", "20260810_0003"],
    forbidden_duplicates: [
      "ip_tasks",
      "ip_hearings",
      "ip_operational_deadlines",
      "ip_calendar_events",
      "ip_notification_intents",
    ],
  });

  const docket = await api.post(`${apiBaseUrl}/api/ip/dockets`, {
    headers,
    data: {
      title: "IPLF 025A shared work target",
      primary_identifier: `TM-SHARED-${Date.now()}`,
      particulars: {
        form_key: "TM-A",
        form_version: "2026.1",
        mark_kind: "word",
        representation: {
          text: "SHARED WORK FOUNDATION",
          evidence_reference: "attachment:shared-work-foundation",
        },
        classes: [{ class_number: 42, specification: "Legal workflow software" }],
        use_priority: null,
        parties: [{ role: "applicant", name: "Shared Work Foundation LLP" }],
        agent: null,
        filing_manifest: [
          {
            key: "representation",
            label: "Mark representation",
            required: true,
            evidence_reference: "attachment:shared-work-foundation",
          },
        ],
      },
    },
  });
  expect(docket.status(), await docket.text()).toBe(201);
  const docketId = (await docket.json()).id as string;

  const task = await api.post(`${apiBaseUrl}/api/ip/tasks`, {
    headers,
    data: {
      docket_id: docketId,
      title: "Review next hearing evidence",
      owner_membership_id: tenant.membership.id,
      priority: "high",
    },
  });
  expect(task.status(), await task.text()).toBe(201);
  expect(await task.json()).toMatchObject({
    target_type: "ip_docket",
    ip_docket_id: docketId,
  });

  const hearing = await api.post(`${apiBaseUrl}/api/ip/hearings`, {
    headers,
    data: {
      docket_id: docketId,
      hearing_on: "2026-10-01",
      forum_name: "Trade Marks Registry, Delhi",
      purpose: "Show-cause hearing",
      time_status: "session",
      session_label: "Morning board",
      hearing_mode: "hybrid",
      responsible_membership_id: tenant.membership.id,
    },
  });
  expect(hearing.status(), await hearing.text()).toBe(201);

  const deadline = await api.post(`${apiBaseUrl}/api/ip/operational-deadlines`, {
    headers,
    data: {
      docket_id: docketId,
      source: "hearing",
      kind: "hearing_note",
      title: "Prepare hearing note",
      due_on: "2026-09-28",
      assignee_membership_id: tenant.membership.id,
    },
  });
  expect(deadline.status(), await deadline.text()).toBe(201);

  const reconciliation = await api.get(
    `${apiBaseUrl}/api/ip/shared-work/reconciliation`,
    { headers },
  );
  expect(reconciliation.status(), await reconciliation.text()).toBe(200);
  const report = await reconciliation.json();
  expect(report).toMatchObject({
    contract_version: "IPLF-025A/2026-08-10",
    release_blocking: true,
    ready: true,
  });
  expect(report.owners.find((row: { owner: string }) => row.owner === "tasks")).toMatchObject({
    ip_target_rows: 1,
    invalid_target_rows: 0,
    tenant_mismatch_rows: 0,
    ready: true,
  });
  expect(
    report.owners.find((row: { owner: string }) => row.owner === "next_hearing_history"),
  ).toMatchObject({ ip_target_rows: 1, ready: true });

  await api.dispose();
});
