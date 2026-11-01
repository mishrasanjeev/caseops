/**
 * Adjacent defects found while fixing Ram's batch 4 (CaseOps_Bugs (4).xlsx):
 *
 * B4-ADJ-01  A walled admin with portal:invite could grant portal access to a
 *            Matter or IP docket they cannot see: the picker was wall-scoped,
 *            the API was not, and the IP grant list showed walled dockets.
 * B4-ADJ-08  A rule that needs an active working calendar was enforced only in
 *            the browser, the rule form preselected the first calendar, and
 *            rule and calendar jurisdictions were never compared.
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
type Calendar = {
  id: string; key: string; status: string; name: string; version: number; jurisdiction: string; timezone: string;
  weekend_days: number[]; holidays: string[]; exceptional_working_days: string[]; source_reference: string; source_hash: string;
};

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

// ------------------------------------------------- B4-ADJ-01 (IP client portal)

type IpGrant = { id: string; ip_docket_record_id: string; docket_title: string; portal_user_email: string; row_version: number; active: boolean };

/** IP records carry their own walls: preview, then apply, as Ram (owner). */
async function ipAccessChange(rt: TesterRuntime, request: APIRequestContext, docketId: string, change: Record<string, unknown>) {
  const panel = await json<{ access_policy_version: number }>(await request.get(
    `${rt.api.origin}/api/ip/dockets/${docketId}/access`, { headers: rt.headers }), "IP access panel");
  const body = { ...change, expected_access_policy_version: panel.access_policy_version, reason: "Conflict with the client (acceptance check)." };
  const preview = await json<{ preview_token: string }>(await request.post(
    `${rt.api.origin}/api/ip/dockets/${docketId}/access/preview`, { headers: rt.headers, data: body }), "IP access preview");
  return json<{ panel: { walls: Array<{ id: string; subject_id: string; revoked_at: string | null }> } }>(await request.post(
    `${rt.api.origin}/api/ip/dockets/${docketId}/access/apply`, { headers: rt.headers, data: { ...body, preview_token: preview.preview_token } }),
  "IP access change");
}

async function ownerIpGrants(rt: TesterRuntime, request: APIRequestContext, docketId: string): Promise<IpGrant[]> {
  const listed = await json<{ grants: IpGrant[] }>(await request.get(`${rt.api.origin}/api/admin/portal/ip-grants`, { headers: rt.headers }),
    "Owner grant oracle");
  return listed.grants.filter((row) => row.ip_docket_record_id === docketId);
}

function ipInvitation(email: string, fullName: string, docketId: string) {
  return { email, full_name: fullName, role: "client", ip_docket_ids: [docketId], event_kinds: ["registry_snapshot_accepted"],
    deadline_kinds: ["opposition_evidence"], document_categories: ["evidence"], can_submit_instructions: true };
}

async function ipPortalWallJourney(page: Page, request: APIRequestContext, rt: TesterRuntime, mobile: boolean) {
  expect(rt.local, "Needs a second admin and an IP wall; Ram is alone on test-legal").toBe(true);
  const admin = await colleague(rt, "admin", "Walled IP Admin");
  const docket = await localTrademark(rt, request, "ADJ01 IP WALLED");
  const tag = rt.run.replace(/\W+/g, "").slice(-10).toLowerCase();
  const ownerClient = `Owner IP Client ${tag}`;
  let walled = false;
  try {
    // Ram's own grant on the docket, which the walled admin must stop seeing.
    const ownerGrant = await json<{ grants: Array<{ id: string }> }>(await request.post(`${rt.api.origin}/api/admin/portal/invitations`, {
      headers: rt.headers, data: ipInvitation(`adj01-ip-owner-${tag}@example.com`, ownerClient, docket.id),
    }), "Owner IP grant", 201);
    const ownerGrantId = ownerGrant.grants[0].id;

    await switchUser(page, rt, admin.credentials);
    const firstList = responseTo(page, /\/api\/admin\/portal\/ip-grants$/, "GET");
    await page.goto(`${rt.web.origin}/app/ip/client-portal`);
    const firstResponse = await firstList;
    expect(firstResponse.status()).toBe(200);
    const before = await firstResponse.json() as { grants: IpGrant[] };
    expect(before.grants.map((row) => row.id), "Before the wall the admin manages Ram's grant").toContain(ownerGrantId);
    // Ram's grant is in the grant list and in the publication grant choice.
    const grantRow = page.getByRole("textbox", { name: `Revocation reason for ${ownerClient}`, exact: true });
    const grantOption = page.getByRole("combobox", { name: "Client grant" }).locator(`option[value="${ownerGrantId}"]`);
    await expect(grantRow).toHaveCount(1);
    await expect(grantOption).toHaveCount(1);

    await page.getByLabel("Client name").fill("Walled IP Client");
    await page.getByLabel("Work email").fill(`adj01-ip-walled-${tag}@example.com`);
    const searched = page.waitForResponse((row) => new URL(row.url()).pathname === "/api/ip/dockets"
      && new URL(row.url()).searchParams.get("query") === docket.title);
    await page.getByLabel("Find the client's docket").fill(docket.title);
    expect((await searched).status()).toBe(200);
    const select = page.getByRole("combobox", { name: "IP docket" });
    await expect(select.locator(`option[value="${docket.id}"]`)).toHaveCount(1);
    await select.selectOption(docket.id);
    await expect(page.getByRole("checkbox", { name: "Evidence" })).toBeChecked();

    // Ram walls the admin off the docket after it was chosen.
    const wall = await ipAccessChange(rt, request, docket.id, { action: "add_wall", subject_type: "membership", subject_id: admin.membershipId });
    walled = true;
    expect(wall.panel.walls.some((row) => row.subject_id === admin.membershipId && !row.revoked_at)).toBe(true);
    const grantsBefore = (await ownerIpGrants(rt, request, docket.id)).map((row) => row.id);

    const submit = page.getByRole("button", { name: "Grant access" });
    await expect(submit).toBeEnabled();
    const invited = responseTo(page, /\/api\/admin\/portal\/invitations$/, "POST");
    if (mobile) await submit.tap(); else await submit.click();
    const refusal = await invited;
    expect(refusal.status(), "The walled docket is refused like a missing one").toBe(404);
    expect((await refusal.json()).detail).toBe("IP record not found.");
    await expect(select).toHaveAttribute("aria-invalid", "true");
    await expect(select).toHaveAccessibleDescription(/This docket is no longer available to you/);
    const error = page.locator("#ip-client-docket-error");
    await error.scrollIntoViewIfNeeded();
    await expectOnScreen(error, "The refusal sits under the docket field");
    if (mobile) await expectNoPageOverflow(page);
    expect((await ownerIpGrants(rt, request, docket.id)).map((row) => row.id), "Nothing was written").toEqual(grantsBefore);

    // After a refresh the walled admin no longer sees Ram's grant or the docket title.
    const secondList = responseTo(page, /\/api\/admin\/portal\/ip-grants$/, "GET");
    await page.getByRole("button", { name: "Refresh" }).click();
    const secondResponse = await secondList;
    expect(secondResponse.status()).toBe(200);
    const after = await secondResponse.json() as { grants: IpGrant[] };
    expect(after.grants.map((row) => row.id)).not.toContain(ownerGrantId);
    expect(JSON.stringify(after)).not.toContain(docket.title);
    await expect(grantRow).toHaveCount(0);
    await expect(grantOption).toHaveCount(0);
    await expect(page.getByText(`${ownerClient} · ${docket.title}`)).toHaveCount(0);
    const revoke = await admin.api.post(`${rt.api.origin}/api/admin/portal/ip-grants/${ownerGrantId}/revoke`, {
      data: { expected_row_version: 1, reason: "Walled admin must not reach this grant." },
    });
    expect(revoke.status()).toBe(404);
    expect((await revoke.json()).detail).toBe("Portal grant not found.");

    // Positive control: Ram, who is not walled, can still grant the same docket.
    const owner = await request.post(`${rt.api.origin}/api/admin/portal/invitations`, {
      headers: rt.headers, data: ipInvitation(`adj01-ip-owner2-${tag}@example.com`, "Second Owner IP Client", docket.id),
    });
    expect(owner.status()).toBe(201);
    await markPositive(test.info(), mobile ? "b4-adj-01-ip-portal-wall-mobile" : "b4-adj-01-ip-portal-wall", { docket: docket.id });
  } finally {
    await admin.api.dispose();
    for (const grant of (await ownerIpGrants(rt, request, docket.id)).filter((row) => row.active)) {
      const revoked = await request.post(`${rt.api.origin}/api/admin/portal/ip-grants/${grant.id}/revoke`, {
        headers: rt.headers, data: { expected_row_version: grant.row_version, reason: "B4-ADJ-01 acceptance cleanup" },
      });
      expect(revoked.status(), "Acceptance grant revoked").toBe(200);
    }
    if (walled) {
      const panel = await json<{ walls: Array<{ id: string; subject_id: string; revoked_at: string | null }> }>(await request.get(
        `${rt.api.origin}/api/ip/dockets/${docket.id}/access`, { headers: rt.headers }), "IP access panel");
      for (const row of panel.walls.filter((item) => item.subject_id === admin.membershipId && !item.revoked_at)) {
        await ipAccessChange(rt, request, docket.id, { action: "revoke_wall", wall_id: row.id });
      }
    }
  }
}

test("B4-ADJ-01 [local-only] a walled admin cannot grant IP portal access to a docket walled after it was chosen", async ({
  page, request, baseURL,
}) => {
  test.setTimeout(300_000);
  page.setDefaultTimeout(30_000);
  const rt = await prepareTester(page, request, baseURL);
  try {
    await ipPortalWallJourney(page, request, rt, false);
  } finally {
    await rt.release();
  }
});

test("B4-ADJ-01 [mobile] [local-only] the walled-docket refusal is anchored to the docket field at 393px", async ({
  page, request, baseURL,
}) => {
  test.setTimeout(300_000);
  page.setDefaultTimeout(30_000);
  const rt = await prepareTester(page, request, baseURL, page.viewportSize() ?? MOBILE);
  try {
    await ipPortalWallJourney(page, request, rt, true);
  } finally {
    await rt.release();
  }
});

// ---------------------------------------------------------------- B4-ADJ-08

async function localDocket(rt: TesterRuntime, request: APIRequestContext): Promise<string> {
  return (await localTrademark(rt, request, "B4-ADJ08 MARK")).id;
}

async function localTrademark(rt: TesterRuntime, request: APIRequestContext, label: string): Promise<{ id: string; title: string }> {
  const mark = stamp(label);
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
  return { id: created.docket.id as string, title: created.docket.title as string };
}

/** Ram proposes, a colleague activates: the two-person path, through the product API. */
// Working-calendar references for the B4-ADJ-08 journeys.
const DELHI_CALENDAR = "b4-adj08-delhi";
const MUMBAI_CALENDAR = "b4-adj08-mumbai";
const UK_CALENDAR = "b4-adj08-uk";

async function activeCalendar(
  rt: TesterRuntime, request: APIRequestContext, approver: APIRequestContext, key: string, name: string,
  jurisdiction = "IN",
): Promise<Calendar> {
  const proposed = await json<Calendar>(await request.post(`${rt.api.origin}/api/ip/working-calendars`, {
    headers: rt.headers,
    data: {
      key, name, jurisdiction, office: jurisdiction === "IN" ? "IP India" : "UK IPO",
      timezone: jurisdiction === "IN" ? "Asia/Kolkata" : "Europe/London", weekend_days: [5, 6], holidays: [],
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
  const delhi = await activeCalendar(rt, request, approver.api, DELHI_CALENDAR, stamp("Delhi registry calendar"));
  const mumbai = await activeCalendar(rt, request, approver.api, MUMBAI_CALENDAR, stamp("Mumbai registry calendar"));
  const uk = await activeCalendar(rt, request, approver.api, UK_CALENDAR, stamp("UK IPO calendar"), "GB");
  const offeredCalendars = (select: Locator) => select.locator("option").evaluateAll(
    (rows) => rows.map((row) => (row as HTMLOptionElement).value).filter(Boolean).sort());
  try {
    const form = await openRuleForm(page, rt, docketId);
    const calendar = form.getByLabel("Fixture working calendar");
    await expect(calendar, "With two active IN calendars nothing is preselected").toHaveValue("");
    await expect(calendar.locator("option[value='']")).toHaveText("Choose a working calendar");
    // The active GB calendar is never offered for an IN rule: the API would refuse it.
    expect(await offeredCalendars(calendar)).toEqual([delhi.id, mumbai.id].sort());
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
    const superseding = await activeCalendar(rt, request, approver.api, MUMBAI_CALENDAR, stamp("Mumbai registry calendar v2"));
    expect(superseding.version).toBe(2);
    const refused = responseTo(page, /\/api\/ip\/deadline-rules$/, "POST");
    await form.getByRole("button", { name: "Propose rule and fixture" }).click();
    const refusal = await refused;
    expect(refusal.status(), "The server refuses a fixture on a superseded calendar").toBe(422);
    expect((await refusal.json()).errors[0].type).toBe("ip_rule_fixture_calendar_not_active");
    await expect(calendar).toHaveAttribute("aria-invalid", "true");
    await expect(calendar).toHaveAccessibleDescription(/it was replaced, withdrawn or never activated/);
    await expectOnScreen(calendar, "The refusal is anchored to the calendar field");

    // Without a page reload the picker now lists exactly the active IN calendars:
    // the superseded version is gone and no stale choice is kept.
    await expect.poll(() => offeredCalendars(calendar), { message: "The refused form reloads its calendars" })
      .toEqual([delhi.id, superseding.id].sort());
    await expect(calendar).toHaveValue("");
    await calendar.selectOption(superseding.id);
    await expect(calendar).not.toHaveAttribute("aria-invalid", "true");
    const proposed = responseTo(page, /\/api\/ip\/deadline-rules$/, "POST");
    await form.getByRole("button", { name: "Propose rule and fixture" }).click();
    const created = await proposed;
    expect(created.status()).toBe(201);
    const rule = await created.json();
    expect(rule.fixtures[0].calculation.calendar.calendar_version_id).toBe(superseding.id);

    // A later supersession is named on the rule itself as a reason it cannot activate.
    const third = await activeCalendar(rt, request, approver.api, MUMBAI_CALENDAR, stamp("Mumbai registry calendar v3"));
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

    // An active calendar of another jurisdiction, embedded exactly as stored, is refused at the same field.
    const foreign = await request.post(`${rt.api.origin}/api/ip/deadline-rules`, {
      headers: rt.headers,
      data: { key: "in-tm-opponent-notice", rule_kind: "deadline", jurisdiction: "IN", office: rule.office,
        right_kind: "trademark", proceeding_kind: rule.proceeding_kind, role: rule.role, stage: rule.stage,
        source_record_id: rule.source_record_id, source_hash: rule.source_hash, source_reference: rule.source_reference,
        effective_from: rule.effective_from, engine_compatibility: rule.engine_compatibility, definition: rule.definition,
        fixtures: [{ ...rule.fixtures[0], calculation: { ...rule.fixtures[0].calculation, calendar: {
          calendar_version_id: uk.id, timezone: uk.timezone, weekend_days: uk.weekend_days, holidays: uk.holidays,
          exceptional_working_days: uk.exceptional_working_days, source_reference: uk.source_reference, source_hash: uk.source_hash,
        } } }] },
    });
    expect(foreign.status()).toBe(422);
    const foreignError = (await foreign.json()).errors[0];
    expect(foreignError.type).toBe("ip_rule_fixture_calendar_jurisdiction_mismatch");
    expect(foreignError.loc).toEqual(["body", "fixtures", 0, "calculation", "calendar", "calendar_version_id"]);
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
  const delhi = await activeCalendar(rt, request, approver.api, DELHI_CALENDAR, stamp("Delhi registry calendar"));
  const mumbai = await activeCalendar(rt, request, approver.api, MUMBAI_CALENDAR, stamp("Mumbai registry calendar"));
  await activeCalendar(rt, request, approver.api, UK_CALENDAR, stamp("UK IPO calendar"), "GB");
  try {
    const form = await openRuleForm(page, rt, docketId);
    const calendar = form.getByLabel("Fixture working calendar");
    await expect(calendar).toHaveValue("");
    const offered = await calendar.locator("option").evaluateAll((rows) => rows.map((row) => (row as HTMLOptionElement).value).filter(Boolean));
    expect(offered.sort(), "Only the IN calendars are offered for an IN rule").toEqual([delhi.id, mumbai.id].sort());
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
