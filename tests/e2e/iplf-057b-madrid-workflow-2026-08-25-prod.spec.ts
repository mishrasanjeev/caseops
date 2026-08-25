/** IPLF-057B dated production acceptance for UJ-35 Madrid workflows. */

import {
  expect,
  request,
  test,
  type APIRequestContext,
  type APIResponse,
  type Page,
} from "@playwright/test";

const WEB = (process.env.PROD_BASE_URL ?? "https://caseops.ai").trim();
const API = (process.env.PROD_API_BASE_URL ?? "https://api.caseops.ai").trim();
const SLUG = (process.env.CASEOPS_IP_QA_SLUG ?? "caseops-ip-qa").trim();
const EMAIL = (
  process.env.CASEOPS_IP_QA_EMAIL ?? "ip-qa-bot@caseops.ai"
).trim();

function required(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required.`);
  return value;
}

async function expectStatus(
  response: Pick<APIResponse, "status" | "text">,
  expected: number,
  label: string,
): Promise<void> {
  const detail =
    response.status() === expected ? "" : ` ${await response.text()}`;
  expect(response.status(), `${label}.${detail}`).toBe(expected);
}

async function authenticate(page: Page) {
  const response = await page.request.post(`${API}/api/auth/login`, {
    data: {
      company_slug: SLUG,
      email: EMAIL,
      password: required("CASEOPS_IP_QA_PASSWORD"),
    },
  });
  await expectStatus(response, 200, "IP QA sign-in");
  const session = await response.json();
  await page.goto(`${WEB}/`);
  await page.evaluate(
    (context) => {
      window.localStorage.setItem(
        "caseops.session.context",
        JSON.stringify(context),
      );
    },
    {
      company: session.company,
      user: session.user,
      membership: session.membership,
      capabilities: session.capabilities,
    },
  );
  return session;
}

async function createBasicApplication(
  api: APIRequestContext,
  headers: Record<string, string>,
  runId: string,
) {
  const response = await api.post(
    `${API}/api/ip/trademark-applications/manual`,
    {
      headers,
      data: {
        title: `IPLF-057B ASTER BASIC ${runId}`,
        restricted: false,
        asset_title: `ASTER ${runId}`,
        jurisdiction: "IN",
        office: "Trade Marks Registry Delhi",
        filing_phase: "filed",
        source_pending_identifier_allocation: false,
        application_number: {
          raw_value: `TM-MAD-${runId}`,
          source: "dated production acceptance receipt",
          effective_from: "2026-08-25",
          is_primary: true,
        },
        particulars: {
          form_key: "TM-A",
          form_version: "2026.1",
          mark_kind: "word",
          representation: {
            text: `ASTER ${runId}`,
            evidence_reference: `prod:iplf057b:basic:${runId}`,
          },
          classes: [
            { class_number: 9, specification: "Downloadable legal software" },
            { class_number: 42, specification: "Legal software as a service" },
          ],
          use_priority: null,
          parties: [{ role: "applicant", name: "Aster Labs Private Limited" }],
          agent: null,
          filing_manifest: [
            {
              key: "representation",
              label: "Mark representation",
              required: true,
              evidence_reference: `prod:iplf057b:basic:${runId}`,
            },
          ],
        },
      },
    },
  );
  await expectStatus(response, 201, "basic application creation");
  return response.json();
}

async function createRecord(
  api: APIRequestContext,
  headers: Record<string, string>,
  runId: string,
  data: Record<string, unknown>,
) {
  const response = await api.post(`${API}/api/ip/international-registrations`, {
    headers,
    data: {
      docket_title: `IPLF-057B Madrid ${runId}`,
      restricted: false,
      international_application_number: null,
      ir_number: null,
      wipo_reference: `WIPO-PROD-${runId}-${Math.random()}`,
      holder_name: "Aster Labs Private Limited",
      mark_name: `ASTER ${runId}`,
      designated_office: null,
      classes: [9, 42],
      goods_services: {
        "9": "Downloadable legal software",
        "42": "Legal software as a service",
      },
      priority_claims: [],
      wipo_status: null,
      national_status: null,
      local_agent_name: null,
      source_url: "https://www.wipo.int/madrid/monitor/",
      source_reference: `prod:iplf057b:${runId}:${Math.random()}`,
      source_retrieved_at: new Date().toISOString(),
      application_date: null,
      international_registration_date: null,
      notification_date: null,
      publication_date: null,
      statement_date: null,
      dependency_end_date: null,
      renewal_due_date: null,
      ...data,
    },
  });
  await expectStatus(response, 201, "Madrid record creation");
  return response.json();
}

async function workspace(
  api: APIRequestContext,
  headers: Record<string, string>,
  recordId: string,
) {
  const response = await api.get(
    `${API}/api/ip/international-registrations/${recordId}/workspace`,
    { headers },
  );
  await expectStatus(response, 200, "Madrid workspace");
  return response.json();
}

async function act(
  api: APIRequestContext,
  headers: Record<string, string>,
  membershipId: string,
  recordId: string,
  actionKind: string,
  authority: string,
  runId: string,
  input: Record<string, unknown> = {},
) {
  const current = await workspace(api, headers, recordId);
  const response = await api.post(
    `${API}/api/ip/international-registrations/${recordId}/actions`,
    {
      headers,
      data: {
        expected_version: current.record.version,
        expected_lifecycle_version: current.docket.lifecycle_version,
        action_kind: actionKind,
        authority,
        effective_at: new Date().toISOString(),
        responsible_membership_id: membershipId,
        reason: `IPLF-057B production acceptance ${actionKind}.`,
        source_url: ["wipo", "office_of_origin", "national_office"].includes(
          authority,
        )
          ? "https://www.wipo.int/madrid/monitor/"
          : null,
        source_reference: `prod:iplf057b:${actionKind}:${runId}:${Math.random()}`,
        source_retrieved_at: new Date().toISOString(),
        evidence_refs: [`prod:evidence:${actionKind}:${runId}`],
        document_refs: [],
        deadline_refs: [],
        cost_item_refs: [],
        details: {},
        ...input,
      },
    },
  );
  await expectStatus(response, 201, actionKind);
  return response.json();
}

test("IPLF-057B production proves UJ-35 and every Madrid exception", async ({
  page,
}) => {
  test.setTimeout(300_000);
  page.setDefaultTimeout(25_000);
  const expectedSha = required("CASEOPS_EXPECTED_RELEASE_SHA");
  const [apiIdentity, webIdentity] = await Promise.all([
    page.request.get(`${API}/api/build`),
    page.request.get(`${WEB}/api/release-identity`),
  ]);
  await expectStatus(apiIdentity, 200, "API release identity");
  await expectStatus(webIdentity, 200, "web release identity");
  expect((await apiIdentity.json()).release_sha).toBe(expectedSha);
  expect((await webIdentity.json()).release_sha).toBe(expectedSha);

  const session = await authenticate(page);
  const headers = { Authorization: `Bearer ${session.access_token}` };
  const api = await request.newContext();
  const runId = `${Date.now()}`;

  const readinessResponse = await api.get(
    `${API}/api/admin/provider-operations/readiness`,
    { headers },
  );
  await expectStatus(readinessResponse, 200, "provider readiness");
  const readiness = new Map(
    (await readinessResponse.json()).providers.map(
      (row: { provider: string }) => [row.provider, row],
    ),
  );
  expect(readiness.get("wipo-madrid")).toEqual(
    expect.objectContaining({
      configured: false,
      enabled: false,
      external_calls_enabled: false,
      adapter_contract: expect.objectContaining({
        endpoint_paths: [],
        implemented_capabilities: [],
      }),
    }),
  );

  const basic = await createBasicApplication(api, headers, runId);
  const registration = await createRecord(api, headers, runId, {
    docket_title: `IPLF-057B international registration ${runId}`,
    record_kind: "international_registration",
    direction: "outbound",
    basic_application_id: basic.application.id,
    office_of_origin: "IP India",
    form_kind: "MM2",
    parent_registration_id: null,
    designated_member_code: null,
    jurisdiction: null,
    designation_kind: null,
    designation_effective_date: null,
  });
  await act(
    api,
    headers,
    session.membership.id,
    registration.id,
    "form_prepared",
    "internal",
    runId,
  );
  await act(
    api,
    headers,
    session.membership.id,
    registration.id,
    "office_of_origin_certified",
    "office_of_origin",
    runId,
  );
  const recorded = await act(
    api,
    headers,
    session.membership.id,
    registration.id,
    "international_registration_recorded",
    "internal",
    runId,
    {
      ir_number: `IR-PROD-${runId}`,
      international_registration_date: "2026-08-25",
    },
  );
  expect(recorded.record.ir_number).toBe(`IR-PROD-${runId}`);

  const india = await createRecord(api, headers, runId, {
    docket_title: `IPLF-057B India designation ${runId}`,
    record_kind: "international_designation",
    direction: "outbound",
    parent_registration_id: registration.id,
    basic_application_id: null,
    office_of_origin: null,
    designated_member_code: "IN",
    designated_office: "Trade Marks Registry India",
    jurisdiction: "IN",
    designation_kind: "original",
    designation_effective_date: "2026-08-25",
    form_kind: null,
  });
  const eu = await createRecord(api, headers, runId, {
    docket_title: `IPLF-057B EU designation ${runId}`,
    record_kind: "international_designation",
    direction: "outbound",
    parent_registration_id: registration.id,
    basic_application_id: null,
    office_of_origin: null,
    designated_member_code: "EM",
    designated_office: "EUIPO",
    jurisdiction: "EM",
    designation_kind: "subsequent",
    designation_effective_date: "2026-08-26",
    form_kind: null,
  });

  const impact = await act(
    api,
    headers,
    session.membership.id,
    registration.id,
    "central_attack_impact_review",
    "internal",
    runId,
    {
      details: {
        impact_scope: [registration.id, india.id, eu.id],
        recommended_action:
          "Review dependency evidence and jurisdiction-specific conversion options.",
      },
    },
  );
  expect(impact.impact_review_only).toBe(true);
  expect(impact.record.wipo_status).toBeNull();

  const refusalCandidate = await act(
    api,
    headers,
    session.membership.id,
    india.id,
    "source_snapshot",
    "national_office",
    runId,
    {
      national_status: "provisional_refusal",
      source_url: "https://ipindia.gov.in/trademark/",
    },
  );
  expect(refusalCandidate.status_applied).toBe(false);
  expect(
    (await workspace(api, headers, india.id)).record.national_status,
  ).toBeNull();
  const refusalDecision = await act(
    api,
    headers,
    session.membership.id,
    india.id,
    "source_reconciliation",
    "internal",
    runId,
    {
      reconciles_event_id: refusalCandidate.event.id,
      reconciliation_decision: "same_fact",
    },
  );
  expect(refusalDecision.record.national_status).toBe("provisional_refusal");
  expect(
    (await workspace(api, headers, eu.id)).record.national_status,
  ).toBeNull();

  const wipoCandidate = await act(
    api,
    headers,
    session.membership.id,
    eu.id,
    "source_snapshot",
    "wipo",
    runId,
    { wipo_status: "notified" },
  );
  const nationalCandidate = await act(
    api,
    headers,
    session.membership.id,
    eu.id,
    "source_snapshot",
    "national_office",
    runId,
    {
      national_status: "examination_pending",
      source_url: "https://euipo.europa.eu/ohimportal/",
    },
  );
  const conflict = await workspace(api, headers, eu.id);
  expect(
    conflict.unresolved_source_candidates.map((row: { id: string }) => row.id),
  ).toEqual(
    expect.arrayContaining([
      wipoCandidate.event.id,
      nationalCandidate.event.id,
    ]),
  );
  expect(conflict.record.wipo_status).toBeNull();
  expect(conflict.record.national_status).toBeNull();

  const agent = await act(
    api,
    headers,
    session.membership.id,
    india.id,
    "local_agent_instruction",
    "local_agent",
    runId,
    { local_agent_name: "Delhi Madrid Production Counsel" },
  );
  expect(agent.record.local_agent_name).toBe("Delhi Madrid Production Counsel");
  expect(agent.record.wipo_status).toBeNull();
  expect(agent.event.payload_json.authority).toBe("local_agent");

  await page.setViewportSize({ width: 360, height: 800 });
  await page.goto(`${WEB}/app/ip/madrid`);
  await expect(
    page.getByRole("heading", { name: "Madrid portfolio" }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Refresh" })).toBeVisible();
  await expect(page.getByRole("button", { name: "New record" })).toBeVisible();
  for (const name of [
    "Status and sources",
    "Designations",
    "Deadlines and evidence",
    "History",
  ]) {
    const tab = page.getByRole("tab", { name });
    await expect(tab).toBeVisible();
    const box = await tab.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(360);
    expect(box!.width).toBeGreaterThan(80);
  }
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth >
        document.documentElement.clientWidth + 1,
    ),
  ).toBe(false);

  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole("button").filter({ hasText: "IN" }).first().click();
  await expect(page.getByText("National: provisional_refusal")).toBeVisible();
  await expect(page.getByText("Delhi Madrid Production Counsel")).toBeVisible();
  await page.getByRole("tab", { name: "History" }).click();
  const sourceLinks = page.getByRole("link", {
    name: /prod:iplf057b:source_snapshot/i,
  });
  expect(await sourceLinks.count()).toBeGreaterThan(0);
  for (const link of await sourceLinks.all()) {
    await expect(link).toHaveAttribute("href", /^https:\/\/ipindia\.gov\.in\//);
  }

  await page.goto(`${WEB}/guide`);
  await expect(
    page.getByRole("heading", { name: "Madrid international registrations" }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Madrid portfolio" }),
  ).toHaveAttribute("href", "/app/ip/madrid");
  await page.goto(`${WEB}/law-firms`);
  await expect(
    page.getByRole("heading", { name: "Madrid international portfolio" }),
  ).toBeVisible();
  await expect(
    page.getByText(/not a claim of live provider sync/i),
  ).toBeVisible();

  await api.dispose();
});
