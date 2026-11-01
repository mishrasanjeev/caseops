/**
 * Adjacent defects found while fixing Ram's batch 4 (CaseOps_Bugs (4).xlsx):
 *
 * B4-ADJ-01  A walled admin with portal:invite could grant portal access to a
 *            Matter they cannot see: the picker was wall-scoped, the API was not.
 * B4-ADJ-08  A rule that needs an active working calendar was enforced only in
 *            the browser, and the rule form preselected the first calendar.
 * B4-ADJ-12  A registry identity's kind was free text and a target outside the
 *            docket answered 404 instead of a field-anchored 422.
 *
 * B4-ADJ-04 (web schema drift on calendar display_type) has no visible change:
 * the API always sends the field, so it is proven by vitest, not here.
 *
 * Production runs sign in as Ram on test-legal and are read-only: the registry
 * checks send only requests the server refuses and assert nothing was written.
 * The portal-invite and rule-governance journeys are [local-only]: each needs a
 * second same-company person (an ethical wall on another admin; an independent
 * calendar approver), Ram is the only member who signs in on test-legal, and
 * both journeys change walls or working calendars that the product cannot retire.
 */
import {
  expect, request as playwrightRequest, test, type APIRequestContext, type Locator, type Page, type Response,
} from "@playwright/test";

import {
  addLocalColleague, deadSelects, expectNoPageOverflow, expectOnScreen, json, markPositive, prepareTester, signIn,
  stamp, type TesterCredentials, type TesterRuntime,
} from "./support/ram-bugs4";
import { noPaidProviderHeaders } from "./support/cost-controls";

test.use({ trace: "off", screenshot: "off", video: "off", storageState: { cookies: [], origins: [] } });
test.describe.configure({ mode: "default", retries: 0 });

const MOBILE = { width: 393, height: 851 };

type Matter = { id: string; matter_code: string; title: string; status: string; updated_at: string };
type RegistryTarget = { docketId: string; applicationId: string; otherApplicationId: string };
type Calendar = { id: string; key: string; status: string; name: string; version: number };

function code(label: string): string {
  return stamp(label).replace(/[^A-Za-z0-9]+/g, "-").toUpperCase().slice(0, 40);
}

function responseTo(page: Page, path: RegExp, method: string): Promise<Response> {
  return page.waitForResponse((row) => path.test(new URL(row.url()).pathname) && row.request().method() === method);
}

type Colleague = { credentials: TesterCredentials; membershipId: string; api: APIRequestContext };

/**
 * A same-company colleague (local only) with its own cookie-free API context.
 * The shared `request` fixture carries Ram's session cookie, which the API
 * prefers over a bearer header, so a colleague's calls must never go through it.
 */
async function colleague(rt: TesterRuntime, role: "admin" | "partner", name: string): Promise<Colleague> {
  const isolated = await playwrightRequest.newContext();
  let added: { credentials: TesterCredentials; membershipId: string };
  let token: string;
  try {
    added = await addLocalColleague(rt, isolated, role, name);
    token = (await json<{ access_token: string }>(await isolated.post(`${rt.api.origin}/api/auth/login`, {
      headers: noPaidProviderHeaders,
      data: { company_slug: added.credentials.slug, email: added.credentials.email, password: added.credentials.password },
    }), `${role} oracle login`)).access_token;
  } finally {
    await isolated.dispose();
  }
  const api = await playwrightRequest.newContext({
    storageState: { cookies: [], origins: [] },
    extraHTTPHeaders: { ...noPaidProviderHeaders, Authorization: `Bearer ${token}` },
  });
  const me = await json<{ membership: { id: string } }>(await api.get(`${rt.api.origin}/api/auth/me`), `${role} identity`);
  expect(me.membership.id, "The colleague context acts as the colleague, not as Ram").toBe(added.membershipId);
  return { ...added, api };
}

/** Signs the browser in as another person of the same tenant. */
async function switchUser(page: Page, rt: TesterRuntime, credentials: TesterCredentials) {
  await page.context().clearCookies();
  await signIn(page, rt, credentials);
}

// ---------------------------------------------------------------- B4-ADJ-12

/** Two national dockets with an application each, by server identity (read-only in production). */
async function registryTarget(rt: TesterRuntime, request: APIRequestContext): Promise<RegistryTarget> {
  if (rt.local) {
    const created: string[][] = [];
    for (const label of ["B4-ADJ12 TARGET", "B4-ADJ12 OTHER"]) {
      const mark = stamp(label);
      const row = await json(await request.post(`${rt.api.origin}/api/ip/trademark-applications/manual`, {
        headers: rt.headers,
        data: {
          title: mark, restricted: false, asset_title: mark, jurisdiction: "IN", office: "IP India", filing_phase: "draft",
          source_pending_identifier_allocation: false,
          application_number: { raw_value: `${Date.now()}`.slice(-9), source: "local fixture", effective_from: "2026-10-01", is_primary: true },
          particulars: {
            form_key: "TM-A", form_version: "2026.1", mark_kind: "word",
            representation: { text: mark, evidence_reference: "fixture:adj12" },
            classes: [{ class_number: 9, specification: "Downloadable legal software" }],
            use_priority: null, parties: [{ role: "applicant", name: "Test Legal Clients LLP" }], agent: null,
            filing_manifest: [{ key: "representation", label: "Mark representation", required: true, evidence_reference: "fixture:adj12" }],
          },
        },
      }), "Local docket prerequisite", 201);
      created.push([row.docket.id, row.application.id]);
    }
    return { docketId: created[0][0], applicationId: created[0][1], otherApplicationId: created[1][1] };
  }
  const found: string[][] = [];
  let cursor: string | null = null;
  for (let pages = 0; pages < 5 && found.length < 2; pages += 1) {
    const search: URLSearchParams = new URLSearchParams({ record_type: "trademark", limit: "50", ...(cursor ? { cursor } : {}) });
    const page: { dockets: Array<{ id: string; restricted: boolean }>; next_cursor: string | null } = await json(
      await request.get(`${rt.api.origin}/api/ip/dockets?${search}`, { headers: rt.headers }), "Docket oracle");
    for (const docket of page.dockets) {
      if (found.length === 2) break;
      if (docket.restricted) continue;
      const core = await json(await request.get(`${rt.api.origin}/api/ip/dockets/${docket.id}/core-records`, { headers: rt.headers }),
        "Core records oracle");
      if (core.applications.length) found.push([docket.id, core.applications[0].id]);
    }
    cursor = page.next_cursor;
    if (!cursor) break;
  }
  expect(found.length, "test-legal holds two national dockets with an application").toBe(2);
  return { docketId: found[0][0], applicationId: found[0][1], otherApplicationId: found[1][1] };
}

function registryBody(target: RegistryTarget, overrides: Record<string, unknown>) {
  return {
    application_id: target.applicationId, proceeding_id: null, provider_key: "ipindia-registry", office: "IP India",
    jurisdiction: "IN", identifier_kind: "application", raw_identifier: stamp("B4-ADJ12-REFUSED"),
    source_url: "https://tmrsearch.ipindia.gov.in/eregister/", match_confidence: 0.95, match_evidence: { capture: "manual" },
    terms_version: null, capability_version: "manual-evidence-v1", ...overrides,
  };
}

async function linkCount(rt: TesterRuntime, request: APIRequestContext, docketId: string): Promise<number> {
  const page = await json<{ total: number }>(await request.get(
    `${rt.api.origin}/api/ip/registry-links?docket_id=${docketId}&limit=1`, { headers: rt.headers }), "Registry link oracle");
  return page.total;
}

/** The server refuses each wrong target or kind at its field and writes nothing. */
async function registryRefusals(rt: TesterRuntime, request: APIRequestContext, target: RegistryTarget) {
  const before = await linkCount(rt, request, target.docketId);
  const cases: Array<[Record<string, unknown>, string, string]> = [
    [{ application_id: target.otherApplicationId }, "application_id", "registry_target_not_in_docket"],
    [{ identifier_kind: "opposition" }, "identifier_kind", "registry_identifier_kind_mismatch"],
    [{ identifier_kind: "trademark_number" }, "identifier_kind", "literal_error"],
  ];
  for (const [overrides, field, type] of cases) {
    const refused = await request.post(`${rt.api.origin}/api/ip/dockets/${target.docketId}/registry-links`, {
      headers: rt.headers, data: registryBody(target, overrides),
    });
    expect(refused.status(), `${type} is a 422, not a 404`).toBe(422);
    const error = (await refused.json()).errors[0];
    expect(error.loc).toEqual(["body", field]);
    expect(error.type).toBe(type);
  }
  expect(await linkCount(rt, request, target.docketId), "No refused identity was written").toBe(before);
}

/** The identifier type offers only kinds the validator accepts for the chosen record. */
async function registryPicker(page: Page, rt: TesterRuntime, target: RegistryTarget): Promise<Locator> {
  const core = page.waitForResponse((row) => row.url().endsWith(`/api/ip/dockets/${target.docketId}/core-records`));
  await page.goto(`${rt.web.origin}/app/ip/registry?docket=${target.docketId}`);
  expect((await core).status()).toBe(200);
  const main = page.locator("main");
  const record = main.getByRole("combobox", { name: "Legal record" });
  await expect(record).toBeEnabled();
  await record.selectOption(`application:${target.applicationId}`);
  const kind = main.getByRole("combobox", { name: "Identifier type" });
  await expect(kind).toBeEnabled();
  const offered = await kind.locator("option").evaluateAll((rows) => rows.map((row) => (row as HTMLOptionElement).value));
  expect(offered.sort(), "An application carries only application and registration numbers").toEqual(["application", "registration"]);
  expect(await deadSelects(page, main)).toEqual([]);
  return kind;
}

test("B4-ADJ-12 a registry identity outside the docket or of the wrong kind is refused at its field and nothing is written", async ({
  page, request, baseURL,
}, info) => {
  test.setTimeout(240_000);
  page.setDefaultTimeout(30_000);
  const rt = await prepareTester(page, request, baseURL);
  try {
    const target = await registryTarget(rt, request);
    await registryRefusals(rt, request, target);
    const kind = await registryPicker(page, rt, target);
    await expectOnScreen(kind, "The identifier type is on screen beside its record");
    await markPositive(info, "b4-adj-12-registry-contract", { local: rt.local, docketId: target.docketId });
  } finally {
    await rt.release();
  }
});

test("B4-ADJ-12 [mobile] the registry identity picker offers only valid kinds at 393px and the server refuses the rest", async ({
  page, request, baseURL,
}, info) => {
  test.setTimeout(240_000);
  page.setDefaultTimeout(30_000);
  const rt = await prepareTester(page, request, baseURL, page.viewportSize() ?? MOBILE);
  try {
    const target = await registryTarget(rt, request);
    await registryRefusals(rt, request, target);
    const kind = await registryPicker(page, rt, target);
    await kind.scrollIntoViewIfNeeded();
    await expectOnScreen(kind, "The identifier type fits a phone");
    await expectNoPageOverflow(page);
    await markPositive(info, "b4-adj-12-registry-contract-mobile", { local: rt.local, docketId: target.docketId });
  } finally {
    await rt.release();
  }
});

// ---------------------------------------------------------------- B4-ADJ-01

async function createMatter(rt: TesterRuntime, request: APIRequestContext, label: string): Promise<Matter> {
  const matterCode = code(label);
  return json<Matter>(await request.post(`${rt.api.origin}/api/matters/`, {
    headers: rt.headers,
    data: { title: `${stamp(label)} portal access check`, matter_code: matterCode, practice_area: "Commercial",
      forum_level: "high_court", status: "intake" },
  }), "Matter prerequisite");
}

async function wall(rt: TesterRuntime, request: APIRequestContext, matterId: string, membershipId: string): Promise<string> {
  const created = await json<{ id: string }>(await request.post(`${rt.api.origin}/api/matters/${matterId}/access/walls`, {
    headers: rt.headers, data: { excluded_membership_id: membershipId, reason: "Conflict with the client (acceptance check)." },
  }), "Ethical wall");
  return created.id;
}

async function cleanUpMatters(rt: TesterRuntime, request: APIRequestContext, walls: Array<[string, string]>, matters: Matter[]) {
  for (const [matterId, wallId] of walls) {
    const removed = await request.delete(`${rt.api.origin}/api/matters/${matterId}/access/walls/${wallId}`, { headers: rt.headers });
    expect(removed.status(), "Acceptance wall removed").toBe(204);
  }
  for (const matter of matters) {
    const current = await json<Matter>(await request.get(`${rt.api.origin}/api/matters/${matter.id}`, { headers: rt.headers }), "Matter read");
    await json(await request.patch(`${rt.api.origin}/api/matters/${matter.id}/lifecycle/status`, { headers: rt.headers,
      data: { to_status: "disposed", expected_from_status: current.status, expected_updated_at: current.updated_at,
        reason: "B4-ADJ-01 acceptance cleanup" } }), "Matter disposal");
  }
}

async function portalWallJourney(page: Page, request: APIRequestContext, rt: TesterRuntime, mobile: boolean) {
  expect(rt.local, "Needs a second admin and an ethical wall; Ram is alone on test-legal").toBe(true);
  const admin = await colleague(rt, "admin", "Walled Admin");
  const hidden = await createMatter(rt, request, "ADJ01-HIDDEN");
  const chosen = await createMatter(rt, request, "ADJ01-CHOSEN");
  const walls: Array<[string, string]> = [[hidden.id, await wall(rt, request, hidden.id, admin.membershipId)]];
  try {
    await switchUser(page, rt, admin.credentials);
    await page.goto(`${rt.web.origin}/app/admin`);
    const select = page.getByLabel("Matter grant", { exact: true });
    const search = page.getByLabel("Search Matters to grant");
    await page.getByTestId("portal-invite-name").fill("Acceptance Client");
    await page.getByTestId("portal-invite-email").fill(`adj01-${rt.run.replace(/\W+/g, "").slice(-10)}@example.com`);

    // The picker never offers the walled Matter.
    const hiddenSearch = page.waitForResponse((row) => new URL(row.url()).searchParams.get("q") === hidden.matter_code);
    await search.fill(hidden.matter_code);
    const hiddenRows = await (await hiddenSearch).json();
    expect(hiddenRows.matters.map((row: Matter) => row.id)).not.toContain(hidden.id);
    await expect(select.locator(`option[value="${hidden.id}"]`)).toHaveCount(0);

    // The API refuses it too, exactly like a Matter that does not exist.
    const direct = await admin.api.post(`${rt.api.origin}/api/admin/portal/invitations`, {
      data: { email: "walled-direct@example.com", full_name: "Direct Client", role: "client", matter_ids: [hidden.id] },
    });
    expect(direct.status()).toBe(404);
    expect((await direct.json()).detail).toBe("Matter not found.");

    // A Matter walled after it was chosen is refused at the Matter field.
    const chosenSearch = page.waitForResponse((row) => new URL(row.url()).searchParams.get("q") === chosen.matter_code);
    await search.fill(chosen.matter_code);
    expect((await chosenSearch).status()).toBe(200);
    await select.selectOption(chosen.id);
    walls.push([chosen.id, await wall(rt, request, chosen.id, admin.membershipId)]);
    const submit = page.getByTestId("portal-invite-submit");
    await expect(submit).toBeEnabled();
    const invited = responseTo(page, /\/api\/admin\/portal\/invitations$/, "POST");
    if (mobile) await submit.tap(); else await submit.click();
    expect((await invited).status(), "The walled Matter is refused").toBe(404);
    await expect(select).toHaveAttribute("aria-invalid", "true");
    await expect(select).toHaveAccessibleDescription(/This Matter is no longer available to you/);
    const error = page.getByText(/This Matter is no longer available to you/).first();
    await error.scrollIntoViewIfNeeded();
    await expectOnScreen(error, "The refusal sits under the Matter field");
    if (mobile) await expectNoPageOverflow(page);

    // Positive control: the owner, who is never walled, can invite to the same Matter.
    const owner = await request.post(`${rt.api.origin}/api/admin/portal/invitations`, {
      headers: rt.headers,
      data: { email: `adj01-owner-${rt.run.replace(/\W+/g, "").slice(-10)}@example.com`, full_name: "Owner Client",
        role: "client", matter_ids: [chosen.id] },
    });
    expect(owner.status()).toBe(201);
    await markPositive(test.info(), mobile ? "b4-adj-01-portal-wall-mobile" : "b4-adj-01-portal-wall", { hidden: hidden.id, chosen: chosen.id });
  } finally {
    await admin.api.dispose();
    await cleanUpMatters(rt, request, walls, [hidden, chosen]);
  }
}

test("B4-ADJ-01 [local-only] a walled admin cannot grant portal access to a Matter they cannot see", async ({
  page, request, baseURL,
}) => {
  test.setTimeout(300_000);
  page.setDefaultTimeout(30_000);
  const rt = await prepareTester(page, request, baseURL);
  try {
    await portalWallJourney(page, request, rt, false);
  } finally {
    await rt.release();
  }
});

test("B4-ADJ-01 [mobile] [local-only] the walled-Matter refusal is anchored to the Matter field at 393px", async ({
  page, request, baseURL,
}) => {
  test.setTimeout(300_000);
  page.setDefaultTimeout(30_000);
  const rt = await prepareTester(page, request, baseURL, page.viewportSize() ?? MOBILE);
  try {
    await portalWallJourney(page, request, rt, true);
  } finally {
    await rt.release();
  }
});

// ---------------------------------------------------------------- B4-ADJ-08

async function localDocket(rt: TesterRuntime, request: APIRequestContext): Promise<string> {
  const mark = stamp("B4-ADJ08 MARK");
  const created = await json(await request.post(`${rt.api.origin}/api/ip/trademark-applications/manual`, {
    headers: rt.headers,
    data: {
      title: mark, restricted: false, asset_title: mark, jurisdiction: "IN", office: "Trade Marks Registry Delhi", filing_phase: "draft",
      source_pending_identifier_allocation: false,
      application_number: { raw_value: `${Date.now()}`.slice(-9), source: "local fixture", effective_from: "2026-10-01", is_primary: true },
      particulars: {
        form_key: "TM-A", form_version: "2026.1", mark_kind: "word",
        representation: { text: mark, evidence_reference: "fixture:adj08" },
        classes: [{ class_number: 9, specification: "Downloadable legal software" }],
        use_priority: null, parties: [{ role: "applicant", name: "Applicant Industries Private Limited" }], agent: null,
        filing_manifest: [{ key: "representation", label: "Mark representation", required: true, evidence_reference: "fixture:adj08" }],
      },
    },
  }), "Local docket prerequisite", 201);
  return created.docket.id as string;
}

/** Ram proposes, a colleague activates: the two-person path, through the product API. */
async function activeCalendar(
  rt: TesterRuntime, request: APIRequestContext, approver: APIRequestContext, key: string, name: string,
): Promise<Calendar> {
  const proposed = await json<Calendar>(await request.post(`${rt.api.origin}/api/ip/working-calendars`, {
    headers: rt.headers,
    data: {
      key, name, jurisdiction: "IN", office: "IP India", timezone: "Asia/Kolkata", weekend_days: [5, 6], holidays: [],
      exceptional_working_days: [], source_priority: ["official_gazette"], source_reference: `https://ipindia.gov.in/${key}`,
      source_hash: "c".repeat(64), effective_from: "2026-01-01",
    },
  }), "Calendar proposal", 201);
  return json<Calendar>(await approver.post(`${rt.api.origin}/api/ip/working-calendars/${proposed.id}/activate`, {
    data: { reason: "Checked against the gazetted holiday list.", conflict_reviewed: true },
  }), "Independent calendar activation");
}

async function fillRule(form: Locator, seed: string) {
  await form.getByLabel("Period (months)").fill("4");
  await form.getByLabel("Rule citation").fill("Trade Marks Act 1999, s.21(1) (firm-authored test rule)");
  await form.getByLabel("Effective from").fill("2026-01-01");
  await form.getByLabel("Rule source reference").fill("https://ipindia.gov.in/trade-marks-act-1999");
  await form.getByTestId("rule-source-hash-file").setInputFiles({
    name: "official-source.pdf", mimeType: "application/pdf", buffer: Buffer.from(`Trade Marks Act 1999 s.21 ${seed}`),
  });
  await expect(form.locator("#rule-source-hash-result")).toContainText("computed in this browser; the file was not uploaded.");
  await form.getByLabel("Fixture trigger date").fill("2026-01-13");
  await form.getByLabel("Expected fixture deadline").fill("2026-05-13");
}

async function openRuleForm(page: Page, rt: TesterRuntime, docketId: string): Promise<Locator> {
  const loaded = page.waitForResponse((row) => row.url().endsWith(`/api/ip/dockets/${docketId}/deadline-workspace`));
  await page.goto(`${rt.web.origin}/app/ip?docket=${docketId}&view=schedule&rule_scope=opponent_notice`);
  expect((await loaded).status()).toBe(200);
  const form = page.getByTestId("ip-deadline-governance").getByTestId("ip-rule-proposal");
  await expect(form.getByLabel("Applies to")).toHaveValue("opponent_notice");
  return form;
}

test("B4-ADJ-08 [local-only] the rule form picks no calendar for you and the server refuses a calendar that is no longer active", async ({
  page, request, baseURL,
}, info) => {
  test.setTimeout(420_000);
  page.setDefaultTimeout(30_000);
  const rt = await prepareTester(page, request, baseURL);
  expect(rt.local, "Calendar activation needs a second approver; Ram is alone on test-legal").toBe(true);
  const approver = await colleague(rt, "admin", "Calendar Approver");
  const docketId = await localDocket(rt, request);
  const delhi = await activeCalendar(rt, request, approver.api, "b4-adj08-delhi", stamp("Delhi registry calendar"));
  const mumbai = await activeCalendar(rt, request, approver.api, "b4-adj08-mumbai", stamp("Mumbai registry calendar"));
  try {
    let form = await openRuleForm(page, rt, docketId);
    const calendar = form.getByLabel("Fixture working calendar");
    await expect(calendar, "With two active calendars nothing is preselected").toHaveValue("");
    await expect(calendar.locator("option[value='']")).toHaveText("Choose a working calendar");
    await fillRule(form, rt.run);
    const sent: string[] = [];
    page.on("request", (row) => { if (/\/api\/ip\/deadline-rules$/.test(new URL(row.url()).pathname)) sent.push(row.method()); });
    await form.getByRole("button", { name: "Propose rule and fixture" }).click();
    await expect(calendar).toHaveAttribute("aria-invalid", "true");
    await expect(calendar).toHaveAccessibleDescription(/Choose the active working calendar the fixture is calculated on/);
    expect(sent, "No proposal is sent without a calendar").toEqual([]);

    // Ram chooses Mumbai; another approver supersedes it before he submits.
    await calendar.selectOption(mumbai.id);
    await expect(calendar).not.toHaveAttribute("aria-invalid", "true");
    const superseding = await activeCalendar(rt, request, approver.api, "b4-adj08-mumbai", stamp("Mumbai registry calendar v2"));
    expect(superseding.version).toBe(2);
    const refused = responseTo(page, /\/api\/ip\/deadline-rules$/, "POST");
    await form.getByRole("button", { name: "Propose rule and fixture" }).click();
    const refusal = await refused;
    expect(refusal.status(), "The server refuses a fixture on a superseded calendar").toBe(422);
    expect((await refusal.json()).errors[0].type).toBe("ip_rule_fixture_calendar_not_active");
    await expect(calendar).toHaveAttribute("aria-invalid", "true");
    await expect(calendar).toHaveAccessibleDescription(/Choose an active working calendar of this workspace/);
    await expectOnScreen(calendar, "The refusal is anchored to the calendar field");

    // After a reload the picker lists exactly the active calendars, and the proposal succeeds.
    form = await openRuleForm(page, rt, docketId);
    const reloaded = form.getByLabel("Fixture working calendar");
    const offered = await reloaded.locator("option").evaluateAll((rows) => rows.map((row) => (row as HTMLOptionElement).value).filter(Boolean));
    expect(offered.sort()).toEqual([delhi.id, superseding.id].sort());
    await reloaded.selectOption(superseding.id);
    await fillRule(form, `${rt.run}-again`);
    const proposed = responseTo(page, /\/api\/ip\/deadline-rules$/, "POST");
    await form.getByRole("button", { name: "Propose rule and fixture" }).click();
    const created = await proposed;
    expect(created.status()).toBe(201);
    const rule = await created.json();
    expect(rule.fixtures[0].calculation.calendar.calendar_version_id).toBe(superseding.id);

    // A later supersession is named on the rule itself as a reason it cannot activate.
    const third = await activeCalendar(rt, request, approver.api, "b4-adj08-mumbai", stamp("Mumbai registry calendar v3"));
    expect(third.version).toBe(3);
    await openRuleForm(page, rt, docketId);
    const blocked = page.getByTestId(`ip-rule-activation-blocked-${rule.id}`);
    await expect(blocked).toContainText("Its fixtures were calculated on a working calendar that is no longer active.");
    const workspace = await json(await approver.api.get(`${rt.api.origin}/api/ip/dockets/${docketId}/deadline-workspace`),
      "Deadline workspace oracle");
    const record = (workspace.rules as Array<{ id: string; can_activate: boolean; activation_blocked_reasons: string[] }>)
      .find((row) => row.id === rule.id);
    expect(record?.can_activate).toBe(false);
    expect(record?.activation_blocked_reasons).toContain("fixture_calendar_not_active");

    // A made-up calendar is refused by the API exactly as the stale one was.
    const forged = await request.post(`${rt.api.origin}/api/ip/deadline-rules`, {
      headers: rt.headers,
      data: { key: "in-tm-opponent-notice", rule_kind: "deadline", jurisdiction: "IN", office: rule.office,
        right_kind: "trademark", proceeding_kind: rule.proceeding_kind, role: rule.role, stage: rule.stage,
        source_record_id: rule.source_record_id, source_hash: rule.source_hash, source_reference: rule.source_reference,
        effective_from: rule.effective_from, engine_compatibility: rule.engine_compatibility, definition: rule.definition,
        fixtures: [{ ...rule.fixtures[0], calculation: { ...rule.fixtures[0].calculation,
          calendar: { ...rule.fixtures[0].calculation.calendar, calendar_version_id: "made-up-calendar" } } }] },
    });
    expect(forged.status()).toBe(422);
    expect((await forged.json()).errors[0].type).toBe("ip_rule_fixture_calendar_not_active");
    await markPositive(info, "b4-adj-08-rule-calendar", { rule_version_id: rule.id });
  } finally {
    await approver.api.dispose();
    await rt.release();
  }
});

test("B4-ADJ-08 [mobile] [local-only] choosing the fixture calendar is required and readable at 393px", async ({
  page, request, baseURL,
}, info) => {
  test.setTimeout(420_000);
  page.setDefaultTimeout(30_000);
  const rt = await prepareTester(page, request, baseURL, page.viewportSize() ?? MOBILE);
  expect(rt.local, "Calendar activation needs a second approver; Ram is alone on test-legal").toBe(true);
  const approver = await colleague(rt, "admin", "Calendar Approver");
  const docketId = await localDocket(rt, request);
  const delhi = await activeCalendar(rt, request, approver.api, "b4-adj08-delhi", stamp("Delhi registry calendar"));
  await activeCalendar(rt, request, approver.api, "b4-adj08-mumbai", stamp("Mumbai registry calendar"));
  try {
    const form = await openRuleForm(page, rt, docketId);
    const calendar = form.getByLabel("Fixture working calendar");
    await expect(calendar).toHaveValue("");
    await fillRule(form, rt.run);
    const submit = form.getByRole("button", { name: "Propose rule and fixture" });
    await submit.scrollIntoViewIfNeeded();
    await submit.tap();
    await expect(calendar).toHaveAttribute("aria-invalid", "true");
    const error = form.locator("#rule-fixture-calendar-error");
    await error.scrollIntoViewIfNeeded();
    await expectOnScreen(error, "The calendar error is readable on a phone");
    await expectNoPageOverflow(page);
    await calendar.selectOption(delhi.id);
    const proposed = responseTo(page, /\/api\/ip\/deadline-rules$/, "POST");
    await submit.tap();
    const created = await proposed;
    expect(created.status()).toBe(201);
    expect((await created.json()).fixtures[0].calculation.calendar.calendar_version_id).toBe(delhi.id);
    await expectNoPageOverflow(page);
    await markPositive(info, "b4-adj-08-rule-calendar-mobile", { docketId });
  } finally {
    await approver.api.dispose();
    await rt.release();
  }
});
