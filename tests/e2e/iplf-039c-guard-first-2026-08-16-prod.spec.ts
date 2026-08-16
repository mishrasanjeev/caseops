/**
 * IPLF-039C / 2026-08-16 guard-first production acceptance.
 *
 * Safety contract:
 * - both the API and web deployment must report one exact 40-character SHA;
 * - the authenticated company id and slug must match an explicitly acknowledged
 *   dedicated QA tenant before the first write;
 * - fixture users are created through the password-based company-user API. The
 *   employee-invite API is intentionally forbidden because production can send
 *   an account-setup email through SendGrid;
 * - fixture emails use the reserved example.com domain, and all legal-work
 *   fixtures are disposed through the supported Matter lifecycle before the
 *   temporary users are deactivated;
 * - every write has an operator-supplied, non-secret recovery run id. The
 *   independently timed afterEach hook re-discovers exact users, Matters, and
 *   dockets by that id before bounded cleanup calls;
 * - no billing, provider, integration, delete, or database endpoint is called;
 * - the database constraint is not inspected. This is API guard-first proof and
 *   must run before migration 20260816_0001 is released.
 *
 * Defensive legacy-collision branches that cannot be reached through the
 * guarded API stay in the static/service and hosted-PostgreSQL evidence. This
 * production spec does not manufacture an invalid pre-guard row.
 */
import {
  expect,
  test,
  type APIRequestContext,
  type APIResponse,
} from "@playwright/test";

const REQUIRED_CONFLICT_CODE = "ip_coverage_distinct_backup_required";
const MUTATION_ACK = "dedicated-qa-disposable-fixtures-only";
const CLEANUP_TIMEOUT_MS = 180_000;
const CLEANUP_REQUEST_TIMEOUT_MS = 10_000;
const FIXTURE_MATTER_TYPE = "synthetic_release_canary";
const FIXTURE_CLIENT_NAME = "CaseOps Synthetic QA";
const FIXTURE_DESCRIPTION =
  "Synthetic IPLF-039C guard-first acceptance data; no client or legal effect.";
const RECOVERY_GUIDE =
  "docs/ip-implementation/evidence/m3/IPLF-039C/guard-first-production-acceptance-plan-2026-08-16.md#manual-recovery";

type FixturePhase = "conflict" | "workflow";

type JsonObject = Record<string, unknown>;

type AuthContext = {
  access_token: string;
  company: { id: string; slug: string };
  user: { email: string };
  membership: { id: string; role: string };
  capabilities: string[];
};

type CompanyUser = {
  membership_id: string;
  role: string;
  membership_active: boolean;
  user_active: boolean;
  email: string;
  full_name: string;
};

type MatterRecord = {
  id: string;
  company_id: string;
  title: string;
  matter_code: string;
  matter_type: string | null;
  client_name: string | null;
  description: string | null;
  practice_area: string;
  forum_level: string;
  status: string;
  is_active: boolean;
  lifecycle_version: number;
  updated_at: string;
};

type CoverageRow = {
  id: string;
  matter_deadline_id: string;
  responsible_membership_id: string;
  backup_membership_id: string | null;
  coverage_status: string;
  pending_replacement_membership_id: string | null;
  replacement_decision: string;
  emergency_escalation_membership_id: string | null;
  reassignment_version: number;
  [key: string]: unknown;
};

type DocketRecord = {
  id: string;
  company_id: string;
  matter_id: string | null;
  title: string;
  status: string;
  is_active: boolean;
  lifecycle_version: number;
  deadline_coverages: CoverageRow[];
};

type Runtime = {
  webBaseUrl: string;
  apiBaseUrl: string;
  expectedSha: string;
  companyId: string;
  companySlug: string;
  ownerEmail: string;
  ownerPassword: string;
  ruleVersionId: string;
  calendarVersionId: string;
  runId: string;
};

type FixtureMatter = {
  matter: MatterRecord;
  docket: DocketRecord;
  disposed: boolean;
};

type CleanupState = {
  run: Runtime;
  owner: AuthContext;
  users: Map<string, CompanyUser>;
  matters: Map<string, MatterRecord>;
  dockets: Map<string, DocketRecord>;
};

type MatterListPage = {
  company_id: string;
  matters: MatterRecord[];
  next_cursor: string | null;
};

let cleanupState: CleanupState | undefined;

function required(key: string): string {
  const value = (process.env[key] ?? "").trim();
  if (!value) throw new Error(`${key} is required for IPLF-039C production acceptance.`);
  return value;
}

function httpsUrl(key: string): string {
  const raw = required(key);
  const parsed = new URL(raw);
  if (parsed.protocol !== "https:") {
    throw new Error(`${key} must be an explicit https production URL.`);
  }
  if (["localhost", "127.0.0.1", "::1", "[::1]"].includes(parsed.hostname.toLowerCase())) {
    throw new Error(`${key} must not resolve to a loopback host in the production spec.`);
  }
  return parsed.toString().replace(/\/$/, "");
}

function runtime(): Runtime {
  if (required("CASEOPS_IP_GUARD_PROD_MODE") !== "verify") {
    throw new Error("CASEOPS_IP_GUARD_PROD_MODE must equal verify.");
  }
  if (required("CASEOPS_IP_GUARD_QA_ACK") !== MUTATION_ACK) {
    throw new Error(
      `CASEOPS_IP_GUARD_QA_ACK must equal ${MUTATION_ACK}; no mutation was attempted.`,
    );
  }
  const expectedSha = required("CASEOPS_EXPECTED_RELEASE_SHA").toLowerCase();
  if (!/^[0-9a-f]{40}$/.test(expectedSha)) {
    throw new Error("CASEOPS_EXPECTED_RELEASE_SHA must be an exact lowercase Git SHA.");
  }
  const companyId = required("CASEOPS_IP_GUARD_QA_COMPANY_ID").toLowerCase();
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(companyId)) {
    throw new Error("CASEOPS_IP_GUARD_QA_COMPANY_ID must be the exact QA company UUID.");
  }
  const runId = required("CASEOPS_IP_GUARD_RUN_ID");
  if (!/^20260816-[a-z0-9]{6,16}$/.test(runId)) {
    throw new Error(
      "CASEOPS_IP_GUARD_RUN_ID must match 20260816-[a-z0-9]{6,16}; it is a non-secret recovery key.",
    );
  }
  return {
    webBaseUrl: httpsUrl("PROD_BASE_URL"),
    apiBaseUrl: httpsUrl("PROD_API_BASE_URL"),
    expectedSha,
    companyId,
    companySlug: required("CASEOPS_IP_GUARD_QA_SLUG"),
    ownerEmail: required("CASEOPS_IP_GUARD_QA_OWNER_EMAIL").toLowerCase(),
    ownerPassword: required("CASEOPS_IP_GUARD_QA_OWNER_PASSWORD"),
    ruleVersionId: required("CASEOPS_IP_GUARD_QA_RULE_VERSION_ID"),
    calendarVersionId: required("CASEOPS_IP_GUARD_QA_CALENDAR_VERSION_ID"),
    runId,
  };
}

function userEmail(roleLabel: "source" | "replacement", runId: string): string {
  return `caseops-ip-guard-${roleLabel}-${runId}@example.com`;
}

function fixtureIdentity(
  runId: string,
  phase: FixturePhase,
): { title: string; matterCode: string; docketTitle: string } {
  return {
    title: `QA IPLF-039C guard ${phase} ${runId}`,
    matterCode: `IPG-${phase}-${runId}`.toUpperCase(),
    docketTitle: `IPGUARD${phase.toUpperCase()}${runId.replace(/-/g, "").toUpperCase()}`,
  };
}

async function body(response: APIResponse): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return await response.text();
  }
}

async function expectStatus(
  response: APIResponse,
  expected: number,
  operation: string,
): Promise<void> {
  expect(
    response.status(),
    `${operation}: ${JSON.stringify(await body(response))}`,
  ).toBe(expected);
}

async function json<T>(response: APIResponse): Promise<T> {
  return (await response.json()) as T;
}

async function optionalJson<T>(response: APIResponse): Promise<T | null> {
  try {
    return await json<T>(response);
  } catch {
    return null;
  }
}

function authHeaders(auth: AuthContext): { Authorization: string } {
  return { Authorization: `Bearer ${auth.access_token}` };
}

async function assertExactRelease(api: APIRequestContext, run: Runtime): Promise<void> {
  const [apiIdentity, webIdentity] = await Promise.all([
    api.get(`${run.apiBaseUrl}/api/build`),
    api.get(`${run.webBaseUrl}/api/release-identity`),
  ]);
  await expectStatus(apiIdentity, 200, "read API release identity");
  await expectStatus(webIdentity, 200, "read web release identity");
  expect((await json<{ release_sha: string }>(apiIdentity)).release_sha).toBe(
    run.expectedSha,
  );
  expect((await json<{ release_sha: string }>(webIdentity)).release_sha).toBe(
    run.expectedSha,
  );
}

async function authenticateOwner(
  api: APIRequestContext,
  run: Runtime,
): Promise<AuthContext> {
  await assertExactRelease(api, run);
  const response = await api.post(`${run.apiBaseUrl}/api/auth/login`, {
    data: {
      company_slug: run.companySlug,
      email: run.ownerEmail,
      password: run.ownerPassword,
    },
  });
  await expectStatus(response, 200, "authenticate dedicated-QA owner");
  const auth = await json<AuthContext>(response);
  expect(auth.company.id.toLowerCase()).toBe(run.companyId);
  expect(auth.company.slug).toBe(run.companySlug);
  expect(auth.user.email.toLowerCase()).toBe(run.ownerEmail);
  expect(auth.membership.role).toBe("owner");

  const workspace = await api.get(`${run.apiBaseUrl}/api/ip/workspace/configuration`, {
    headers: authHeaders(auth),
  });
  await expectStatus(workspace, 200, "read dedicated-QA IP configuration");
  const configuration = (
    await json<{
      configuration: null | {
        workspace_enabled: boolean;
        provider_keys_json: string[];
        enabled_automations_json: string[];
      };
    }>(workspace)
  ).configuration;
  expect(configuration, "QA IP workspace must already be configured").not.toBeNull();
  expect(configuration?.workspace_enabled).toBe(true);
  expect(configuration?.provider_keys_json, "QA guard tenant must have no provider keys").toEqual(
    [],
  );
  expect(
    configuration?.enabled_automations_json,
    "QA guard tenant must have no enabled IP automations",
  ).toEqual([]);

  const policies = await api.get(`${run.apiBaseUrl}/api/ip/rule-policies`, {
    headers: authHeaders(auth),
  });
  await expectStatus(policies, 200, "read QA rule policies");
  const selected = (await json<Array<JsonObject>>(policies)).find(
    (row) => row.active_rule_version_id === run.ruleVersionId,
  );
  expect(selected, "the exact seeded rule version must be selected in the QA tenant").toBeTruthy();
  expect(selected?.active_rule_status).toBe("active");
  return auth;
}

async function authenticateUser(
  api: APIRequestContext,
  run: Runtime,
  email: string,
  password: string,
  membershipId: string,
): Promise<AuthContext> {
  const response = await api.post(`${run.apiBaseUrl}/api/auth/login`, {
    data: { company_slug: run.companySlug, email, password },
  });
  await expectStatus(response, 200, `authenticate disposable user ${membershipId}`);
  const auth = await json<AuthContext>(response);
  expect(auth.company.id.toLowerCase()).toBe(run.companyId);
  expect(auth.membership.id).toBe(membershipId);
  expect(auth.user.email.toLowerCase()).toBe(email.toLowerCase());
  return auth;
}

async function expectCoverageConflict(
  response: APIResponse,
  operation: string,
): Promise<JsonObject> {
  await expectStatus(response, 409, operation);
  const problem = await json<JsonObject>(response);
  expect(problem.code, `${operation} must return a typed domain conflict`).toBe(
    REQUIRED_CONFLICT_CODE,
  );
  expect(problem.detail, `${operation} must return an actionable message`).toEqual(
    expect.any(String),
  );
  return problem;
}

function particulars(mark: string): JsonObject {
  return {
    form_key: "TM-A",
    form_version: "2026.1",
    mark_kind: "word",
    representation: { text: mark, evidence_reference: `qa:${mark.toLowerCase()}` },
    classes: [{ class_number: 9, specification: "Downloadable software" }],
    use_priority: null,
    parties: [{ role: "applicant", name: "CaseOps QA Fixtures LLP" }],
    agent: null,
    filing_manifest: [
      {
        key: "representation",
        label: "Mark representation",
        required: true,
        evidence_reference: `qa:${mark.toLowerCase()}`,
      },
    ],
  };
}

async function createDisposableUser(
  api: APIRequestContext,
  state: CleanupState,
  roleLabel: "source" | "replacement",
): Promise<{ record: CompanyUser; password: string }> {
  const { run, owner } = state;
  const runId = run.runId;
  const password = `QaGuard-${runId}-Aa7!`;
  const email = userEmail(roleLabel, runId);
  const response = await api.post(`${run.apiBaseUrl}/api/companies/current/users`, {
    headers: authHeaders(owner),
    data: {
      full_name: `IP guard ${roleLabel} ${runId}`,
      email,
      password,
      role: "member",
    },
  });
  const committed = await optionalJson<CompanyUser>(response);
  if (committed?.membership_id && committed.email) {
    state.users.set(committed.email.toLowerCase(), committed);
  }
  await expectStatus(response, 200, `create disposable ${roleLabel} user`);
  expect(committed, `create disposable ${roleLabel} user must return a record`).not.toBeNull();
  const record = committed as CompanyUser;
  expect(record.email.toLowerCase()).toBe(email);
  expect(record.membership_active).toBe(true);
  expect(record.user_active).toBe(true);
  return { record, password };
}

async function createFixtureMatter(
  api: APIRequestContext,
  state: CleanupState,
  phase: FixturePhase,
): Promise<FixtureMatter> {
  const { run, owner } = state;
  const identity = fixtureIdentity(run.runId, phase);
  const createdMatter = await api.post(`${run.apiBaseUrl}/api/matters/`, {
    headers: authHeaders(owner),
    data: {
      title: identity.title,
      matter_code: identity.matterCode,
      matter_type: FIXTURE_MATTER_TYPE,
      client_name: FIXTURE_CLIENT_NAME,
      description: FIXTURE_DESCRIPTION,
      practice_area: "intellectual_property",
      forum_level: "high_court",
      status: "active",
    },
  });
  const committedMatter = await optionalJson<MatterRecord>(createdMatter);
  if (committedMatter?.id) {
    state.matters.set(committedMatter.id, committedMatter);
  }
  await expectStatus(createdMatter, 200, `create ${phase} QA Matter`);
  expect(committedMatter, `create ${phase} QA Matter must return a record`).not.toBeNull();
  const matter = committedMatter as MatterRecord;
  expect(matter.company_id.toLowerCase()).toBe(run.companyId);
  expect(matter).toMatchObject({
    title: identity.title,
    matter_code: identity.matterCode,
    matter_type: FIXTURE_MATTER_TYPE,
    client_name: FIXTURE_CLIENT_NAME,
    description: FIXTURE_DESCRIPTION,
    status: "active",
    is_active: true,
  });

  const createdDocket = await api.post(`${run.apiBaseUrl}/api/ip/dockets`, {
    headers: authHeaders(owner),
    data: {
      title: identity.docketTitle,
      matter_id: matter.id,
      restricted: false,
      particulars: particulars(identity.docketTitle),
    },
  });
  const committedDocket = await optionalJson<DocketRecord>(createdDocket);
  if (committedDocket?.id) {
    state.dockets.set(committedDocket.id, committedDocket);
  }
  await expectStatus(createdDocket, 201, `create ${phase} QA IP docket`);
  expect(committedDocket, `create ${phase} QA IP docket must return a record`).not.toBeNull();
  const docket = committedDocket as DocketRecord;
  expect(docket.company_id.toLowerCase()).toBe(run.companyId);
  expect(docket.matter_id).toBe(matter.id);
  expect(docket.title).toBe(identity.docketTitle);
  return { matter, docket, disposed: false };
}

async function createOperationalDeadline(
  api: APIRequestContext,
  run: Runtime,
  owner: AuthContext,
  fixture: FixtureMatter,
  assigneeMembershipId: string,
  title: string,
): Promise<{ id: string }> {
  const dueOn = new Date(Date.now() + 45 * 24 * 60 * 60 * 1000)
    .toISOString()
    .slice(0, 10);
  const response = await api.post(
    `${run.apiBaseUrl}/api/matters/${fixture.matter.id}/deadlines`,
    {
      headers: authHeaders(owner),
      data: {
        source: "custom",
        kind: "licence_royalty",
        title,
        due_on: dueOn,
        assignee_membership_id: assigneeMembershipId,
      },
    },
  );
  await expectStatus(response, 200, `create operational deadline: ${title}`);
  return json<{ id: string }>(response);
}

async function getDocket(
  api: APIRequestContext,
  run: Runtime,
  auth: AuthContext,
  docketId: string,
): Promise<DocketRecord> {
  const response = await api.get(`${run.apiBaseUrl}/api/ip/dockets/${docketId}`, {
    headers: authHeaders(auth),
  });
  await expectStatus(response, 200, `read docket ${docketId}`);
  const docket = await json<DocketRecord>(response);
  expect(docket.company_id.toLowerCase()).toBe(run.companyId);
  return docket;
}

async function getCoverage(
  api: APIRequestContext,
  run: Runtime,
  auth: AuthContext,
  docketId: string,
  coverageId: string,
): Promise<CoverageRow> {
  const docket = await getDocket(api, run, auth, docketId);
  const coverage = docket.deadline_coverages.find((row) => row.id === coverageId);
  expect(coverage, `coverage ${coverageId} must belong to ${docketId}`).toBeTruthy();
  return structuredClone(coverage as CoverageRow);
}

async function createCoverage(
  api: APIRequestContext,
  run: Runtime,
  owner: AuthContext,
  docketId: string,
  deadlineId: string,
  responsibleId: string,
  backupId?: string,
): Promise<CoverageRow> {
  const response = await api.post(
    `${run.apiBaseUrl}/api/ip/dockets/${docketId}/deadline-coverages`,
    {
      headers: authHeaders(owner),
      data: {
        matter_deadline_id: deadlineId,
        responsible_membership_id: responsibleId,
        ...(backupId ? { backup_membership_id: backupId } : {}),
        coverage_status: "accepted",
      },
    },
  );
  await expectStatus(response, 200, "create valid deadline coverage");
  const docket = await json<DocketRecord>(response);
  const row = docket.deadline_coverages.find(
    (coverage) => coverage.matter_deadline_id === deadlineId,
  );
  expect(row).toBeTruthy();
  return row as CoverageRow;
}

function reservedMatterPhase(matter: MatterRecord, run: Runtime): FixturePhase | null {
  for (const phase of ["conflict", "workflow"] as const) {
    const identity = fixtureIdentity(run.runId, phase);
    if (
      matter.company_id.toLowerCase() === run.companyId &&
      matter.title === identity.title &&
      matter.matter_code === identity.matterCode &&
      matter.matter_type === FIXTURE_MATTER_TYPE &&
      matter.client_name === FIXTURE_CLIENT_NAME &&
      matter.description === FIXTURE_DESCRIPTION &&
      matter.practice_area === "intellectual_property" &&
      matter.forum_level === "high_court"
    ) {
      return phase;
    }
  }
  return null;
}

function bounded(cleanup: boolean): { timeout?: number } {
  return cleanup ? { timeout: CLEANUP_REQUEST_TIMEOUT_MS } : {};
}

async function disposeTrackedMatter(
  api: APIRequestContext,
  state: CleanupState,
  matterId: string,
  docketIds: string[],
  cleanup: boolean,
): Promise<void> {
  const { run, owner } = state;
  const currentResponse = await api.get(
    `${run.apiBaseUrl}/api/matters/${matterId}`,
    { headers: authHeaders(owner), ...bounded(cleanup) },
  );
  await expectStatus(currentResponse, 200, `read Matter ${matterId} for disposal`);
  const current = await json<MatterRecord>(currentResponse);
  expect(
    reservedMatterPhase(current, run),
    `cleanup refuses Matter ${matterId} unless every reserved-fixture marker matches`,
  ).not.toBeNull();
  state.matters.set(current.id, current);
  if (current.status !== "disposed") {
    const disposedResponse = await api.patch(
      `${run.apiBaseUrl}/api/matters/${matterId}/lifecycle/status`,
      {
        headers: authHeaders(owner),
        ...bounded(cleanup),
        data: {
          to_status: "disposed",
          expected_from_status: current.status,
          expected_updated_at: current.updated_at,
          reason: "Dispose the isolated IPLF guard acceptance fixture after verification.",
        },
      },
    );
    await expectStatus(disposedResponse, 200, `dispose QA Matter ${matterId}`);
    const disposed = await json<MatterRecord>(disposedResponse);
    expect(disposed.status).toBe("disposed");
    expect(disposed.is_active).toBe(false);
    state.matters.set(disposed.id, disposed);
  } else {
    expect(current.is_active).toBe(false);
  }
  // Terminal IP dockets intentionally disappear from operational reads. The
  // exact child neutralization is covered by the lifecycle service regression;
  // production proves the supported parent transition and fail-closed read.
  for (const docketId of docketIds) {
    const retiredDocket = await api.get(
      `${run.apiBaseUrl}/api/ip/dockets/${docketId}`,
      { headers: authHeaders(owner), ...bounded(cleanup) },
    );
    await expectStatus(retiredDocket, 404, `verify retired docket ${docketId}`);
  }
}

async function disposeMatter(
  api: APIRequestContext,
  state: CleanupState,
  fixture: FixtureMatter,
): Promise<void> {
  if (fixture.disposed) return;
  await disposeTrackedMatter(api, state, fixture.matter.id, [fixture.docket.id], false);
  fixture.disposed = true;
}

async function deactivateDisposableUser(
  api: APIRequestContext,
  state: CleanupState,
  user: CompanyUser,
): Promise<void> {
  const { run, owner } = state;
  const response = await api.patch(
    `${run.apiBaseUrl}/api/companies/current/users/${user.membership_id}`,
    {
      headers: authHeaders(owner),
      timeout: CLEANUP_REQUEST_TIMEOUT_MS,
      data: { is_active: false },
    },
  );
  await expectStatus(response, 200, `deactivate disposable user ${user.membership_id}`);
  const record = await json<CompanyUser>(response);
  expect(record.email.toLowerCase()).toBe(user.email.toLowerCase());
  expect(record.membership_active).toBe(false);
  expect(record.user_active).toBe(false);
  state.users.set(record.email.toLowerCase(), record);
}

function reservedUserRole(user: CompanyUser, run: Runtime): "source" | "replacement" | null {
  for (const roleLabel of ["source", "replacement"] as const) {
    if (
      user.email.toLowerCase() === userEmail(roleLabel, run.runId) &&
      user.full_name === `IP guard ${roleLabel} ${run.runId}` &&
      user.role === "member"
    ) {
      return roleLabel;
    }
  }
  return null;
}

function reservedDocketPhase(
  docket: DocketRecord,
  state: CleanupState,
): FixturePhase | null {
  if (docket.company_id.toLowerCase() !== state.run.companyId || !docket.matter_id) {
    return null;
  }
  const matter = state.matters.get(docket.matter_id);
  const phase = matter ? reservedMatterPhase(matter, state.run) : null;
  if (!phase) return null;
  return docket.title === fixtureIdentity(state.run.runId, phase).docketTitle
    ? phase
    : null;
}

async function recoverReservedUsers(
  api: APIRequestContext,
  state: CleanupState,
): Promise<void> {
  const response = await api.get(`${state.run.apiBaseUrl}/api/companies/current/users`, {
    headers: authHeaders(state.owner),
    timeout: CLEANUP_REQUEST_TIMEOUT_MS,
  });
  await expectStatus(response, 200, "recover disposable users by deterministic run id");
  const listed = await json<{ company_id: string; users: CompanyUser[] }>(response);
  expect(listed.company_id.toLowerCase()).toBe(state.run.companyId);
  for (const roleLabel of ["source", "replacement"] as const) {
    const expectedEmail = userEmail(roleLabel, state.run.runId);
    const matches = listed.users.filter(
      (candidate) => candidate.email.toLowerCase() === expectedEmail,
    );
    expect(matches.length, `at most one disposable ${roleLabel} user may match`).toBeLessThanOrEqual(
      1,
    );
    const match = matches[0];
    if (match) {
      expect(reservedUserRole(match, state.run)).toBe(roleLabel);
      state.users.set(match.email.toLowerCase(), match);
    }
  }
}

async function recoverReservedMatters(
  api: APIRequestContext,
  state: CleanupState,
): Promise<void> {
  let cursor: string | null = null;
  const seenCursors = new Set<string>();
  for (let pageNumber = 0; pageNumber < 2; pageNumber += 1) {
    const response = await api.get(`${state.run.apiBaseUrl}/api/matters/`, {
      headers: authHeaders(state.owner),
      timeout: CLEANUP_REQUEST_TIMEOUT_MS,
      params: {
        q: state.run.runId,
        limit: 50,
        ...(cursor ? { cursor } : {}),
      },
    });
    await expectStatus(response, 200, "recover reserved Matters by deterministic run id");
    const page = await json<MatterListPage>(response);
    expect(page.company_id.toLowerCase()).toBe(state.run.companyId);
    for (const matter of page.matters) {
      if (reservedMatterPhase(matter, state.run)) {
        state.matters.set(matter.id, matter);
      }
    }
    cursor = page.next_cursor;
    if (!cursor) break;
    expect(seenCursors.has(cursor), "Matter recovery pagination must advance").toBe(false);
    seenCursors.add(cursor);
    if (pageNumber === 1) {
      throw new Error(
        `Matter recovery exceeded its two-page safety bound for run ${state.run.runId}.`,
      );
    }
  }
  for (const phase of ["conflict", "workflow"] as const) {
    const identity = fixtureIdentity(state.run.runId, phase);
    const matches = [...state.matters.values()].filter(
      (matter) => matter.matter_code === identity.matterCode,
    );
    expect(matches.length, `at most one reserved ${phase} Matter may match`).toBeLessThanOrEqual(1);
  }
}

async function recoverReservedDockets(
  api: APIRequestContext,
  state: CleanupState,
): Promise<void> {
  const response = await api.get(`${state.run.apiBaseUrl}/api/ip/dockets`, {
    headers: authHeaders(state.owner),
    timeout: CLEANUP_REQUEST_TIMEOUT_MS,
  });
  await expectStatus(response, 200, "recover operational dockets by deterministic run id");
  const listed = await json<{ dockets: DocketRecord[]; count: number }>(response);
  expect(listed.count).toBe(listed.dockets.length);
  for (const docket of listed.dockets) {
    if (reservedDocketPhase(docket, state)) {
      state.dockets.set(docket.id, docket);
    }
  }
  for (const phase of ["conflict", "workflow"] as const) {
    const expectedTitle = fixtureIdentity(state.run.runId, phase).docketTitle;
    const matches = [...state.dockets.values()].filter(
      (docket) => docket.title === expectedTitle,
    );
    expect(matches.length, `at most one reserved ${phase} docket may match`).toBeLessThanOrEqual(
      1,
    );
  }
}

async function cleanupReservedRun(
  api: APIRequestContext,
  state: CleanupState,
): Promise<void> {
  const discoveryErrors: unknown[] = [];
  for (const discover of [recoverReservedUsers, recoverReservedMatters, recoverReservedDockets]) {
    try {
      await discover(api, state);
    } catch (error) {
      discoveryErrors.push(error);
    }
  }

  const matterErrors: unknown[] = [];
  for (const matter of [...state.matters.values()].reverse()) {
    try {
      const docketIds = [...state.dockets.values()]
        .filter((docket) => docket.matter_id === matter.id)
        .map((docket) => docket.id);
      for (const docket of state.dockets.values()) {
        if (docket.matter_id === matter.id) {
          expect(reservedDocketPhase(docket, state)).not.toBeNull();
        }
      }
      await disposeTrackedMatter(api, state, matter.id, docketIds, true);
    } catch (error) {
      matterErrors.push(error);
    }
  }

  const orphanDockets = [...state.dockets.values()].filter(
    (docket) => !docket.matter_id || !state.matters.has(docket.matter_id),
  );
  if (orphanDockets.length) {
    matterErrors.push(
      new Error(
        `Reserved docket recovery found ${orphanDockets.length} docket(s) without a tracked Matter.`,
      ),
    );
  }

  const userErrors: unknown[] = [];
  if (discoveryErrors.length === 0 && matterErrors.length === 0) {
    for (const user of [...state.users.values()].reverse()) {
      try {
        expect(reservedUserRole(user, state.run)).not.toBeNull();
        if (user.membership_active || user.user_active) {
          await deactivateDisposableUser(api, state, user);
        }
      } catch (error) {
        userErrors.push(error);
      }
    }
  }

  const errors = [...discoveryErrors, ...matterErrors, ...userErrors];
  if (errors.length) {
    throw new AggregateError(
      errors,
      `Cleanup incomplete for non-secret run ${state.run.runId}; follow ${RECOVERY_GUIDE}.`,
    );
  }
}

test.afterEach(async ({ request: api }, testInfo) => {
  const state = cleanupState;
  cleanupState = undefined;
  if (!state) return;
  testInfo.setTimeout(CLEANUP_TIMEOUT_MS);
  try {
    await cleanupReservedRun(api, state);
    console.log(`[IPLF-039C] cleanup complete; run_id=${state.run.runId}`);
  } catch (error) {
    console.error(
      `[IPLF-039C] MANUAL RECOVERY REQUIRED; run_id=${state.run.runId}; guide=${RECOVERY_GUIDE}`,
    );
    throw error;
  }
});

test("guard-first writers reject role collapse and preserve disposable QA state", async ({
  request: api,
}) => {
  const run = runtime();
  const owner = await authenticateOwner(api, run);
  const state: CleanupState = {
    run,
    owner,
    users: new Map(),
    matters: new Map(),
    dockets: new Map(),
  };
  cleanupState = state;
  const runId = run.runId;
  console.log(`[IPLF-039C] run_id=${runId}; manual_recovery=${RECOVERY_GUIDE}`);

    const source = await createDisposableUser(api, state, "source");
    const replacement = await createDisposableUser(api, state, "replacement");
    const replacementAuth = await authenticateUser(
      api,
      run,
      replacement.record.email,
      replacement.password,
      replacement.record.membership_id,
    );

    const conflictFixture = await createFixtureMatter(api, state, "conflict");
    const conflictDeadline = await createOperationalDeadline(
      api,
      run,
      owner,
      conflictFixture,
      source.record.membership_id,
      `QA distinct-role conflict ${runId}`,
    );

    const collapsedCreate = await api.post(
      `${run.apiBaseUrl}/api/ip/dockets/${conflictFixture.docket.id}/deadline-coverages`,
      {
        headers: authHeaders(owner),
        data: {
          matter_deadline_id: conflictDeadline.id,
          responsible_membership_id: source.record.membership_id,
          backup_membership_id: source.record.membership_id,
          coverage_status: "accepted",
        },
      },
    );
    await expectCoverageConflict(collapsedCreate, "coverage create collision");
    expect((await getDocket(api, run, owner, conflictFixture.docket.id)).deadline_coverages).toEqual(
      [],
    );

    const conflictCoverage = await createCoverage(
      api,
      run,
      owner,
      conflictFixture.docket.id,
      conflictDeadline.id,
      source.record.membership_id,
      replacement.record.membership_id,
    );
    const conflictBefore = await getCoverage(
      api,
      run,
      owner,
      conflictFixture.docket.id,
      conflictCoverage.id,
    );

    const directProposed = await api.post(
      `${run.apiBaseUrl}/api/ip/dockets/${conflictFixture.docket.id}/deadline-coverages/${conflictCoverage.id}/reassign`,
      {
        headers: authHeaders(owner),
        data: {
          expected_responsible_membership_id: source.record.membership_id,
          responsible_membership_id: replacement.record.membership_id,
          backup_membership_id: source.record.membership_id,
          reason: "A proposed transfer must keep the current owner distinct from backup.",
          transfer_mode: "proposed",
        },
      },
    );
    await expectCoverageConflict(directProposed, "direct proposed collision");
    expect(
      await getCoverage(api, run, owner, conflictFixture.docket.id, conflictCoverage.id),
    ).toEqual(conflictBefore);

    const directImmediate = await api.post(
      `${run.apiBaseUrl}/api/ip/dockets/${conflictFixture.docket.id}/deadline-coverages/${conflictCoverage.id}/reassign`,
      {
        headers: authHeaders(owner),
        data: {
          expected_responsible_membership_id: source.record.membership_id,
          responsible_membership_id: owner.membership.id,
          backup_membership_id: replacement.record.membership_id,
          reason: "An immediate decline fallback must remain distinct from backup.",
          transfer_mode: "immediate",
          escalation_membership_id: replacement.record.membership_id,
        },
      },
    );
    await expectCoverageConflict(directImmediate, "direct immediate escalation collision");
    expect(
      await getCoverage(api, run, owner, conflictFixture.docket.id, conflictCoverage.id),
    ).toEqual(conflictBefore);

    const bulk = await api.post(`${run.apiBaseUrl}/api/ip/deadline-coverages/bulk-reassign`, {
      headers: authHeaders(owner),
      data: {
        from_membership_id: source.record.membership_id,
        to_membership_id: replacement.record.membership_id,
        reason: "A portfolio transfer must preserve distinct backup cover.",
        transfer_mode: "proposed",
      },
    });
    await expectCoverageConflict(bulk, "bulk portfolio collision");
    expect(
      await getCoverage(api, run, owner, conflictFixture.docket.id, conflictCoverage.id),
    ).toEqual(conflictBefore);

    const blockedPreview = await api.post(
      `${run.apiBaseUrl}/api/ip/deadline-coverages/reassign-preview`,
      {
        headers: authHeaders(owner),
        data: {
          from_membership_id: source.record.membership_id,
          to_membership_id: replacement.record.membership_id,
        },
      },
    );
    await expectStatus(blockedPreview, 200, "preview blocked portfolio transfer");
    const blockedSnapshot = await json<{
      preview_token: string;
      transfer_allowed: boolean;
      blocked_docket_ids: string[];
    }>(blockedPreview);
    expect(blockedSnapshot.transfer_allowed).toBe(false);
    expect(blockedSnapshot.blocked_docket_ids).toContain(conflictFixture.docket.id);
    const blockedProposal = await api.post(
      `${run.apiBaseUrl}/api/ip/deadline-coverages/reassign-propose`,
      {
        headers: authHeaders(owner),
        data: {
          from_membership_id: source.record.membership_id,
          to_membership_id: replacement.record.membership_id,
          preview_token: blockedSnapshot.preview_token,
          reason: "The previewed portfolio transfer must fail closed on collision.",
        },
      },
    );
    await expectCoverageConflict(blockedProposal, "portfolio proposal collision");
    expect(
      await getCoverage(api, run, owner, conflictFixture.docket.id, conflictCoverage.id),
    ).toEqual(conflictBefore);

    const offboardingPreview = await api.post(
      `${run.apiBaseUrl}/api/companies/current/employees/${source.record.membership_id}/offboarding/preview`,
      {
        headers: authHeaders(owner),
        data: {
          reassign_to_membership_id: replacement.record.membership_id,
          notes: `IPLF guard collision ${runId}`,
        },
      },
    );
    await expectStatus(offboardingPreview, 200, "preview collision-bearing offboarding");
    const offboardingSnapshot = await json<{
      can_commit: boolean;
      blockers: string[];
      employee: { membership_active: boolean; user_active: boolean };
    }>(offboardingPreview);
    expect(offboardingSnapshot.can_commit).toBe(false);
    expect(offboardingSnapshot.employee.membership_active).toBe(true);
    expect(offboardingSnapshot.employee.user_active).toBe(true);
    expect(offboardingSnapshot.blockers.join(" ").toLowerCase()).toContain(
      "distinct ip deadline backup",
    );
    const offboardingCoverageBefore = await getCoverage(
      api,
      run,
      owner,
      conflictFixture.docket.id,
      conflictCoverage.id,
    );
    const offboardingCommit = await api.post(
      `${run.apiBaseUrl}/api/companies/current/employees/${source.record.membership_id}/offboarding/commit`,
      {
        headers: authHeaders(owner),
        data: {
          reassign_to_membership_id: replacement.record.membership_id,
          notes: `IPLF guard collision ${runId}`,
        },
      },
    );
    await expectStatus(offboardingCommit, 400, "offboarding commit collision");
    const offboardingProblem = await json<{
      status: number;
      detail: string;
      instance: string;
    }>(offboardingCommit);
    expect(offboardingProblem.status).toBe(400);
    expect(offboardingProblem.instance).toBe(
      `/api/companies/current/employees/${source.record.membership_id}/offboarding/commit`,
    );
    expect(offboardingProblem.detail.toLowerCase()).toContain(
      "choose a distinct ip deadline backup",
    );
    expect(
      await getCoverage(api, run, owner, conflictFixture.docket.id, conflictCoverage.id),
    ).toEqual(offboardingCoverageBefore);

    await disposeMatter(api, state, conflictFixture);

    const workflowFixture = await createFixtureMatter(api, state, "workflow");
    const acceptedDeadline = await createOperationalDeadline(
      api,
      run,
      owner,
      workflowFixture,
      source.record.membership_id,
      `QA accepted transfer ${runId}`,
    );
    const acceptedCoverage = await createCoverage(
      api,
      run,
      owner,
      workflowFixture.docket.id,
      acceptedDeadline.id,
      source.record.membership_id,
    );
    const acceptedPreview = await api.post(
      `${run.apiBaseUrl}/api/ip/deadline-coverages/reassign-preview`,
      {
        headers: authHeaders(owner),
        data: {
          from_membership_id: source.record.membership_id,
          to_membership_id: replacement.record.membership_id,
        },
      },
    );
    await expectStatus(acceptedPreview, 200, "preview valid portfolio proposal");
    const acceptedSnapshot = await json<{
      preview_token: string;
      transfer_allowed: boolean;
      affected_coverage_ids: string[];
    }>(acceptedPreview);
    expect(acceptedSnapshot.transfer_allowed).toBe(true);
    expect(acceptedSnapshot.affected_coverage_ids).toEqual([acceptedCoverage.id]);
    const proposed = await api.post(
      `${run.apiBaseUrl}/api/ip/deadline-coverages/reassign-propose`,
      {
        headers: authHeaders(owner),
        data: {
          from_membership_id: source.record.membership_id,
          to_membership_id: replacement.record.membership_id,
          preview_token: acceptedSnapshot.preview_token,
          reason: "Exercise the accepted replacement path with distinct coverage roles.",
        },
      },
    );
    await expectStatus(proposed, 200, "propose valid portfolio transfer");
    const pending = await getCoverage(
      api,
      run,
      owner,
      workflowFixture.docket.id,
      acceptedCoverage.id,
    );
    expect(pending.responsible_membership_id).toBe(source.record.membership_id);
    expect(pending.pending_replacement_membership_id).toBe(
      replacement.record.membership_id,
    );
    expect(pending.replacement_decision).toBe("pending");
    const accepted = await api.post(
      `${run.apiBaseUrl}/api/ip/deadline-coverages/${acceptedCoverage.id}/replacement-decision`,
      {
        headers: authHeaders(replacementAuth),
        data: { decision: "accepted", reason: "QA acceptance of isolated coverage." },
      },
    );
    await expectStatus(accepted, 200, "accept valid portfolio transfer");
    const acceptedAfter = await getCoverage(
      api,
      run,
      owner,
      workflowFixture.docket.id,
      acceptedCoverage.id,
    );
    expect(acceptedAfter.responsible_membership_id).toBe(
      replacement.record.membership_id,
    );
    expect(acceptedAfter.backup_membership_id).toBeNull();
    expect(acceptedAfter.replacement_decision).toBe("accepted");

    const rejectedDeadline = await createOperationalDeadline(
      api,
      run,
      owner,
      workflowFixture,
      source.record.membership_id,
      `QA rejected immediate transfer ${runId}`,
    );
    const rejectedCoverage = await createCoverage(
      api,
      run,
      owner,
      workflowFixture.docket.id,
      rejectedDeadline.id,
      source.record.membership_id,
    );
    const immediate = await api.post(
      `${run.apiBaseUrl}/api/ip/dockets/${workflowFixture.docket.id}/deadline-coverages/${rejectedCoverage.id}/reassign`,
      {
        headers: authHeaders(owner),
        data: {
          expected_responsible_membership_id: source.record.membership_id,
          responsible_membership_id: replacement.record.membership_id,
          reason: "Exercise immediate cover and the explicit rejection escalation.",
          transfer_mode: "immediate",
          escalation_membership_id: owner.membership.id,
        },
      },
    );
    await expectStatus(immediate, 200, "create valid immediate transfer");
    const immediatePending = await getCoverage(
      api,
      run,
      owner,
      workflowFixture.docket.id,
      rejectedCoverage.id,
    );
    expect(immediatePending.responsible_membership_id).toBe(
      replacement.record.membership_id,
    );
    expect(immediatePending.replacement_decision).toBe("pending");
    const rejected = await api.post(
      `${run.apiBaseUrl}/api/ip/deadline-coverages/${rejectedCoverage.id}/replacement-decision`,
      {
        headers: authHeaders(replacementAuth),
        data: {
          decision: "rejected",
          reason: "QA rejection exercises the explicit escalation owner.",
        },
      },
    );
    await expectStatus(rejected, 200, "reject immediate transfer and escalate");
    const rejectedAfter = await getCoverage(
      api,
      run,
      owner,
      workflowFixture.docket.id,
      rejectedCoverage.id,
    );
    expect(rejectedAfter.responsible_membership_id).toBe(owner.membership.id);
    expect(rejectedAfter.backup_membership_id).toBeNull();
    expect(rejectedAfter.coverage_status).toBe("escalated");
    expect(rejectedAfter.replacement_decision).toBe("rejected");

    const proposal = await api.post(
      `${run.apiBaseUrl}/api/ip/dockets/${workflowFixture.docket.id}/deadlines`,
      {
        headers: authHeaders(owner),
        data: {
          title: `QA critical confirmation ${runId}`,
          rule_version_id: run.ruleVersionId,
          calendar_version_id: run.calendarVersionId,
          base_date: new Date().toISOString().slice(0, 10),
          base_date_certainty: "certain",
          is_critical: true,
        },
      },
    );
    await expectStatus(proposal, 201, "create isolated critical deadline proposal");
    const proposedDeadline = await json<{ id: string; version: number }>(proposal);
    const workspaceBeforeResponse = await api.get(
      `${run.apiBaseUrl}/api/ip/dockets/${workflowFixture.docket.id}/deadline-workspace`,
      { headers: authHeaders(owner) },
    );
    await expectStatus(workspaceBeforeResponse, 200, "read deadline workspace before guard");
    const workspaceBefore = await json<{ deadlines: JsonObject[] }>(workspaceBeforeResponse);
    const criticalBefore = workspaceBefore.deadlines.find(
      (row) => row.id === proposedDeadline.id,
    );
    expect(criticalBefore).toBeTruthy();
    const coveragesBeforeConfirmation = (
      await getDocket(api, run, owner, workflowFixture.docket.id)
    ).deadline_coverages;
    const collapsedConfirmation = await api.post(
      `${run.apiBaseUrl}/api/ip/deadlines/${proposedDeadline.id}/confirm`,
      {
        headers: authHeaders(owner),
        data: {
          expected_version: proposedDeadline.version,
          responsibilities: [
            {
              membership_id: source.record.membership_id,
              role: "primary",
              accepted: true,
            },
            {
              membership_id: source.record.membership_id,
              role: "backup",
              accepted: true,
            },
          ],
          reminder_offsets_days: [],
        },
      },
    );
    await expectCoverageConflict(collapsedConfirmation, "critical confirmation collision");
    const workspaceAfterResponse = await api.get(
      `${run.apiBaseUrl}/api/ip/dockets/${workflowFixture.docket.id}/deadline-workspace`,
      { headers: authHeaders(owner) },
    );
    await expectStatus(workspaceAfterResponse, 200, "read deadline workspace after guard");
    const workspaceAfter = await json<{ deadlines: JsonObject[] }>(workspaceAfterResponse);
    expect(workspaceAfter.deadlines.find((row) => row.id === proposedDeadline.id)).toEqual(
      criticalBefore,
    );
    expect(
      (await getDocket(api, run, owner, workflowFixture.docket.id)).deadline_coverages,
    ).toEqual(coveragesBeforeConfirmation);

    await disposeMatter(api, state, workflowFixture);
    await assertExactRelease(api, run);
});
