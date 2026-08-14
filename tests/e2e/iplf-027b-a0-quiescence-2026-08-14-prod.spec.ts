import { randomBytes } from "node:crypto";

import {
  expect,
  request as playwrightRequest,
  test,
  type APIRequestContext,
  type APIResponse,
} from "@playwright/test";

const PROD_BASE_URL = "https://caseops.ai";
const PROD_API_BASE_URL = "https://api.caseops.ai";
const IP_QA_SLUG = "caseops-ip-qa";
const IP_QA_EMAIL = "ip-qa-bot@caseops.ai";

const A0_PREDECESSOR_SHA = "3177f0176305e8790f40c3f771daebe595087955";
const FIXTURE_DOCKET_IDENTIFIER = "TM-IPLF-027B-A0-FIXTURE";
const FIXTURE_CALENDAR_KEY = "caseops-ip-qa-iplf-027b-a0-calendar";
const FIXTURE_RULE_KEY = "caseops-ip-qa-iplf-027b-a0-deadline";
const FIXTURE_RULE_SOURCE_ID = "caseops-ip-qa-iplf-027b-a0-source-v1";
const FIXTURE_SELECTION_ANCHOR_TITLE = "IPLF-027B A0 tenant-selection anchor";
const FIXTURE_CALENDAR_HASH = "a".repeat(64);
const FIXTURE_RULE_HASH = "b".repeat(64);
const SYNTHETIC_MATTER_TITLE_PREFIX = "IPLF-027B A0 synthetic matter ";
const SYNTHETIC_MATTER_CODE_PREFIX = "IP-A0-";

type A0Mode = "prepare" | "verify";

type AuthIdentity = {
  access_token: string;
  company: { slug: string };
  membership: { id: string; role: string };
};

type CompanyUser = {
  membership_id: string;
  role: string;
  email: string;
  membership_active: boolean;
  user_active: boolean;
};

type SyntheticAdmin = {
  email: string;
  password: string;
  membershipId: string;
};

type DocketRecord = {
  id: string;
  matter_id: string | null;
  primary_identifier: string | null;
};

type MatterRecord = {
  id: string;
  company_id: string;
  title: string;
  matter_code: string;
  matter_type: string | null;
  client_name: string | null;
  status: string;
  practice_area: string;
  forum_level: string;
  description: string | null;
  is_active: boolean;
  lifecycle_version: number;
  updated_at: string;
};

type MatterListPage = {
  company_id: string;
  matters: MatterRecord[];
  next_cursor: string | null;
};

type RuleRecord = {
  id: string;
  key: string;
  rule_kind: string;
  jurisdiction: string;
  office: string | null;
  right_kind: string;
  proceeding_kind: string | null;
  role: string | null;
  stage: string;
  version: number;
  status: string;
  source_record_id: string;
  source_hash: string;
  engine_compatibility: string;
  definition: Record<string, unknown>;
};

type CalendarRecord = {
  id: string;
  key: string;
  version: number;
  status: string;
  source_hash: string;
  timezone: string;
};

type DeadlineRecord = {
  id: string;
  docket_id: string;
  rule_version_id: string;
  calendar_version_id: string;
  matter_deadline_id: string | null;
  supersedes_deadline_id: string | null;
  title: string;
  result_on: string | null;
  state: string;
  version: number;
  override_reason: string | null;
  override_evidence_ref: string | null;
  completed_evidence_ref: string | null;
  responsibilities: Array<Record<string, unknown>>;
};

type DeadlineWorkspace = {
  docket_id: string;
  rules: RuleRecord[];
  calendars: CalendarRecord[];
  deadlines: DeadlineRecord[];
  automation_state: string;
};

type RuleImpact = {
  rule_version_id: string;
  impact_token: string;
  company_policy_count: number;
};

type DeadlineImpact = {
  deadline_id: string;
  expected_version: number;
  impact_token: string;
  operational_deadline_ids: string[];
  notification_intent_ids: string[];
  unrelated_work_preserved: boolean;
};

const CALENDAR_PROPOSAL = {
  key: FIXTURE_CALENDAR_KEY,
  name: "CaseOps IP QA A0 legal calendar",
  jurisdiction: "IN",
  office: "IP India",
  timezone: "Asia/Kolkata",
  weekend_days: [5, 6],
  holidays: [],
  exceptional_working_days: [],
  source_priority: ["synthetic_release_fixture"],
  source_reference: "qa:iplf-027b-a0-calendar-source",
  source_hash: FIXTURE_CALENDAR_HASH,
  effective_from: "2026-01-01",
  effective_until: null,
};

function ruleProposal(calendar: CalendarRecord): Record<string, unknown> {
  const definition = {
    deadline_kind: "legal_deadline",
    trigger_kind: "synthetic_a0_acceptance_event",
    duration_value: 1,
    duration_unit: "days",
    calendar_method: "calendar_days",
    direction: "after",
    include_base_date: false,
    next_working_day: false,
    extension_days: 0,
    rule_citation: "Synthetic IPLF-027B A0 acceptance rule; no legal effect",
  };
  return {
    key: FIXTURE_RULE_KEY,
    rule_kind: "deadline",
    jurisdiction: "IN",
    office: "IP India",
    right_kind: "trademark",
    proceeding_kind: "application",
    role: "applicant",
    stage: "synthetic_a0_acceptance",
    source_record_id: FIXTURE_RULE_SOURCE_ID,
    source_hash: FIXTURE_RULE_HASH,
    source_reference: "qa:iplf-027b-a0-rule-source",
    effective_from: "2026-01-01",
    effective_until: null,
    engine_compatibility: "caseops-ip-deadline-v1",
    definition,
    fixtures: [
      {
        id: "calendar-day-determinism",
        fixture_kind: "positive",
        calculation: {
          ...definition,
          base_date: "2026-08-14",
          base_date_certainty: "certain",
          rule_version_id: "iplf-027b-a0-fixture-rule",
          source_version: FIXTURE_RULE_SOURCE_ID,
          engine_version: "caseops-ip-deadline-v1",
          calendar: {
            calendar_version_id: calendar.id,
            timezone: calendar.timezone,
            weekend_days: [5, 6],
            holidays: [],
            exceptional_working_days: [],
            source_reference: CALENDAR_PROPOSAL.source_reference,
            source_hash: calendar.source_hash,
          },
        },
        expected_state: "candidate",
        expected_result_on: "2026-08-15",
        evidence_reference: "qa:iplf-027b-a0-rule-fixture",
      },
    ],
  };
}

function required(name: string): string {
  const value = process.env[name]?.trim() ?? "";
  if (!value) throw new Error(`${name} is required for production proof.`);
  return value;
}

function assertCanonicalProductionOrigins(): void {
  expect(IP_QA_SLUG).toBe("caseops-ip-qa");
  expect(IP_QA_EMAIL).toBe("ip-qa-bot@caseops.ai");
  for (const [value, expectedOrigin] of [
    [PROD_BASE_URL, "https://caseops.ai"],
    [PROD_API_BASE_URL, "https://api.caseops.ai"],
  ] as const) {
    const parsed = new URL(value);
    expect(parsed.origin).toBe(expectedOrigin);
    expect(parsed.protocol).toBe("https:");
    expect(parsed.username).toBe("");
    expect(parsed.password).toBe("");
    expect(parsed.port).toBe("");
    expect(parsed.pathname).toBe("/");
    expect(parsed.search).toBe("");
    expect(parsed.hash).toBe("");
  }
}

function selectedMode(): A0Mode {
  const value = (process.env.CASEOPS_IP_A0_PROD_MODE ?? "verify").trim();
  if (value !== "prepare" && value !== "verify") {
    throw new Error(
      "CASEOPS_IP_A0_PROD_MODE must be exactly 'prepare' or 'verify'.",
    );
  }
  return value;
}

function authHeaders(token: string): Record<string, string> {
  return { Authorization: `Bearer ${token}` };
}

async function jsonResponse<T>(
  response: APIResponse,
  expectedStatus: number,
  operation: string,
): Promise<T> {
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    body = { non_json_response: true };
  }
  expect(response.status(), `${operation}: ${JSON.stringify(body)}`).toBe(
    expectedStatus,
  );
  return body as T;
}

async function authenticate(
  email: string,
  password: string,
): Promise<AuthIdentity> {
  const loginApi = await playwrightRequest.newContext({ maxRedirects: 0 });
  try {
    const response = await loginApi.post(
      `${PROD_API_BASE_URL}/api/auth/login`,
      {
        data: { email, password, company_slug: IP_QA_SLUG },
        maxRedirects: 0,
      },
    );
    expect(response.status(), "Synthetic IP QA sign-in must succeed.").toBe(
      200,
    );
    const identity = (await response.json()) as AuthIdentity;
    expect(identity.access_token).toBeTruthy();
    expect(identity.company.slug).toBe(IP_QA_SLUG);
    expect(identity.membership.id).toBeTruthy();
    return identity;
  } finally {
    await loginApi.dispose();
  }
}

async function assertExactRelease(api: APIRequestContext): Promise<string> {
  const expectedSha = required("CASEOPS_EXPECTED_RELEASE_SHA").toLowerCase();
  expect(expectedSha).toMatch(/^[0-9a-f]{40}$/);
  const [apiIdentityResponse, webIdentityResponse] = await Promise.all([
    api.get(`${PROD_API_BASE_URL}/api/build`),
    api.get(`${PROD_BASE_URL}/api/release-identity`),
  ]);
  const apiIdentity = await jsonResponse<{ release_sha: string }>(
    apiIdentityResponse,
    200,
    "read API release identity",
  );
  const webIdentity = await jsonResponse<{ release_sha: string }>(
    webIdentityResponse,
    200,
    "read web release identity",
  );
  expect(apiIdentity.release_sha).toBe(expectedSha);
  expect(webIdentity.release_sha).toBe(expectedSha);
  return expectedSha;
}

function newest<T extends { version: number }>(rows: T[]): T | undefined {
  return [...rows].sort((left, right) => right.version - left.version)[0];
}

function activeRule(workspace: DeadlineWorkspace): RuleRecord | undefined {
  return newest(
    workspace.rules.filter(
      (row) => row.key === FIXTURE_RULE_KEY && row.status === "active",
    ),
  );
}

function activeCalendar(
  workspace: DeadlineWorkspace,
): CalendarRecord | undefined {
  return newest(
    workspace.calendars.filter(
      (row) => row.key === FIXTURE_CALENDAR_KEY && row.status === "active",
    ),
  );
}

async function findFixtureDocket(
  api: APIRequestContext,
  ownerToken: string,
): Promise<DocketRecord | undefined> {
  const headers = authHeaders(ownerToken);
  const listed = await jsonResponse<{ dockets: DocketRecord[] }>(
    await api.get(`${PROD_API_BASE_URL}/api/ip/dockets`, { headers }),
    200,
    "list IP QA dockets for the deterministic A0 fixture",
  );
  return listed.dockets.find(
    (row) => row.primary_identifier === FIXTURE_DOCKET_IDENTIFIER,
  );
}

async function createFixtureDocket(
  api: APIRequestContext,
  ownerToken: string,
): Promise<DocketRecord> {
  const existing = await findFixtureDocket(api, ownerToken);
  if (existing) return existing;

  return jsonResponse<DocketRecord>(
    await api.post(`${PROD_API_BASE_URL}/api/ip/dockets`, {
      headers: authHeaders(ownerToken),
      data: {
        title: "IPLF-027B A0 deterministic production fixture",
        primary_identifier: FIXTURE_DOCKET_IDENTIFIER,
        restricted: false,
        particulars: {
          form_key: "TM-A",
          form_version: "2026.1",
          mark_kind: "word",
          representation: {
            text: "A0 QUIESCENCE FIXTURE",
            evidence_reference: "qa:iplf-027b-a0-fixture",
          },
          classes: [
            {
              class_number: 42,
              specification: "Synthetic legal workflow acceptance testing",
            },
          ],
          use_priority: null,
          parties: [{ role: "applicant", name: "CaseOps Synthetic QA" }],
          agent: null,
          filing_manifest: [
            {
              key: "representation",
              label: "Synthetic representation",
              required: true,
              evidence_reference: "qa:iplf-027b-a0-fixture",
            },
          ],
        },
      },
    }),
    201,
    "create deterministic A0 fixture docket",
  );
}

async function loadWorkspace(
  api: APIRequestContext,
  token: string,
  docketId: string,
): Promise<DeadlineWorkspace> {
  const body = await jsonResponse<DeadlineWorkspace>(
    await api.get(
      `${PROD_API_BASE_URL}/api/ip/dockets/${docketId}/deadline-workspace`,
      { headers: authHeaders(token) },
    ),
    200,
    "reload legal-deadline workspace",
  );
  expect(body.docket_id).toBe(docketId);
  expect(body.automation_state).toBe("explicit_confirmation_only");
  expect(
    body.rules.filter(
      (row) => row.key === FIXTURE_RULE_KEY && row.status === "active",
    ),
    "The deterministic A0 rule must never have split active versions.",
  ).toHaveLength(activeRule(body) ? 1 : 0);
  expect(
    body.calendars.filter(
      (row) => row.key === FIXTURE_CALENDAR_KEY && row.status === "active",
    ),
    "The deterministic A0 calendar must never have split active versions.",
  ).toHaveLength(activeCalendar(body) ? 1 : 0);
  return body;
}

async function readRuleImpact(
  api: APIRequestContext,
  token: string,
  ruleId: string,
): Promise<RuleImpact> {
  const impact = await jsonResponse<RuleImpact>(
    await api.get(
      `${PROD_API_BASE_URL}/api/ip/deadline-rules/${ruleId}/impact`,
      { headers: authHeaders(token) },
    ),
    200,
    "read rule impact",
  );
  expect(impact.rule_version_id).toBe(ruleId);
  expect(impact.impact_token).toMatch(/^[0-9a-f]{64}$/);
  return impact;
}

async function proveTenantRuleSelection(
  api: APIRequestContext,
  ownerToken: string,
  docketId: string,
  workspace: DeadlineWorkspace,
  rule: RuleRecord,
  calendar: CalendarRecord,
): Promise<boolean> {
  const anchor = workspace.deadlines.find(
    (row) =>
      row.rule_version_id === rule.id &&
      row.calendar_version_id === calendar.id &&
      row.title === FIXTURE_SELECTION_ANCHOR_TITLE,
  );
  const response = await api.post(
    `${PROD_API_BASE_URL}/api/ip/dockets/${docketId}/deadlines`,
    {
      headers: authHeaders(ownerToken),
      data: {
        title: FIXTURE_SELECTION_ANCHOR_TITLE,
        rule_version_id: rule.id,
        // After the one durable anchor exists, this absent calendar makes the
        // canonical consumer prove the current tenant policy without adding
        // another deadline or audit event.
        calendar_version_id: anchor
          ? "00000000-0000-0000-0000-000000000000"
          : calendar.id,
        base_date: "2026-08-14",
        base_date_certainty: "certain",
        date_precision: "date",
        is_critical: false,
      },
    },
  );
  if (!anchor && response.status() === 201) {
    const created = (await response.json()) as DeadlineRecord;
    expect(created).toMatchObject({
      docket_id: docketId,
      rule_version_id: rule.id,
      calendar_version_id: calendar.id,
      state: "candidate",
      version: 1,
    });
    return true;
  }

  const body = (await response.json()) as {
    status?: number;
    detail?: string;
  };
  expect(
    response.status(),
    `probe current QA rule selection: ${JSON.stringify(body)}`,
  ).toBe(409);
  if (body.detail === "Company policy has not selected this rule.") {
    return false;
  }
  expect(body).toMatchObject({
    status: 409,
    detail: "An active company calendar is required.",
  });
  return true;
}

async function createSyntheticAdmin(
  api: APIRequestContext,
  ownerToken: string,
  label: string,
): Promise<SyntheticAdmin> {
  const nonce = `${Date.now()}-${randomBytes(5).toString("hex")}`;
  const email = `iplf-027b-a0-${label}-${nonce}@example.com`;
  const password = `${randomBytes(24).toString("base64url")}aA1!`;
  const created = await jsonResponse<CompanyUser>(
    await api.post(`${PROD_API_BASE_URL}/api/companies/current/users`, {
      headers: authHeaders(ownerToken),
      data: {
        full_name: `IPLF-027B A0 synthetic ${label}`,
        email,
        password,
        role: "admin",
      },
    }),
    200,
    `create synthetic ${label} admin`,
  );
  expect(created.role).toBe("admin");
  return { email, password, membershipId: created.membership_id };
}

async function deactivateSyntheticAdmin(
  api: APIRequestContext,
  ownerToken: string,
  membershipId: string,
): Promise<void> {
  const deactivated = await jsonResponse<{
    membership_active: boolean;
    user_active: boolean;
  }>(
    await api.patch(
      `${PROD_API_BASE_URL}/api/companies/current/users/${membershipId}`,
      {
        headers: authHeaders(ownerToken),
        data: { is_active: false },
      },
    ),
    200,
    "deactivate temporary A0 preparation admin",
  );
  expect(deactivated.membership_active).toBe(false);
  expect(deactivated.user_active).toBe(false);
}

function isReservedPreparationAdmin(user: CompanyUser): boolean {
  return (
    user.role === "admin" &&
    /^iplf-027b-a0-(?:reviewer|legal-approver)-\d{13}-[0-9a-f]{10}@example\.com$/.test(
      user.email,
    )
  );
}

async function reconcilePreparationAdmins(
  api: APIRequestContext,
  ownerToken: string,
): Promise<void> {
  const listUsers = async (): Promise<CompanyUser[]> => {
    const body = await jsonResponse<{ users: CompanyUser[] }>(
      await api.get(`${PROD_API_BASE_URL}/api/companies/current/users`, {
        headers: authHeaders(ownerToken),
      }),
      200,
      "list reserved A0 preparation admins",
    );
    return body.users;
  };
  const stale = (await listUsers()).filter(
    (user) =>
      isReservedPreparationAdmin(user) &&
      (user.membership_active || user.user_active),
  );
  const cleanup = await Promise.allSettled(
    stale.map((user) =>
      deactivateSyntheticAdmin(api, ownerToken, user.membership_id),
    ),
  );
  expect(
    cleanup.filter((result) => result.status === "rejected"),
    "Every stale reserved A0 preparation admin must be deactivated.",
  ).toEqual([]);
  expect(
    (await listUsers()).filter(
      (user) =>
        isReservedPreparationAdmin(user) &&
        (user.membership_active || user.user_active),
    ),
  ).toEqual([]);
}

function assertFixtureShape(rule: RuleRecord, calendar: CalendarRecord): void {
  expect(calendar).toMatchObject({
    key: FIXTURE_CALENDAR_KEY,
    status: "active",
    source_hash: FIXTURE_CALENDAR_HASH,
    timezone: "Asia/Kolkata",
  });
  expect(rule).toMatchObject({
    key: FIXTURE_RULE_KEY,
    rule_kind: "deadline",
    jurisdiction: "IN",
    office: "IP India",
    right_kind: "trademark",
    proceeding_kind: "application",
    role: "applicant",
    stage: "synthetic_a0_acceptance",
    status: "active",
    source_record_id: FIXTURE_RULE_SOURCE_ID,
    source_hash: FIXTURE_RULE_HASH,
    engine_compatibility: "caseops-ip-deadline-v1",
    definition: {
      deadline_kind: "legal_deadline",
      trigger_kind: "synthetic_a0_acceptance_event",
      duration_value: 1,
      duration_unit: "days",
      calendar_method: "calendar_days",
      next_working_day: false,
    },
  });
}

async function prepareFixture(
  api: APIRequestContext,
  owner: AuthIdentity,
): Promise<void> {
  await reconcilePreparationAdmins(api, owner.access_token);
  const fixtureDocket = await createFixtureDocket(api, owner.access_token);
  let workspace = await loadWorkspace(
    api,
    owner.access_token,
    fixtureDocket.id,
  );
  let calendar = activeCalendar(workspace);
  let rule = activeRule(workspace);
  let selected = false;
  if (calendar && rule) {
    assertFixtureShape(rule, calendar);
    selected = await proveTenantRuleSelection(
      api,
      owner.access_token,
      fixtureDocket.id,
      workspace,
      rule,
      calendar,
    );
  }
  if (calendar && rule && selected) {
    return;
  }

  const createdMembershipIds: string[] = [];
  try {
    const reviewerAccount = await createSyntheticAdmin(
      api,
      owner.access_token,
      "reviewer",
    );
    createdMembershipIds.push(reviewerAccount.membershipId);
    const reviewer = await authenticate(
      reviewerAccount.email,
      reviewerAccount.password,
    );
    expect(reviewer.membership.id).toBe(reviewerAccount.membershipId);
    expect(reviewer.membership.role).toBe("admin");

    const approverAccount = await createSyntheticAdmin(
      api,
      owner.access_token,
      "legal-approver",
    );
    createdMembershipIds.push(approverAccount.membershipId);
    const approver = await authenticate(
      approverAccount.email,
      approverAccount.password,
    );
    expect(approver.membership.id).toBe(approverAccount.membershipId);
    expect(approver.membership.role).toBe("admin");

    if (!calendar) {
      const candidate =
        newest(
          workspace.calendars.filter(
            (row) =>
              row.key === FIXTURE_CALENDAR_KEY &&
              row.status === "candidate" &&
              row.source_hash === FIXTURE_CALENDAR_HASH,
          ),
        ) ??
        (await jsonResponse<CalendarRecord>(
          await api.post(`${PROD_API_BASE_URL}/api/ip/working-calendars`, {
            headers: authHeaders(owner.access_token),
            data: CALENDAR_PROPOSAL,
          }),
          201,
          "propose the deterministic A0 calendar",
        ));
      calendar = await jsonResponse<CalendarRecord>(
        await api.post(
          `${PROD_API_BASE_URL}/api/ip/working-calendars/${candidate.id}/activate`,
          {
            headers: authHeaders(approver.access_token),
            data: {
              reason:
                "Independent review of the synthetic A0 acceptance calendar.",
              conflict_reviewed: true,
            },
          },
        ),
        200,
        "activate the deterministic A0 calendar",
      );
    }

    if (!rule || !selected) {
      const proposal = ruleProposal(calendar);
      const candidate =
        newest(
          workspace.rules.filter(
            (row) =>
              row.key === FIXTURE_RULE_KEY &&
              row.status === "candidate" &&
              row.source_record_id === FIXTURE_RULE_SOURCE_ID &&
              row.source_hash === FIXTURE_RULE_HASH,
          ),
        ) ??
        (await jsonResponse<RuleRecord>(
          await api.post(`${PROD_API_BASE_URL}/api/ip/deadline-rules`, {
            headers: authHeaders(owner.access_token),
            data: proposal,
          }),
          201,
          "propose the deterministic A0 rule",
        ));
      await jsonResponse<RuleRecord>(
        await api.post(
          `${PROD_API_BASE_URL}/api/ip/deadline-rules/${candidate.id}/activate`,
          {
            headers: authHeaders(approver.access_token),
            data: {
              reviewer_membership_id: reviewer.membership.id,
              impact_acknowledged: true,
              impact_reason:
                "Reviewed the synthetic fixture impact before A0 routing.",
              select_for_company: true,
              auto_confirm_eligible: false,
              internal_target_policy: {},
            },
          },
        ),
        200,
        "activate and select the deterministic A0 rule",
      );
    }

    workspace = await loadWorkspace(api, owner.access_token, fixtureDocket.id);
    calendar = activeCalendar(workspace);
    rule = activeRule(workspace);
    expect(
      calendar,
      "A0 calendar must be active after preparation.",
    ).toBeTruthy();
    expect(rule, "A0 rule must be active after preparation.").toBeTruthy();
    assertFixtureShape(rule!, calendar!);
    selected = await proveTenantRuleSelection(
      api,
      owner.access_token,
      fixtureDocket.id,
      workspace,
      rule!,
      calendar!,
    );
    expect(selected).toBe(true);
    const impact = await readRuleImpact(api, owner.access_token, rule!.id);
    expect(impact.company_policy_count).toBeGreaterThanOrEqual(1);
  } finally {
    const cleanup = await Promise.allSettled(
      createdMembershipIds
        .reverse()
        .map((membershipId) =>
          deactivateSyntheticAdmin(api, owner.access_token, membershipId),
        ),
    );
    expect(
      cleanup.filter((result) => result.status === "rejected"),
      "Every temporary A0 preparation admin must be deactivated.",
    ).toEqual([]);
  }
}

function isoDateAfter(days: number): string {
  const value = new Date();
  value.setUTCDate(value.getUTCDate() + days);
  return value.toISOString().slice(0, 10);
}

function addIsoDays(value: string, days: number): string {
  const date = new Date(`${value}T00:00:00.000Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

function isReservedSyntheticMatter(matter: MatterRecord): boolean {
  return (
    /^IPLF-027B A0 synthetic matter \d{13}-[0-9a-f]{8}$/.test(matter.title) &&
    /^IP-A0-\d{13}-[0-9A-F]{8}$/.test(matter.matter_code) &&
    matter.matter_type === "synthetic_release_canary" &&
    matter.client_name === "CaseOps Synthetic QA" &&
    matter.practice_area === "intellectual_property" &&
    matter.forum_level === "tribunal" &&
    matter.description ===
      "Synthetic production acceptance data only; no client or legal effect."
  );
}

async function readMatter(
  api: APIRequestContext,
  ownerToken: string,
  matterId: string,
): Promise<MatterRecord> {
  return jsonResponse<MatterRecord>(
    await api.get(`${PROD_API_BASE_URL}/api/matters/${matterId}`, {
      headers: authHeaders(ownerToken),
    }),
    200,
    `read synthetic A0 matter ${matterId}`,
  );
}

async function listReservedSyntheticMatters(
  api: APIRequestContext,
  ownerToken: string,
): Promise<MatterRecord[]> {
  const matches: MatterRecord[] = [];
  const seenCursors = new Set<string>();
  let cursor: string | null = null;
  do {
    const body: MatterListPage = await jsonResponse<MatterListPage>(
      await api.get(`${PROD_API_BASE_URL}/api/matters/`, {
        headers: authHeaders(ownerToken),
        params: {
          q: SYNTHETIC_MATTER_TITLE_PREFIX.trim(),
          limit: 200,
          ...(cursor ? { cursor } : {}),
        },
      }),
      200,
      "list prior reserved synthetic A0 matters",
    );
    for (const matter of body.matters) {
      expect(matter.company_id).toBe(body.company_id);
      if (isReservedSyntheticMatter(matter)) matches.push(matter);
    }
    cursor = body.next_cursor;
    if (cursor) {
      expect(
        seenCursors.has(cursor),
        "Reserved synthetic Matter pagination must advance.",
      ).toBe(false);
      seenCursors.add(cursor);
    }
  } while (cursor);
  return matches;
}

async function listOperationalDockets(
  api: APIRequestContext,
  ownerToken: string,
): Promise<DocketRecord[]> {
  const body = await jsonResponse<{ dockets: DocketRecord[] }>(
    await api.get(`${PROD_API_BASE_URL}/api/ip/dockets`, {
      headers: authHeaders(ownerToken),
    }),
    200,
    "list operational dockets for synthetic Matter cleanup",
  );
  return body.dockets;
}

async function disposeSyntheticMatter(
  api: APIRequestContext,
  ownerToken: string,
  matterId: string,
  expectedCompanyId: string,
  docketIds: string[],
): Promise<void> {
  let current = await readMatter(api, ownerToken, matterId);
  expect(current.company_id).toBe(expectedCompanyId);
  expect(
    isReservedSyntheticMatter(current),
    "Cleanup must target only the exact reserved A0 synthetic Matter shape.",
  ).toBe(true);
  if (current.status !== "disposed") {
    expect(["intake", "active", "on_hold"]).toContain(current.status);
    expect(current.is_active).toBe(true);
    const priorLifecycleVersion = current.lifecycle_version;
    current = await jsonResponse<MatterRecord>(
      await api.patch(
        `${PROD_API_BASE_URL}/api/matters/${matterId}/lifecycle/status`,
        {
          headers: authHeaders(ownerToken),
          data: {
            to_status: "disposed",
            expected_from_status: current.status,
            expected_updated_at: current.updated_at,
            reason:
              "Dispose the synthetic IPLF-027B A0 canary after persistence proof.",
          },
        },
      ),
      200,
      "dispose the reserved synthetic A0 Matter",
    );
    expect(current.lifecycle_version).toBe(priorLifecycleVersion + 1);
  }
  expect(current).toMatchObject({
    id: matterId,
    company_id: expectedCompanyId,
    status: "disposed",
    is_active: false,
  });
  const persisted = await readMatter(api, ownerToken, matterId);
  expect(persisted).toMatchObject({
    id: matterId,
    company_id: expectedCompanyId,
    status: "disposed",
    is_active: false,
    lifecycle_version: current.lifecycle_version,
  });
  for (const docketId of docketIds) {
    const workspace = await api.get(
      `${PROD_API_BASE_URL}/api/ip/dockets/${docketId}/deadline-workspace`,
      { headers: authHeaders(ownerToken) },
    );
    expect(
      workspace.status(),
      `Disposed Matter child docket ${docketId} must be non-operational.`,
    ).toBe(404);
  }
}

async function reconcilePriorSyntheticMatters(
  api: APIRequestContext,
  ownerToken: string,
): Promise<void> {
  const reserved = await listReservedSyntheticMatters(api, ownerToken);
  const operational = reserved.filter(
    (matter) => matter.status !== "disposed" || matter.is_active,
  );
  if (operational.length === 0) return;
  const dockets = await listOperationalDockets(api, ownerToken);
  for (const matter of operational) {
    await disposeSyntheticMatter(
      api,
      ownerToken,
      matter.id,
      matter.company_id,
      dockets
        .filter((docket) => docket.matter_id === matter.id)
        .map((docket) => docket.id),
    );
  }
  expect(
    (await listReservedSyntheticMatters(api, ownerToken)).filter(
      (matter) => matter.status !== "disposed" || matter.is_active,
    ),
    "No prior reserved A0 synthetic Matter may remain operational.",
  ).toEqual([]);
}

async function createFreshMatter(
  api: APIRequestContext,
  owner: AuthIdentity,
): Promise<{ matter: MatterRecord; nonce: string }> {
  const nonce = `${Date.now()}-${randomBytes(4).toString("hex")}`;
  const headers = authHeaders(owner.access_token);
  const matter = await jsonResponse<MatterRecord>(
    await api.post(`${PROD_API_BASE_URL}/api/matters/`, {
      headers,
      data: {
        title: `${SYNTHETIC_MATTER_TITLE_PREFIX}${nonce}`,
        matter_code: `${SYNTHETIC_MATTER_CODE_PREFIX}${nonce}`.toUpperCase(),
        matter_type: "synthetic_release_canary",
        client_name: "CaseOps Synthetic QA",
        status: "intake",
        practice_area: "intellectual_property",
        forum_level: "tribunal",
        description:
          "Synthetic production acceptance data only; no client or legal effect.",
      },
    }),
    200,
    "create fresh synthetic A0 matter",
  );
  return { matter, nonce };
}

async function activateFreshMatterAndCreateDocket(
  api: APIRequestContext,
  owner: AuthIdentity,
  matter: MatterRecord,
  nonce: string,
): Promise<DocketRecord> {
  const headers = authHeaders(owner.access_token);
  const conflictCheck = await jsonResponse<{ status: string }>(
    await api.post(
      `${PROD_API_BASE_URL}/api/matters/${matter.id}/conflict-checks`,
      {
        headers,
        data: {
          opposing_party_name: `QAX${randomBytes(24).toString("hex")}`,
          related_party_names: [],
        },
      },
    ),
    200,
    "record the fresh synthetic matter conflict check",
  );
  expect(conflictCheck.status).toBe("cleared");

  const activatedMatter = await jsonResponse<MatterRecord>(
    await api.patch(`${PROD_API_BASE_URL}/api/matters/${matter.id}`, {
      headers,
      data: {
        status: "active",
        expected_updated_at: matter.updated_at,
      },
    }),
    200,
    "activate the fresh synthetic matter with its optimistic token",
  );
  expect(activatedMatter).toMatchObject({
    id: matter.id,
    company_id: matter.company_id,
    status: "active",
    is_active: true,
  });
  expect(isReservedSyntheticMatter(activatedMatter)).toBe(true);

  const docket = await jsonResponse<DocketRecord>(
    await api.post(`${PROD_API_BASE_URL}/api/ip/dockets`, {
      headers,
      data: {
        title: `IPLF-027B A0 legal-deadline canary ${nonce}`,
        matter_id: activatedMatter.id,
        primary_identifier: `TM-A0-${nonce}`.toUpperCase(),
        restricted: false,
        particulars: {
          form_key: "TM-A",
          form_version: "2026.1",
          mark_kind: "word",
          representation: {
            text: "A0 DEADLINE CANARY",
            evidence_reference: `qa:iplf-027b-a0:${nonce}`,
          },
          classes: [
            {
              class_number: 42,
              specification: "Synthetic legal workflow acceptance testing",
            },
          ],
          use_priority: null,
          parties: [{ role: "applicant", name: "CaseOps Synthetic QA" }],
          agent: null,
          filing_manifest: [
            {
              key: "representation",
              label: "Synthetic representation",
              required: true,
              evidence_reference: `qa:iplf-027b-a0:${nonce}`,
            },
          ],
        },
      },
    }),
    201,
    "create fresh synthetic A0 docket",
  );
  return docket;
}

async function expectQuiesced(
  response: APIResponse,
  operation: string,
): Promise<void> {
  const body = await jsonResponse<Record<string, unknown>>(
    response,
    503,
    operation,
  );
  expect(response.headers()["content-type"]).toContain(
    "application/problem+json",
  );
  expect(body).toMatchObject({
    status: 503,
    code: "ip_rule_governance_quiesced",
    reason: "rollout_disabled",
    rollout_flag: "ip_rule_governance_enabled",
    detail:
      "IP rule-governance mutations are temporarily unavailable during the controlled ownership rollout drain.",
  });
}

async function verifyQuiescenceAndDeadlineWriters(
  api: APIRequestContext,
  owner: AuthIdentity,
): Promise<void> {
  const headers = authHeaders(owner.access_token);
  await reconcilePriorSyntheticMatters(api, owner.access_token);
  const readiness = await jsonResponse<{
    workspace_available: boolean;
    manual_docketing_available: boolean;
  }>(
    await api.get(`${PROD_API_BASE_URL}/api/ip/readiness`, { headers }),
    200,
    "read A0 workspace readiness",
  );
  expect(readiness.workspace_available).toBe(true);
  expect(readiness.manual_docketing_available).toBe(true);

  const fixtureDocket = await findFixtureDocket(api, owner.access_token);
  expect(
    fixtureDocket,
    "Run the pre-T_ROUTE prepare mode; the deterministic fixture docket is absent.",
  ).toBeTruthy();
  if (!fixtureDocket) throw new Error("A0 fixture docket is absent.");
  const fixtureWorkspace = await loadWorkspace(
    api,
    owner.access_token,
    fixtureDocket.id,
  );
  const rule = activeRule(fixtureWorkspace);
  const calendar = activeCalendar(fixtureWorkspace);
  expect(
    rule,
    "Run the pre-T_ROUTE prepare mode; the selected A0 rule fixture is absent.",
  ).toBeTruthy();
  expect(
    calendar,
    "Run the pre-T_ROUTE prepare mode; the active A0 calendar fixture is absent.",
  ).toBeTruthy();
  const selectionAnchor = fixtureWorkspace.deadlines.find(
    (row) =>
      row.title === FIXTURE_SELECTION_ANCHOR_TITLE &&
      row.rule_version_id === rule!.id &&
      row.calendar_version_id === calendar!.id,
  );
  expect(
    selectionAnchor,
    "Run the pre-T_ROUTE prepare mode; the tenant-selection anchor is absent.",
  ).toBeTruthy();
  assertFixtureShape(rule!, calendar!);
  expect(
    await proveTenantRuleSelection(
      api,
      owner.access_token,
      fixtureDocket.id,
      fixtureWorkspace,
      rule!,
      calendar!,
    ),
  ).toBe(true);

  const ruleImpact = await readRuleImpact(api, owner.access_token, rule!.id);
  expect(ruleImpact.company_policy_count).toBeGreaterThanOrEqual(1);

  const { matter, nonce } = await createFreshMatter(api, owner);
  let freshDocketId: string | undefined;
  try {
    expect(matter).toMatchObject({ status: "intake", is_active: true });
    expect(isReservedSyntheticMatter(matter)).toBe(true);
    const docket = await activateFreshMatterAndCreateDocket(
      api,
      owner,
      matter,
      nonce,
    );
    freshDocketId = docket.id;
    expect(docket.matter_id).toBe(matter.id);
    let workspace = await loadWorkspace(api, owner.access_token, docket.id);
    expect(activeRule(workspace)?.id).toBe(rule!.id);
    expect(activeCalendar(workspace)?.id).toBe(calendar!.id);

    const incompatibleProposal = {
      ...ruleProposal(calendar!),
      // If the A0 fence is accidentally open, this exact existing key plus an
      // incompatible scope fails with 409 before any candidate or audit write.
      right_kind: "patent",
    };
    await expectQuiesced(
      await api.post(`${PROD_API_BASE_URL}/api/ip/deadline-rules`, {
        headers,
        data: incompatibleProposal,
      }),
      "probe fenced rule proposal",
    );
    await expectQuiesced(
      await api.post(
        `${PROD_API_BASE_URL}/api/ip/deadline-rules/${rule!.id}/activate`,
        {
          headers,
          // The active row would reject this without mutation if the fence were
          // unexpectedly open.
          data: {
            reviewer_membership_id: owner.membership.id,
            select_for_company: true,
          },
        },
      ),
      "probe fenced rule activation",
    );
    await expectQuiesced(
      await api.post(
        `${PROD_API_BASE_URL}/api/ip/deadline-rules/${rule!.id}/transition`,
        {
          headers,
          // A deliberately invalid token makes the probe non-mutating even if
          // the fence regresses open.
          data: {
            impact_token: "a0-safe-non-matching-impact-token",
            reason: "Verify the A0 ownership drain without changing the rule.",
            emergency_disable: false,
          },
        },
      ),
      "probe fenced rule transition",
    );

    workspace = await loadWorkspace(api, owner.access_token, docket.id);
    expect(activeRule(workspace)?.id).toBe(rule!.id);
    const postProbeImpact = await readRuleImpact(
      api,
      owner.access_token,
      rule!.id,
    );
    expect(postProbeImpact.impact_token).toBe(ruleImpact.impact_token);

    const baseDate = isoDateAfter(30);
    const recalculatedBaseDate = addIsoDays(baseDate, 1);
    const overrideResultDate = addIsoDays(baseDate, 10);
    const title = `IPLF-027B A0 legal deadline ${Date.now()}`;
    const proposed = await jsonResponse<DeadlineRecord>(
      await api.post(
        `${PROD_API_BASE_URL}/api/ip/dockets/${docket.id}/deadlines`,
        {
          headers,
          data: {
            title,
            rule_version_id: rule!.id,
            calendar_version_id: calendar!.id,
            base_date: baseDate,
            base_date_certainty: "certain",
            date_precision: "date",
            is_critical: false,
          },
        },
      ),
      201,
      "propose a legal deadline while rule governance is quiesced",
    );
    expect(proposed).toMatchObject({
      docket_id: docket.id,
      rule_version_id: rule!.id,
      calendar_version_id: calendar!.id,
      result_on: addIsoDays(baseDate, 1),
      state: "candidate",
      version: 1,
    });

    const responsibilities = [
      {
        membership_id: owner.membership.id,
        role: "primary",
        accepted: true,
        replacement_source: "synthetic_release_canary",
        escalation_policy: {},
      },
    ];
    const confirmed = await jsonResponse<DeadlineRecord>(
      await api.post(
        `${PROD_API_BASE_URL}/api/ip/deadlines/${proposed.id}/confirm`,
        {
          headers,
          data: {
            expected_version: proposed.version,
            responsibilities,
            internal_target_on: null,
            reminder_offsets_days: [],
          },
        },
      ),
      200,
      "confirm the proposed legal deadline",
    );
    expect(confirmed.id).toBe(proposed.id);
    expect(confirmed.state).toBe("confirmed");
    expect(confirmed.version).toBe(2);
    expect(confirmed.matter_deadline_id).toBeTruthy();
    expect(confirmed.responsibilities).toHaveLength(1);

    const recalculated = await jsonResponse<DeadlineRecord>(
      await api.post(
        `${PROD_API_BASE_URL}/api/ip/deadlines/${proposed.id}/recalculate`,
        {
          headers,
          data: {
            expected_version: confirmed.version,
            trigger_event_id: null,
            base_date: recalculatedBaseDate,
            base_date_certainty: "certain",
            reason:
              "Synthetic A0 canary recalculation after a sourced date update.",
            evidence_reference: "qa:iplf-027b-a0:recalculation",
          },
        },
      ),
      200,
      "recalculate the confirmed legal deadline",
    );
    expect(recalculated).toMatchObject({
      docket_id: docket.id,
      supersedes_deadline_id: confirmed.id,
      result_on: addIsoDays(recalculatedBaseDate, 1),
      state: "candidate",
      version: 1,
    });

    const deadlineImpact = await jsonResponse<DeadlineImpact>(
      await api.get(
        `${PROD_API_BASE_URL}/api/ip/deadlines/${confirmed.id}/impact`,
        { headers },
      ),
      200,
      "read confirmed deadline impact",
    );
    expect(deadlineImpact).toMatchObject({
      deadline_id: confirmed.id,
      expected_version: confirmed.version,
      unrelated_work_preserved: true,
    });
    expect(deadlineImpact.impact_token).toMatch(/^[0-9a-f]{64}$/);
    expect(deadlineImpact.notification_intent_ids).toEqual([]);
    expect(deadlineImpact.operational_deadline_ids).toContain(
      confirmed.matter_deadline_id,
    );

    const overridden = await jsonResponse<DeadlineRecord>(
      await api.post(
        `${PROD_API_BASE_URL}/api/ip/deadlines/${confirmed.id}/override`,
        {
          headers,
          data: {
            expected_version: confirmed.version,
            new_result_on: overrideResultDate,
            reason: "Synthetic A0 canary sourced override.",
            evidence_reference: "qa:iplf-027b-a0:override",
            impact_token: deadlineImpact.impact_token,
            responsibilities,
            internal_target_on: null,
            reminder_offsets_days: [],
          },
        },
      ),
      200,
      "override the confirmed legal deadline",
    );
    expect(overridden).toMatchObject({
      docket_id: docket.id,
      supersedes_deadline_id: confirmed.id,
      result_on: overrideResultDate,
      state: "confirmed",
      version: 2,
      override_reason: "Synthetic A0 canary sourced override.",
      override_evidence_ref: "qa:iplf-027b-a0:override",
    });
    expect(overridden.matter_deadline_id).toBeTruthy();

    const overriddenImpact = await jsonResponse<DeadlineImpact>(
      await api.get(
        `${PROD_API_BASE_URL}/api/ip/deadlines/${overridden.id}/impact`,
        { headers },
      ),
      200,
      "prove the override queued no delivery intent",
    );
    expect(overriddenImpact).toMatchObject({
      deadline_id: overridden.id,
      expected_version: overridden.version,
      notification_intent_ids: [],
      unrelated_work_preserved: true,
    });

    const completed = await jsonResponse<DeadlineRecord>(
      await api.post(
        `${PROD_API_BASE_URL}/api/ip/deadlines/${overridden.id}/complete`,
        {
          headers,
          data: {
            expected_version: overridden.version,
            evidence_reference: "qa:iplf-027b-a0:completion",
            attestation:
              "Verified synthetic completion evidence for the A0 production canary.",
          },
        },
      ),
      200,
      "complete the overridden legal deadline",
    );
    expect(completed).toMatchObject({
      id: overridden.id,
      state: "completed",
      version: 3,
      completed_evidence_ref: "qa:iplf-027b-a0:completion",
    });

    workspace = await loadWorkspace(api, owner.access_token, docket.id);
    const persistedCompleted = workspace.deadlines.find(
      (row) => row.id === completed.id,
    );
    const persistedOriginal = workspace.deadlines.find(
      (row) => row.id === proposed.id,
    );
    const persistedRecalculation = workspace.deadlines.find(
      (row) => row.id === recalculated.id,
    );
    expect(persistedCompleted).toMatchObject({
      id: completed.id,
      state: "completed",
      version: 3,
      matter_deadline_id: completed.matter_deadline_id,
      supersedes_deadline_id: confirmed.id,
      completed_evidence_ref: "qa:iplf-027b-a0:completion",
    });
    expect(persistedOriginal).toMatchObject({
      id: proposed.id,
      state: "superseded",
      version: 3,
      result_on: addIsoDays(baseDate, 1),
    });
    expect(persistedRecalculation).toMatchObject({
      id: recalculated.id,
      state: "candidate",
      version: 1,
      supersedes_deadline_id: confirmed.id,
      result_on: addIsoDays(recalculatedBaseDate, 1),
    });
    expect(activeRule(workspace)?.id).toBe(rule!.id);
    expect(activeCalendar(workspace)?.id).toBe(calendar!.id);
  } finally {
    await disposeSyntheticMatter(
      api,
      owner.access_token,
      matter.id,
      matter.company_id,
      freshDocketId ? [freshDocketId] : [],
    );
  }
}

/**
 * One-time fixture preparation must run before T_ROUTE while production still
 * serves the exact unfenced predecessor. PowerShell assigns the Secret Manager
 * result without printing it and removes every scoped environment variable:
 *
 * try {
 *   $env:CASEOPS_IP_QA_PASSWORD = & gcloud secrets versions access latest --secret caseops-ip-qa-password --project perfect-period-305406
 *   if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($env:CASEOPS_IP_QA_PASSWORD)) { throw "Unable to load the IP QA password." }
 *   $env:CASEOPS_EXPECTED_RELEASE_SHA = "3177f0176305e8790f40c3f771daebe595087955"
 *   $env:CASEOPS_IP_A0_PROD_MODE = "prepare"
 *   & npx playwright test --config=playwright.ip-a0-prod.config.ts --reporter=list
 *   if ($LASTEXITCODE -ne 0) { throw "A0 fixture preparation failed with exit code $LASTEXITCODE." }
 * } finally {
 *   Remove-Item Env:CASEOPS_IP_QA_PASSWORD, Env:CASEOPS_EXPECTED_RELEASE_SHA, Env:CASEOPS_IP_A0_PROD_MODE -ErrorAction SilentlyContinue
 * }
 *
 * The canonical post-deploy workflow sets mode to `verify`; it never prepares
 * governance state and fails loudly when this fixture is absent.
 */
test("IPLF-027B A0 production quiescence and legal-deadline continuity", async () => {
  test.setTimeout(180_000);
  assertCanonicalProductionOrigins();
  const api = await playwrightRequest.newContext({ maxRedirects: 0 });
  try {
    const mode = selectedMode();
    const releaseSha = await assertExactRelease(api);
    if (mode === "prepare") {
      expect(
        releaseSha,
        "A0 fixture preparation is permitted only on the exact 3177 predecessor.",
      ).toBe(A0_PREDECESSOR_SHA);
    }

    const owner = await authenticate(
      IP_QA_EMAIL,
      required("CASEOPS_IP_QA_PASSWORD"),
    );
    expect(owner.membership.role).toBe("owner");

    if (mode === "prepare") {
      await prepareFixture(api, owner);
      return;
    }
    await verifyQuiescenceAndDeadlineWriters(api, owner);
  } finally {
    await api.dispose();
  }
});
