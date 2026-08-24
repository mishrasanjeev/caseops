/** IPLF-052 / UJ-21 / UJ-33: journal watch, review, corrections, and handoffs. */

import { spawnSync } from "node:child_process";
import path from "node:path";

import { expect, request, test, type APIRequestContext, type Page } from "@playwright/test";

import { apiBaseUrl, e2eEnv, repoRoot } from "./support/env";

const PASSWORD = "JournalWatch2026!";

function grantIpEntitlement(companyId: string): void {
  const python = process.platform === "win32"
    ? path.join(repoRoot, "apps", "api", ".venv", "Scripts", "python.exe")
    : path.join(repoRoot, "apps", "api", ".venv", "bin", "python");
  const script = [
    "import os",
    "from caseops_api.db.models import BillingSubscription",
    "from caseops_api.db.session import get_session_factory",
    "session=get_session_factory()()",
    "session.add(BillingSubscription(company_id=os.environ['CASEOPS_E2E_COMPANY_ID'],status='manual_active',segment='law_firm',source='iplf_052_playwright',externally_billable=False,entitlement_overrides_json={'ip_workspace': True}))",
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
  const slug = `journal-watch-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  const email = `owner-${slug}@example.com`;
  const response = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "IPLF 052 Journal Watch LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Journal Watch Partner",
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
  const configured = await api.put(`${apiBaseUrl}/api/ip/workspace/configuration`, {
    headers,
    data: {
      expected_version: null,
      enabled_asset_types: ["trademark"],
      jurisdictions: ["IN"],
      offices: ["Trade Marks Registry Delhi"],
      timezone: "Asia/Kolkata",
      holiday_calendar_key: "journal-watch-calendar",
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
  });
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

async function createApplication(api: APIRequestContext, headers: Record<string, string>) {
  const response = await api.post(`${apiBaseUrl}/api/ip/trademark-applications/manual`, {
    headers,
    data: {
      title: "ASTER JOURNAL WATCH",
      restricted: false,
      asset_title: "ASTER JOURNAL WATCH",
      jurisdiction: "IN",
      office: "Trade Marks Registry Delhi",
      filing_phase: "draft",
      source_pending_identifier_allocation: false,
      application_number: {
        raw_value: "TM-APP-052-2026",
        source: "e2e journal watch fixture",
        effective_from: "2026-08-24",
        is_primary: true,
      },
      particulars: {
        form_key: "TM-A",
        form_version: "2026.1",
        mark_kind: "word",
        representation: { text: "ASTER", evidence_reference: "e2e:aster-watch" },
        classes: [
          { class_number: 9, specification: "Downloadable legal software" },
          { class_number: 42, specification: "Legal software as a service" },
        ],
        use_priority: null,
        parties: [{ role: "applicant", name: "Aster Watch Limited" }],
        agent: null,
        filing_manifest: [
          {
            key: "representation",
            label: "Mark representation",
            required: true,
            evidence_reference: "e2e:aster-watch",
          },
        ],
      },
    },
  });
  expect(response.status(), await response.text()).toBe(201);
  return response.json();
}

async function signIn(page: Page, slug: string, email: string): Promise<void> {
  const login = await page.request.post(`${apiBaseUrl}/api/auth/login`, {
    data: { company_slug: slug, email, password: PASSWORD },
  });
  expect(login.status(), await login.text()).toBe(200);
  const session = await login.json();
  await page.goto("/");
  await page.evaluate((context) => {
    window.localStorage.setItem("caseops.session.context", JSON.stringify(context));
  }, {
    company: session.company,
    user: session.user,
    membership: session.membership,
    capabilities: session.capabilities,
  });
}

function publication(input: {
  applicationId: string;
  journalNumber: string;
  journalDate: string;
  applicationNumber?: string;
  markText: string;
  sourceStatus: "available" | "unavailable" | "stale";
  sourceRetrievedAt: string;
  kind?: "advertisement" | "correction" | "readvertisement";
  supersedes?: string | null;
  correctionReason?: string | null;
}) {
  return {
    application_id: input.applicationId,
    journal_number: input.journalNumber,
    journal_date: input.journalDate,
    publication_kind: input.kind ?? "advertisement",
    application_number: input.applicationNumber ?? "TM-CANDIDATE-052",
    mark_text: input.markText,
    device_reference: "https://evidence.example/aster-watch-device.png",
    proprietor_name: "Aster Candidate Technologies",
    office: "IP India",
    jurisdiction: "IN",
    class_numbers: [9, 42],
    goods_services: { "9": ["downloadable legal software"], "42": ["SaaS"] },
    publication_scope: { scope_kind: "partial", published_classes: [9, 42] },
    source_url: `https://ipindia.gov.in/journal/${input.journalNumber}/page/412`,
    source_page: "412",
    source_status: input.sourceStatus,
    source_retrieved_at: input.sourceRetrievedAt,
    parser_version: "e2e-manual-journal-v1",
    attribution: { publisher: "IP India", capture_method: "manual" },
    raw_evidence: { heading: `Trade Marks Journal ${input.journalNumber}` },
    supersedes_publication_id: input.supersedes ?? null,
    correction_reason: input.correctionReason ?? null,
  };
}

async function ingest(
  api: APIRequestContext,
  headers: Record<string, string>,
  key: string,
  item: ReturnType<typeof publication>,
) {
  return api.post(`${apiBaseUrl}/api/ip/watch/journal-ingestions`, {
    headers,
    data: {
      idempotency_key: key,
      provider_key: "ipindia-journal-manual",
      external_call: false,
      cost_minor: 10,
      currency: "INR",
      publications: [item],
    },
  });
}

test("IPLF-052 completes journal watch, correction review, and every canonical handoff", async ({ page }) => {
  test.setTimeout(360_000);
  page.setDefaultTimeout(25_000);
  const api = await request.newContext();
  const tenant = await bootstrap(api);
  const headers = await enableWorkspace(api, tenant);
  const application = await createApplication(api, headers);
  await signIn(page, tenant.slug, tenant.email);

  await page.setViewportSize({ width: 360, height: 800 });
  await page.goto("/app/ip/watch");
  await expect(page.getByRole("heading", { name: "Trademark journal watch" })).toBeVisible();
  const viewButtons = ["Hits", "Profiles", "Journal intake", "Runs"].map((name) =>
    page.getByRole("button", { name }),
  );
  const boxes: Array<{ x: number; y: number; width: number; height: number }> = [];
  for (const button of viewButtons) {
    await expect(button).toBeVisible();
    const box = await button.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.width).toBeGreaterThan(100);
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(360);
    boxes.push(box!);
  }
  for (let left = 0; left < boxes.length; left += 1) {
    for (let right = left + 1; right < boxes.length; right += 1) {
      const horizontal = boxes[left].x < boxes[right].x + boxes[right].width
        && boxes[left].x + boxes[left].width > boxes[right].x;
      const vertical = boxes[left].y < boxes[right].y + boxes[right].height
        && boxes[left].y + boxes[left].height > boxes[right].y;
      expect(horizontal && vertical).toBe(false);
    }
  }
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole("button", { name: "Profiles" }).click();
  await page.getByLabel("Profile name").fill("ASTER word, phonetic and class watch");
  await page.getByLabel("Word terms").fill("ASTER");
  await page.getByLabel("Phonetic terms").fill("ASTER");
  await page.getByLabel("Nice classes").fill("9, 42");
  await page.getByLabel("Jurisdictions").fill("IN");
  const profileResponse = page.waitForResponse(
    (response) => response.url().endsWith("/api/ip/watch/profiles") && response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Create profile" }).click();
  const createdProfile = await profileResponse;
  expect(createdProfile.status(), await createdProfile.text()).toBe(201);
  await expect(page.getByRole("heading", { name: "ASTER word, phonetic and class watch" })).toBeVisible();

  const originalItem = publication({
    applicationId: application.application.id,
    journalNumber: "TMJ-2248",
    journalDate: "2026-08-21",
    markText: "ASTER PRIME",
    sourceStatus: "available",
    sourceRetrievedAt: "2026-08-21T06:00:00Z",
  });
  const originalResponse = await ingest(api, headers, "iplf052-original-0001", originalItem);
  expect(originalResponse.status(), await originalResponse.text()).toBe(201);
  const original = await originalResponse.json();
  expect(original.hits).toHaveLength(1);

  const replayResponse = await ingest(api, headers, "iplf052-original-0001", originalItem);
  expect(replayResponse.status(), await replayResponse.text()).toBe(201);
  const replay = await replayResponse.json();
  expect(replay.idempotent_replay).toBe(true);
  expect(replay.publications[0].id).toBe(original.publications[0].id);
  expect(replay.hits[0].id).toBe(original.hits[0].id);

  const conflictingItem = publication({
    applicationId: application.application.id,
    journalNumber: "TMJ-2249",
    journalDate: "2026-08-22",
    markText: "ASTER CHANGED",
    sourceStatus: "available",
    sourceRetrievedAt: "2026-08-22T06:00:00Z",
  });
  const conflict = await ingest(api, headers, "iplf052-original-0001", conflictingItem);
  expect(conflict.status(), await conflict.text()).toBe(409);

  const unavailableResponse = await ingest(
    api,
    headers,
    "iplf052-unavailable-0001",
    publication({
      applicationId: application.application.id,
      journalNumber: "TMJ-2250",
      journalDate: "2026-08-23",
      applicationNumber: "TM-CANDIDATE-BLOCKED-052",
      markText: "ASTER BLOCKED",
      sourceStatus: "unavailable",
      sourceRetrievedAt: "2026-08-23T06:00:00Z",
    }),
  );
  expect(unavailableResponse.status(), await unavailableResponse.text()).toBe(201);
  const unavailable = await unavailableResponse.json();
  const blockedDecision = await api.post(
    `${apiBaseUrl}/api/ip/watch/hits/${unavailable.hits[0].id}/disposition`,
    {
      headers,
      data: {
        expected_version: unavailable.hits[0].version,
        disposition: "relevant",
        reason: "This final decision must be blocked while source is unavailable.",
        source_confirmed: false,
      },
    },
  );
  expect(blockedDecision.status(), await blockedDecision.text()).toBe(422);

  const correctionResponse = await ingest(
    api,
    headers,
    "iplf052-correction-0001",
    publication({
      applicationId: application.application.id,
      journalNumber: "TMJ-2252",
      journalDate: "2026-08-24",
      markText: "ASTER PRIME",
      sourceStatus: "available",
      sourceRetrievedAt: "2026-09-01T10:00:00Z",
      kind: "readvertisement",
      supersedes: original.publications[0].id,
      correctionReason: "Published goods scope corrected and re-advertised.",
    }),
  );
  expect(correctionResponse.status(), await correctionResponse.text()).toBe(201);
  const correction = await correctionResponse.json();
  expect(correction.hits[0].duplicate_of_hit_id).toBe(original.hits[0].id);
  expect(correction.hits[0].stale_source_alert).toBe(true);

  await page.getByRole("button", { name: "Hits" }).click();
  await page.getByRole("button", { name: "Refresh" }).click();
  await page.getByRole("button").filter({ hasText: "ASTER PRIME" }).first().click();
  await expect(page.getByText(/Prior hit/)).toBeVisible();
  await expect(page.getByText("AI assistance is advisory.")).toBeVisible();
  await expect(page.getByRole("link", { name: "Open source" })).toHaveAttribute(
    "href",
    correction.publications[0].source_url,
  );

  await page.getByLabel("Disposition").selectOption("relevant");
  await page.getByLabel("Reason").fill("Official re-advertisement confirms overlapping mark and classes.");
  await page.getByLabel(/I opened and confirmed/).check();
  const reviewResponse = page.waitForResponse(
    (response) => response.url().endsWith(`/api/ip/watch/hits/${correction.hits[0].id}/disposition`),
  );
  await page.getByRole("button", { name: "Record review" }).click();
  expect((await reviewResponse).status()).toBe(200);
  await expect(page.getByRole("heading", { name: "Canonical handoff" })).toBeVisible();

  const handoffTargets = new Map<string, string>();
  async function createHandoff(kind: string, targetType: string) {
    const responsePromise = page.waitForResponse(
      (response) =>
        response.url().endsWith(`/api/ip/watch/hits/${correction.hits[0].id}/handoffs`) &&
        response.request().method() === "POST",
    );
    await page.getByRole("button", { name: `Create ${kind}` }).click();
    const response = await responsePromise;
    expect(response.status(), await response.text()).toBe(201);
    const body = await response.json();
    expect(body.target_type).toBe(targetType);
    handoffTargets.set(body.handoff_kind, body.target_id);
  }

  await createHandoff("opposition", "ip_proceeding");
  await page.getByRole("button", { name: /^task/ }).click();
  await createHandoff("task", "matter_task");
  await page.getByRole("button", { name: /^deadline/ }).click();
  await page.getByLabel("Due date").fill("2026-09-30");
  await createHandoff("deadline", "matter_deadline");
  await page.getByRole("button", { name: /^client report item/ }).click();
  await createHandoff("client report item", "ip_docket_event");
  await page.getByRole("button", { name: /^enforcement matter/ }).click();
  await page.getByLabel("Matter code").fill(`ENF-052-${Date.now()}`);
  await createHandoff("enforcement matter", "matter");

  expect(handoffTargets.size).toBe(5);
  await page.getByRole("button", { name: "Runs" }).click();
  await expect(page.getByText("ipindia-journal-manual").first()).toBeVisible();

  await page.getByRole("button", { name: "Hits" }).click();
  await page.getByRole("button").filter({ hasText: "ASTER BLOCKED" }).click();
  await expect(page.getByText(/Final source-dependent dispositions are blocked/)).toBeVisible();

  const workspace = await api.get(
    `${apiBaseUrl}/api/ip/watch?docket_id=${application.docket.id}&limit=250`,
    { headers },
  );
  expect(workspace.status(), await workspace.text()).toBe(200);
  const evidence = await workspace.json();
  expect(evidence.handoffs.map((item: { handoff_kind: string }) => item.handoff_kind).sort()).toEqual(
    ["client_report_item", "deadline", "enforcement_matter", "opposition", "task"],
  );
  expect(evidence.handoffs.every((item: { source_snapshot_json: object; reviewer_decision_json: object }) =>
    Object.keys(item.source_snapshot_json).length > 0 &&
    Object.keys(item.reviewer_decision_json).length > 0,
  )).toBe(true);
  await api.dispose();
});
