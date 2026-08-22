import { randomBytes } from "node:crypto";

import {
  expect,
  request as playwrightRequest,
  test,
  type APIRequestContext,
  type APIResponse,
  type Page,
} from "@playwright/test";

const WEB = "https://caseops.ai";
const API = "https://api.caseops.ai";
const SLUG = "caseops-ip-qa";
const EMAIL = "ip-qa-bot@caseops.ai";
const RESERVED_PREFIX = "IPLF-037B renewal synthetic ";
const RESERVED_DESCRIPTION =
  "Synthetic production renewal acceptance only; no client or legal effect.";

type Json = Record<string, any>;
type Auth = {
  access_token: string;
  company: { id: string; slug: string };
  user: { email: string };
  membership: { id: string; role: string };
  capabilities: string[];
};
type Matter = {
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
  updated_at: string;
};
type Docket = {
  id: string;
  title: string;
  primary_identifier: string | null;
  lifecycle_version: number;
  cost_items?: Array<{ id: string; evidence_reference: string }>;
};
type Deadline = {
  id: string;
  deadline_kind: string;
  trigger_event_id: string | null;
  state: string;
  version: number;
};
type Fixture = {
  matter: Matter;
  docket: Docket;
  registrationId: string;
  renewalId: string;
  graceId: string;
  term?: Json;
  filingId?: string;
  acceptanceId?: string;
  nextTermId?: string;
  feeId?: string;
  certificateId?: string;
};

let api: APIRequestContext;
let auth: Auth;
let supervisorMembershipId: string | undefined;
const cleanupMatters = new Map<string, Matter>();

function required(name: string): string {
  const value = (process.env[name] ?? "").trim();
  if (!value)
    throw new Error(`${name} is required for IPLF-037B production acceptance.`);
  return value;
}

function headers(): { Authorization: string } {
  return { Authorization: `Bearer ${auth.access_token}` };
}

async function json<T>(
  response: APIResponse,
  expected: number,
  operation: string,
): Promise<T> {
  const text = await response.text();
  expect(response.status(), `${operation}: ${text}`).toBe(expected);
  return JSON.parse(text) as T;
}

async function authenticate(): Promise<Auth> {
  const expectedSha = required("CASEOPS_EXPECTED_RELEASE_SHA").toLowerCase();
  expect(expectedSha).toMatch(/^[0-9a-f]{40}$/);
  const [apiBuild, webBuild] = await Promise.all([
    api.get(`${API}/api/build`),
    api.get(`${WEB}/api/release-identity`),
  ]);
  expect(
    (await json<{ release_sha: string }>(apiBuild, 200, "read API identity"))
      .release_sha,
  ).toBe(expectedSha);
  expect(
    (await json<{ release_sha: string }>(webBuild, 200, "read web identity"))
      .release_sha,
  ).toBe(expectedSha);
  const session = await json<Auth>(
    await api.post(`${API}/api/auth/login`, {
      data: {
        company_slug: SLUG,
        email: EMAIL,
        password: required("CASEOPS_IP_QA_PASSWORD"),
      },
    }),
    200,
    "authenticate dedicated IP QA owner",
  );
  expect(session).toMatchObject({
    company: { slug: SLUG },
    user: { email: EMAIL },
    membership: { role: "owner" },
  });
  expect(session.capabilities).toEqual(
    expect.arrayContaining(["ip:read", "ip:write"]),
  );
  return session;
}

async function createSupervisor(): Promise<string> {
  const nonce = randomBytes(8).toString("hex");
  const result = await json<{ membership_id: string }>(
    await api.post(`${API}/api/companies/current/users`, {
      headers: headers(),
      data: {
        full_name: `IPLF-037B synthetic supervisor ${nonce}`,
        email: `caseops-iplf037b-supervisor-${nonce}@example.com`,
        password: `Qa7!${randomBytes(24).toString("base64url")}`,
        role: "member",
      },
    }),
    200,
    "create disposable renewal supervisor",
  );
  return result.membership_id;
}

async function deactivateSupervisor(): Promise<void> {
  if (!supervisorMembershipId) return;
  const result = await json<Json>(
    await api.patch(
      `${API}/api/companies/current/users/${supervisorMembershipId}`,
      {
        headers: headers(),
        data: { is_active: false },
      },
    ),
    200,
    "deactivate disposable renewal supervisor",
  );
  expect(result.membership_active).toBe(false);
  expect(result.user_active).toBe(false);
  supervisorMembershipId = undefined;
}

function isReserved(matter: Matter): boolean {
  return (
    matter.title.startsWith(RESERVED_PREFIX) &&
    /^IP-REN-[0-9A-F]{16}$/.test(matter.matter_code) &&
    matter.matter_type === "synthetic_release_canary" &&
    matter.client_name === "CaseOps Synthetic QA" &&
    matter.practice_area === "intellectual_property" &&
    matter.forum_level === "tribunal" &&
    matter.description === RESERVED_DESCRIPTION
  );
}

async function disposeMatter(matter: Matter): Promise<void> {
  const current = await json<Matter>(
    await api.get(`${API}/api/matters/${matter.id}`, { headers: headers() }),
    200,
    `read reserved Matter ${matter.id}`,
  );
  expect(current.company_id).toBe(auth.company.id);
  expect(
    isReserved(current),
    "cleanup refuses non-reserved Matter shapes",
  ).toBe(true);
  if (current.status === "disposed") return;
  const disposed = await json<Matter>(
    await api.patch(`${API}/api/matters/${current.id}/lifecycle/status`, {
      headers: headers(),
      data: {
        to_status: "disposed",
        expected_from_status: current.status,
        expected_updated_at: current.updated_at,
        reason:
          "Dispose completed IPLF-037B synthetic production acceptance data.",
      },
    }),
    200,
    `dispose reserved Matter ${matter.id}`,
  );
  expect(disposed).toMatchObject({ status: "disposed", is_active: false });
}

async function createMatterAndDocket(
  label: string,
): Promise<{ matter: Matter; docket: Docket }> {
  const nonce = randomBytes(8).toString("hex").toUpperCase();
  const matter = await json<Matter>(
    await api.post(`${API}/api/matters/`, {
      headers: headers(),
      data: {
        title: `${RESERVED_PREFIX}${label} ${nonce}`,
        matter_code: `IP-REN-${nonce}`,
        matter_type: "synthetic_release_canary",
        client_name: "CaseOps Synthetic QA",
        status: "intake",
        practice_area: "intellectual_property",
        forum_level: "tribunal",
        description: RESERVED_DESCRIPTION,
      },
    }),
    200,
    `create ${label} synthetic Matter`,
  );
  cleanupMatters.set(matter.id, matter);
  await json(
    await api.post(`${API}/api/matters/${matter.id}/conflict-checks`, {
      headers: headers(),
      data: {
        opposing_party_name: `Synthetic Opponent ${nonce}`,
        related_party_names: [],
      },
    }),
    200,
    `clear ${label} synthetic conflict check`,
  );
  const active = await json<Matter>(
    await api.patch(`${API}/api/matters/${matter.id}`, {
      headers: headers(),
      data: { status: "active", expected_updated_at: matter.updated_at },
    }),
    200,
    `activate ${label} synthetic Matter`,
  );
  cleanupMatters.set(active.id, active);
  const docket = await json<Docket>(
    await api.post(`${API}/api/ip/dockets`, {
      headers: headers(),
      data: {
        title: `ASTER ${label} renewal ${nonce}`,
        matter_id: matter.id,
        primary_identifier: `TM-REN-${nonce}`,
        restricted: false,
        particulars: {
          form_key: "TM-A",
          form_version: "2026.1",
          mark_kind: "word",
          representation: {
            text: `ASTER ${nonce}`,
            evidence_reference: `qa:renewal:${nonce}`,
          },
          classes: [
            { class_number: 42, specification: "Synthetic QA legal software" },
          ],
          use_priority: null,
          parties: [
            { role: "registered_proprietor", name: "CaseOps Synthetic QA" },
          ],
          agent: null,
          filing_manifest: [
            {
              key: "representation",
              label: "Synthetic representation",
              required: true,
              evidence_reference: `qa:renewal:${nonce}`,
            },
          ],
        },
      },
    }),
    201,
    `create ${label} synthetic docket`,
  );
  return { matter: active, docket };
}

async function readDocket(docketId: string): Promise<Docket> {
  return json(
    await api.get(`${API}/api/ip/dockets/${docketId}`, { headers: headers() }),
    200,
    `read docket ${docketId}`,
  );
}

async function appendEvent(
  docketId: string,
  eventKind: string,
  nonce: string,
): Promise<string> {
  const docket = await readDocket(docketId);
  const event = await json<{ id: string }>(
    await api.post(`${API}/api/ip/dockets/${docketId}/events`, {
      headers: headers(),
      data: {
        expected_lifecycle_version: docket.lifecycle_version,
        expected_application_version: null,
        application_id: null,
        proceeding_id: null,
        event_kind: eventKind,
        source: "registry",
        source_reference: `qa:iplf-037b:${eventKind}:${nonce}`,
        effective_at: new Date().toISOString(),
        responsible_membership_id: auth.membership.id,
        reason: null,
        evidence_refs: [`qa:iplf-037b:${eventKind}:${nonce}`],
        document_refs: [],
        resulting_deadline_refs: [],
        candidate_status: "confirmed",
        acknowledged_exception_codes: [],
        payload: { synthetic_qa: true, no_legal_effect: true },
      },
    }),
    201,
    `append ${eventKind} event`,
  );
  return event.id;
}

function isoAfter(days: number): string {
  const value = new Date();
  value.setUTCDate(value.getUTCDate() + days);
  return value.toISOString().slice(0, 10);
}

async function createDeadline(
  docketId: string,
  ruleVersionId: string,
  calendarVersionId: string,
  title: string,
  triggerEventId: string,
  correctedResultOn?: string,
): Promise<Deadline> {
  const proposed = await json<Deadline>(
    await api.post(`${API}/api/ip/dockets/${docketId}/deadlines`, {
      headers: headers(),
      data: {
        title,
        trigger_event_id: triggerEventId,
        rule_version_id: ruleVersionId,
        calendar_version_id: calendarVersionId,
        base_date: isoAfter(0),
        base_date_certainty: "certain",
        date_precision: "date",
        is_critical: true,
      },
    }),
    201,
    `propose ${title}`,
  );
  const confirmed = await json<Deadline>(
    await api.post(`${API}/api/ip/deadlines/${proposed.id}/confirm`, {
      headers: headers(),
      data: {
        expected_version: proposed.version,
        responsibilities: [
          {
            membership_id: auth.membership.id,
            role: "primary",
            accepted: true,
            replacement_source: "iplf-037b-production-canary",
            escalation_policy: { supervisor_after_days: 0 },
          },
          {
            membership_id: supervisorMembershipId,
            role: "supervisor",
            accepted: true,
            replacement_source: "iplf-037b-production-canary",
            escalation_policy: { supervisor_after_days: 0 },
          },
        ],
        reminder_offsets_days: [],
        corrected_result_on: correctedResultOn ?? null,
        correction_reason: correctedResultOn
          ? "Synthetic QA date correction for deterministic exception proof."
          : null,
        correction_evidence_reference: correctedResultOn
          ? "qa:iplf-037b:deterministic-date"
          : null,
      },
    }),
    200,
    `confirm ${title}`,
  );
  expect(confirmed.state).toBe("confirmed");
  return confirmed;
}

async function createFixture(label: "normal" | "grace"): Promise<Fixture> {
  const ids = {
    calendar: required("CASEOPS_IP_RENEWAL_CALENDAR_VERSION_ID"),
    renewal: required("CASEOPS_IP_RENEWAL_RULE_VERSION_ID"),
    grace: required("CASEOPS_IP_RENEWAL_GRACE_RULE_VERSION_ID"),
  };
  const { matter, docket } = await createMatterAndDocket(label);
  const nonce = docket.primary_identifier!;
  const registrationId = await appendEvent(docket.id, "registration", nonce);
  const renewal = await createDeadline(
    docket.id,
    ids.renewal,
    ids.calendar,
    `${label} renewal due`,
    registrationId,
    label === "grace" ? isoAfter(-1) : undefined,
  );
  const grace = await createDeadline(
    docket.id,
    ids.grace,
    ids.calendar,
    `${label} renewal grace ends`,
    registrationId,
    label === "grace" ? isoAfter(30) : undefined,
  );
  return {
    matter,
    docket,
    registrationId,
    renewalId: renewal.id,
    graceId: grace.id,
  };
}

async function uploadAcceptedCertificate(fixture: Fixture): Promise<string> {
  await json(
    await api.post(`${API}/api/ip/document-taxonomy/seed`, {
      headers: headers(),
    }),
    200,
    "seed IP document taxonomy",
  );
  const nonce = fixture.docket.primary_identifier!;
  const uploaded = await json<Json>(
    await api.post(`${API}/api/ip/documents/upload`, {
      headers: headers(),
      multipart: {
        metadata_json: JSON.stringify({
          taxonomy_key: "evidence",
          title: `Accepted renewal certificate ${nonce}`,
          confidentiality: "internal",
          is_privileged: false,
          client_code: "CASEOPS-QA",
          asset_type: "Trademark",
          mark: `ASTER ${nonce}`,
          jurisdiction: "IN",
          document_date: isoAfter(0),
          links: [{ target_type: "docket", target_id: fixture.docket.id }],
        }),
        upload: {
          name: `renewal-certificate-${nonce}.txt`,
          mimeType: "text/plain",
          buffer: Buffer.from(
            `Synthetic renewal certificate ${nonce}; no legal effect.`,
          ),
        },
      },
    }),
    200,
    "upload synthetic renewal certificate",
  );
  expect(uploaded.outcome).toBe("created");
  const documentId = uploaded.document.id as string;
  let document = uploaded.document as Json;
  await expect
    .poll(
      async () => {
        document = await json<Json>(
          await api.get(`${API}/api/ip/documents/${documentId}`, {
            headers: headers(),
          }),
          200,
          "poll renewal certificate processing",
        );
        return document.versions[0].processing_status as string;
      },
      { timeout: 60_000 },
    )
    .toBe("indexed");
  const targets: Record<string, string> = {
    draft: "review",
    review: "approved",
    approved: "filed",
    filed: "served",
    served: "accepted",
  };
  while (document.versions[0].state !== "accepted") {
    const version = document.versions[0];
    const target = targets[version.state];
    expect(
      target,
      `unexpected certificate state ${version.state}`,
    ).toBeTruthy();
    document = await json<Json>(
      await api.post(
        `${API}/api/ip/documents/${documentId}/versions/${version.version}/transition`,
        {
          headers: headers(),
          data: {
            expected_current_version: document.current_version,
            expected_state: version.state,
            target_state: target,
          },
        },
      ),
      200,
      `transition renewal certificate to ${target}`,
    );
  }
  return documentId;
}

async function completeFixtureEvidence(fixture: Fixture): Promise<Fixture> {
  const nonce = fixture.docket.primary_identifier!;
  fixture.filingId = await appendEvent(fixture.docket.id, "filing", nonce);
  fixture.acceptanceId = await appendEvent(
    fixture.docket.id,
    "acceptance",
    nonce,
  );
  fixture.nextTermId = (
    await createDeadline(
      fixture.docket.id,
      required("CASEOPS_IP_RENEWAL_NEXT_TERM_RULE_VERSION_ID"),
      required("CASEOPS_IP_RENEWAL_CALENDAR_VERSION_ID"),
      "Next renewal due",
      fixture.acceptanceId,
    )
  ).id;
  const evidenceReference = `qa:iplf-037b:fee:${nonce}`;
  const withCost = await json<Docket>(
    await api.post(`${API}/api/ip/dockets/${fixture.docket.id}/cost-items`, {
      headers: headers(),
      data: {
        category: "official_fee",
        description: "Renewal official fee quote",
        amount_minor: 900000,
        currency: "INR",
        evidence_reference: evidenceReference,
        billable: false,
        cost_nature: "estimate",
        rate_confidential: false,
      },
    }),
    200,
    "create renewal fee evidence",
  );
  fixture.feeId = withCost.cost_items?.find(
    (item) => item.evidence_reference === evidenceReference,
  )?.id;
  expect(fixture.feeId).toBeTruthy();
  fixture.certificateId = await uploadAcceptedCertificate(fixture);
  return fixture;
}

async function createTerm(fixture: Fixture): Promise<Fixture> {
  fixture.term = await json<Json>(
    await api.post(`${API}/api/ip/dockets/${fixture.docket.id}/renewal-terms`, {
      headers: headers(),
      data: {
        registration_event_id: fixture.registrationId,
        renewal_deadline_id: fixture.renewalId,
        grace_deadline_id: fixture.graceId,
        fee_cost_item_id: fixture.feeId ?? null,
      },
    }),
    201,
    "create renewal term",
  );
  return fixture;
}

async function signIn(page: Page): Promise<void> {
  await page.goto(`${WEB}/sign-in`);
  await page.locator("#company-slug").fill(SLUG);
  await page.locator("#email").fill(EMAIL);
  await page.locator("#password").fill(required("CASEOPS_IP_QA_PASSWORD"));
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  await page.waitForURL(/\/app(?:[/?]|$)/);
}

test.beforeEach(async () => {
  api = await playwrightRequest.newContext({ maxRedirects: 0 });
  auth = await authenticate();
  supervisorMembershipId = await createSupervisor();
});

test.afterEach(async () => {
  const failures: string[] = [];
  for (const matter of [...cleanupMatters.values()].reverse()) {
    try {
      await disposeMatter(matter);
    } catch (error) {
      failures.push(`${matter.id}: ${String(error)}`);
    }
  }
  try {
    await deactivateSupervisor();
  } catch (error) {
    failures.push(`supervisor: ${String(error)}`);
  }
  cleanupMatters.clear();
  await api.dispose();
  expect(
    failures,
    "all reserved synthetic production data must be retired",
  ).toEqual([]);
});

test("IPLF-037B production completes UJ-26 and reconciles grace explicitly", async ({
  page,
}) => {
  const normal = await createTerm(
    await completeFixtureEvidence(await createFixture("normal")),
  );
  await signIn(page);
  await page.goto(`${WEB}/app/ip/renewals`);
  await expect(
    page.getByRole("heading", { name: "Trademark renewals" }),
  ).toBeVisible();
  await expect(page.getByText(normal.docket.title).first()).toBeVisible();
  await expect(
    page
      .getByText(
        "Synthetic IPLF-037B production acceptance rule; no legal effect",
      )
      .first(),
  ).toBeVisible();
  await expect(
    page.getByText("caseops-ip-qa-iplf-037b-v1").first(),
  ).toBeVisible();
  await expect(
    page.getByText(/Renewal official fee quote/).first(),
  ).toBeVisible();

  await page
    .getByRole("button", { name: "Schedule instruction notifications" })
    .click();
  await expect(page.getByText(/1 delivered · 6 queued/)).toBeVisible();
  await page
    .getByLabel("Authority name")
    .fill("CaseOps Synthetic QA authority");
  await page.getByLabel("Authority reference").fill("QA-RENEWAL-AUTHORITY");
  await page.getByLabel("Evidence reference").fill("qa:iplf-037b:instruction");
  await page.getByRole("button", { name: "Record instruction" }).click();
  await expect(page.getByText(/1 delivered · 0 queued/)).toBeVisible();
  await page
    .getByLabel("Review reason")
    .fill("Synthetic authority and scope verified");
  await page.getByRole("button", { name: "Accept" }).click();
  await expect(page.getByRole("table").getByText("Instructed")).toBeVisible();

  await page.getByLabel("Reason").fill("Synthetic provider filing initiated");
  await page.getByLabel("Filing initiation reference").fill("QA-PROVIDER-ACK");
  await page.getByRole("button", { name: "Record transition" }).click();
  await expect(
    page.getByRole("table").getByText("Filing in progress"),
  ).toBeVisible();
  await page
    .getByLabel("Reason")
    .fill("Confirmed synthetic filing event linked");
  await page.getByLabel("Confirmed filing event ID").fill(normal.filingId!);
  await page.getByRole("button", { name: "Record transition" }).click();
  await expect(page.getByRole("table").getByText("Filed")).toBeVisible();
  await page
    .getByLabel("Reason")
    .fill("Synthetic registry acceptance verified");
  await page
    .getByLabel("Registry acceptance event ID")
    .fill(normal.acceptanceId!);
  await page.getByRole("button", { name: "Record transition" }).click();
  await expect(
    page.getByRole("table").getByText("Registry accepted"),
  ).toBeVisible();
  await page
    .getByLabel("Reason")
    .fill("Synthetic certificate and next term verified");
  await page
    .getByLabel("Accepted certificate document ID")
    .fill(normal.certificateId!);
  await page
    .getByLabel("Confirmed next-term deadline ID")
    .fill(normal.nextTermId!);
  await page.getByRole("button", { name: "Record transition" }).click();
  await expect(page.getByRole("table").getByText("Completed")).toBeVisible();
  await expect(page.getByText("This renewal term is closed.")).toBeVisible();

  const persisted = await json<Json>(
    await api.get(`${API}/api/ip/dockets/${normal.docket.id}/renewal-terms`, {
      headers: headers(),
    }),
    200,
    "read completed production renewal term",
  );
  expect(persisted.items[0]).toMatchObject({
    state: "completed",
    filing_initiated_reference: "QA-PROVIDER-ACK",
    filing_event_id: normal.filingId,
    acceptance_event_id: normal.acceptanceId,
    certificate_document_id: normal.certificateId,
    next_term_deadline_id: normal.nextTermId,
  });

  const grace = await createTerm(await createFixture("grace"));
  await page.getByRole("button", { name: "Refresh" }).click();
  await page.getByLabel("Renewal state").selectOption("grace");
  await expect(page.getByText("Recorded state: Due")).toBeVisible();
  await expect(page.getByText(/calendar is in grace/i)).toBeVisible();
  await page.getByLabel("Next state").selectOption("grace");
  await page
    .getByLabel("Reason")
    .fill("Verified synthetic renewal grace period entered");
  await page.getByRole("button", { name: "Record transition" }).click();
  await expect(page.getByText("Recorded state: Due")).not.toBeVisible();
  const gracePersisted = await json<Json>(
    await api.get(`${API}/api/ip/dockets/${grace.docket.id}/renewal-terms`, {
      headers: headers(),
    }),
    200,
    "read reconciled grace renewal term",
  );
  expect(gracePersisted.items[0].state).toBe("grace");

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(
    page.getByRole("heading", { name: "Trademark renewals" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});
