/**
 * Ram 2026-10-31 (CaseOps_Bugs (4).xlsx) BUG-003, BUG-004, BUG-005, BUG-006:
 * governed deadline rules and working calendars.
 *
 * BUG-003/004: the opposition "Governed rule" and "Working calendar" pickers
 * were enabled selects with no options. They must list exactly the rules the
 * deadline validator accepts, or be disabled and say what is missing and how
 * to get it. BUG-005/006: the governance card offered silently disabled or
 * always-failing propose/activate controls. Every control must now follow the
 * server projection, and the full propose -> independent approval -> select ->
 * use -> emergency-disable path must work through the UI.
 *
 * Local runs use a fresh tenant entitled like test-legal; the three-user
 * journey adds two colleagues (local only). Production runs sign in as Ram on
 * test-legal: the opposition picker check is read-only, and each governance
 * check proposes one clock-stamped calendar, asserts the honest
 * pending-approval state, then withdraws it through the UI (the proposer's
 * own audited withdrawal), so no candidate is left behind.
 */
import {
  expect, request as playwrightRequest, test, type APIRequestContext, type Browser, type Locator, type Page, type Response,
} from "@playwright/test";

import {
  addLocalColleague, deadSelects, expectNoPageOverflow, expectOnScreen, json, markPositive, prepareTester,
  signIn, stamp, type TesterCredentials, type TesterRuntime,
} from "./support/ram-bugs4";

test.use({ trace: "off", screenshot: "off", video: "off", storageState: { cookies: [], origins: [] } });
test.describe.configure({ mode: "default", retries: 0 });

// The reported production records (Ram, test-legal), selected by server identity.
const PROD_DOCKET = "2cc78d06-8fc5-535b-b21f-75da52914233";
const PROD_OPPONENT_PROCEEDING = "eecba83d-2f83-456b-9c41-ddc3102f6c05";
const MOBILE = { width: 393, height: 851 };

type Opposition = { docketId: string; proceedingId: string };

function slug(label: string): string {
  return stamp(label).toLowerCase().replace(/[^a-z0-9]+/g, "-");
}

/**
 * Local prerequisite only: a trademark docket linked to an operational Matter,
 * with a confirmed opponent opposition profile. None of these is what these
 * bugs are about (the pickers, governance and deadline confirmation are), and
 * their own UI journeys are covered by the matter and IPLF-042 specs.
 */
async function localOpposition(rt: TesterRuntime, request: APIRequestContext): Promise<Opposition> {
  const mark = stamp("BUG-003 TARGET MARK");
  const matter = await json(await request.post(`${rt.api.origin}/api/matters`, {
    headers: rt.headers,
    data: { matter_code: slug("B4-OPP"), title: `${mark} opposition`, practice_area: "Intellectual Property", forum_level: "high_court" },
  }), "Local matter prerequisite");
  const created = await json(await request.post(`${rt.api.origin}/api/ip/trademark-applications/manual`, {
    headers: rt.headers,
    data: {
      title: mark, matter_id: matter.id, restricted: false, asset_title: mark, jurisdiction: "IN", office: "Trade Marks Registry Delhi",
      filing_phase: "draft", source_pending_identifier_allocation: false,
      application_number: { raw_value: slug("TM-APP-B4"), source: "local fixture", effective_from: "2026-08-23", is_primary: true },
      particulars: {
        form_key: "TM-A", form_version: "2026.1", mark_kind: "word",
        representation: { text: mark, evidence_reference: "fixture:mark" },
        classes: [{ class_number: 9, specification: "Downloadable legal software" }],
        use_priority: null, parties: [{ role: "applicant", name: "Applicant Industries Private Limited" }], agent: null,
        filing_manifest: [{ key: "representation", label: "Mark representation", required: true, evidence_reference: "fixture:mark" }],
      },
    },
  }), "Local docket prerequisite", 201);
  const docketId = created.docket.id as string;
  const proceeding = await json(await request.post(`${rt.api.origin}/api/ip/dockets/${docketId}/proceedings`, {
    headers: rt.headers,
    data: {
      application_id: created.application.id, proceeding_kind: "opposition", side: "opponent",
      office: "Trade Marks Registry Delhi", jurisdiction: "IN", stage: "draft", origin_kind: "manual_intake",
      source_pending_identifier_allocation: true,
    },
  }), "Local opposition prerequisite", 201);
  const docket = await json(await request.get(`${rt.api.origin}/api/ip/dockets/${docketId}`, { headers: rt.headers }), "Local docket read");
  await json(await request.put(`${rt.api.origin}/api/ip/dockets/${docketId}/proceedings/${proceeding.id}/opposition-workspace`, {
    headers: rt.headers,
    data: {
      expected_lifecycle_version: docket.lifecycle_version, expected_proceeding_version: proceeding.version,
      source: "manual", source_reference: "registry:opposition:b4", source_notice_reference: "notice:opposition:b4",
      effective_at: "2026-10-30T07:00:00Z", responsible_membership_id: rt.actor.membership.id,
      reason: "Confirmed the opponent profile from the advertised journal notice.",
      applicable_rule_version: "trade-marks-rules-2017", forum: "Trade Marks Registry Delhi",
      client_instruction_state: "confirmed", client_instruction_reference: "client-instruction:b4",
      limitation_date: "2027-02-27",
      parties: [
        { role: "applicant", party_name: "Applicant Industries Pvt Ltd", source: "opposition notice" },
        { role: "opponent", party_name: "Opponent Brands LLP", source: "opposition notice" },
      ],
      grounds: [{ category: "earlier_mark", lawyer_detail: "Earlier registered mark asserted against the application.", classification_source: "manual" }],
      challenged_scope: [{ class_number: 9, goods_services_segment: "Recorded computer software" }],
      relied_on_rights: [{
        mark_or_right: "EARLIER MARK", jurisdiction: "IN", identifier: "TM-EARLIER-B4", status: "registered",
        owner: "Opponent Brands LLP", goods_services: "Recorded computer software", reputation_claim: null,
        use_claim: "Used since 2019", evidence_refs: ["registry:earlier-right:b4"],
      }],
      service: null,
      evidence_refs: ["evidence:notice:b4"],
    },
  }), "Local opposition profile prerequisite");
  return { docketId, proceedingId: proceeding.id as string };
}

async function opposition(rt: TesterRuntime, request: APIRequestContext): Promise<Opposition> {
  return rt.local
    ? localOpposition(rt, request)
    : { docketId: PROD_DOCKET, proceedingId: PROD_OPPONENT_PROCEEDING };
}

async function workspaceOf(rt: TesterRuntime, request: APIRequestContext, docketId: string) {
  return json(await request.get(`${rt.api.origin}/api/ip/dockets/${docketId}/deadline-workspace`, { headers: rt.headers }),
    "Deadline workspace oracle");
}

async function openOpponent(page: Page, rt: TesterRuntime, target: Opposition): Promise<Locator> {
  await page.goto(`${rt.web.origin}/app/ip?docket=${target.docketId}&view=proceedings&proceeding=${target.proceedingId}`);
  const opponent = page.getByTestId("ip-opposition-opponent-workflow");
  await expect(opponent).toBeVisible({ timeout: 30_000 });
  return opponent;
}

async function openGovernance(page: Page, rt: TesterRuntime, docketId: string): Promise<Locator> {
  await page.goto(`${rt.web.origin}/app/ip?docket=${docketId}&view=schedule`);
  const card = page.getByTestId("ip-deadline-governance");
  await expect(card.getByText("Calendar versions", { exact: true })).toBeVisible({ timeout: 30_000 });
  return card;
}

function responseTo(page: Page, suffix: RegExp, method: string): Promise<Response> {
  return page.waitForResponse((row) => suffix.test(new URL(row.url()).pathname) && row.request().method() === method);
}

async function chooseSourceFile(scope: Locator, id: string, text: string) {
  await scope.getByTestId(`${id}-file`).setInputFiles({ name: "official-source.pdf", mimeType: "application/pdf", buffer: Buffer.from(text) });
  await expect(scope.locator(`#${id}-result`)).toContainText("computed in this browser; the file was not uploaded.");
}

async function proposeCalendar(page: Page, card: Locator, name: string): Promise<{ id: string; status: string }> {
  const form = card.getByTestId("ip-calendar-proposal");
  await form.getByLabel("Calendar name").fill(name);
  await form.getByLabel("Holiday dates").fill("26/01/2026, 15/08/2026");
  await form.getByLabel("Effective from").fill("2026-01-01");
  await form.getByLabel("Official source reference").fill("https://ipindia.gov.in/holiday-list-2026");
  await chooseSourceFile(form, "calendar-source-hash", `IP India holiday list 2026 ${name}`);
  const proposed = responseTo(page, /\/api\/ip\/working-calendars$/, "POST");
  await form.getByRole("button", { name: "Propose calendar version" }).click();
  const response = await proposed;
  expect(response.status(), "The calendar proposal the tester submitted must be created").toBe(201);
  return response.json();
}

/** The proposer's own withdrawal, through the UI: production runs leave no candidate behind. */
async function withdrawCalendar(page: Page, card: Locator, calendarId: string) {
  const row = card.getByTestId(`ip-calendar-version-${calendarId}`);
  await row.getByLabel("Reason to withdraw your proposal").fill("Synthetic tester proposal, withdrawn after the check.");
  const withdrawn = responseTo(page, /\/working-calendars\/[^/]+\/withdraw$/, "POST");
  await row.getByRole("button", { name: "Withdraw my proposal" }).click();
  const response = await withdrawn;
  expect(response.status(), "The proposer can withdraw its own candidate").toBe(200);
  expect(await response.json()).toMatchObject({ id: calendarId, status: "retired", can_withdraw: false, can_activate: false });
  await expect(row.getByText("withdrawn", { exact: true })).toBeVisible();
}

/**
 * addLocalColleague logs the colleague in on the context it is given, and that
 * login cookie would then authenticate later calls as the colleague. Give each
 * colleague a throwaway context so Ram's oracle calls stay Ram's.
 */
async function colleague(rt: TesterRuntime, role: "admin" | "partner", name: string) {
  const isolated = await playwrightRequest.newContext();
  try {
    return await addLocalColleague(rt, isolated, role, name);
  } finally {
    await isolated.dispose();
  }
}

async function colleaguePage(browser: Browser, rt: TesterRuntime, credentials: TesterCredentials): Promise<Page> {
  const context = await browser.newContext({ storageState: { cookies: [], origins: [] }, viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  await signIn(page, rt, credentials);
  return page;
}

test("BUG-003/004 opposition governed-rule and calendar pickers are never dead selects", async ({ page, request, baseURL }, info) => {
  test.setTimeout(240_000);
  const rt = await prepareTester(page, request, baseURL);
  const target = await opposition(rt, request);
  const oracle = await workspaceOf(rt, request, target.docketId);
  const workflow = await json(await request.get(
    `${rt.api.origin}/api/ip/dockets/${target.docketId}/proceedings/${target.proceedingId}/opponent-workflow`, { headers: rt.headers },
  ), "Opponent workflow oracle");
  expect(workflow.next_required_action, "The reported proceeding is waiting for its notice deadline").toBe("propose_notice_filing_deadline");
  const eligible = (oracle.rules as Array<Record<string, unknown>>).filter((row) =>
    (oracle.eligible_rule_version_ids as string[]).includes(row.id as string) && row.status === "active"
    && row.proceeding_kind === "opposition" && row.role === "opponent" && row.stage === "notice_filing_due");
  const calendars = (oracle.calendars as Array<Record<string, unknown>>).filter((row) => row.status === "active");

  const opponent = await openOpponent(page, rt, target);
  const rule = opponent.getByLabel("Governed rule", { exact: true });
  const calendar = opponent.getByLabel("Working calendar", { exact: true });
  await expect(rule).toBeVisible();
  expect(await deadSelects(page, opponent), "No enabled select without a real option").toEqual([]);
  // Picker == validator: exactly the server-eligible, exact-scope rules.
  const offered = await rule.locator("option").evaluateAll((rows) => rows.map((row) => (row as HTMLOptionElement).value).filter(Boolean));
  expect(offered.sort()).toEqual(eligible.map((row) => row.id as string).sort());
  const status = opponent.getByTestId("opponent-deadline-governed-pickers");
  if (eligible.length === 0) {
    await expect(rule).toBeDisabled();
    await expect(status).toContainText("No active governed rule exists for Opposition, opponent · notice of opposition due.");
  } else {
    await expect(rule).toBeEnabled();
  }
  if (calendars.length === 0) {
    await expect(calendar).toBeDisabled();
    await expect(status).toContainText("Working calendar.");
  } else {
    await expect(calendar).toBeEnabled();
  }
  await expect(opponent.getByText(/notice_filing_due/)).toHaveCount(0);
  // "Propose deadline" is never an enabled button that can only fail: every
  // refusal the proposer would raise is named on screen first.
  const propose = opponent.getByRole("button", { name: "Propose deadline" });
  const blockers = opponent.getByTestId("opponent-deadline-blockers");
  await expect(opponent.getByLabel("TM Journal advertisement date")).toHaveValue("");
  await expect(propose).toBeDisabled();
  await expect(propose).toHaveAttribute("aria-describedby", "opponent-deadline-blockers");
  await expect(blockers).toContainText("Enter the TM Journal advertisement date; the period runs from it.");
  expect(Array.isArray(workflow.deadline_proposal_gaps), "The workflow projects the proposer's readiness gaps").toBe(true);
  for (const gap of workflow.deadline_proposal_gaps as string[]) {
    await expect(blockers.locator(`[data-gap="${gap}"]`)).toBeVisible();
  }
  const link = opponent.getByRole("link", { name: "Open rule and calendar governance" });
  await expect(link).toHaveCount(eligible.length === 0 || calendars.length === 0 ? 1 : 0);
  if (eligible.length === 0 || calendars.length === 0) {
    await link.click();
    await page.waitForURL(/view=schedule/);
    const card = page.getByTestId("ip-deadline-governance");
    await expect(card.getByText("Calendar versions", { exact: true })).toBeVisible();
    await expectOnScreen(card.getByRole("heading", { name: "Rule and calendar governance" }), "The governance link lands on the card");
    expect(new URL(page.url()).searchParams.get("rule_scope")).toBe("opponent_notice");
  }
  await markPositive(info, "bug-003-004-picker-matches-validator", { offered: offered.length, calendars: calendars.length });
});

test("[mobile] BUG-003/004 opposition picker reasons and governance link fit 393px", async ({ page, request, baseURL }, info) => {
  test.setTimeout(240_000);
  const rt = await prepareTester(page, request, baseURL, MOBILE);
  const target = await opposition(rt, request);
  const oracle = await workspaceOf(rt, request, target.docketId);
  const opponent = await openOpponent(page, rt, target);
  await expect(opponent.getByLabel("Governed rule", { exact: true })).toBeVisible();
  expect(await deadSelects(page, opponent)).toEqual([]);
  const blockers = opponent.getByTestId("opponent-deadline-blockers");
  await blockers.scrollIntoViewIfNeeded();
  await expectOnScreen(blockers, "Why Propose deadline is disabled is readable on a phone");
  await expectNoPageOverflow(page);
  const hasEligible = (oracle.rules as Array<Record<string, unknown>>).some((row) =>
    (oracle.eligible_rule_version_ids as string[]).includes(row.id as string) && row.proceeding_kind === "opposition"
    && row.role === "opponent" && row.stage === "notice_filing_due");
  const hasCalendar = (oracle.calendars as Array<{ status: string }>).some((row) => row.status === "active");
  const link = opponent.getByRole("link", { name: "Open rule and calendar governance" });
  if (hasEligible && hasCalendar) {
    await expect(link).toHaveCount(0);
    await expect(opponent.getByLabel("Governed rule", { exact: true })).toBeEnabled();
  } else {
    await link.scrollIntoViewIfNeeded();
    await expectOnScreen(link, "The governance link is reachable on a phone");
    await link.click();
    const card = page.getByTestId("ip-deadline-governance");
    await expect(card.getByText("Calendar versions", { exact: true })).toBeVisible();
    await expectOnScreen(card.getByRole("heading", { name: "Rule and calendar governance" }), "The card is in view after the deep link");
    await expectNoPageOverflow(page);
  }
  await markPositive(info, "bug-003-004-mobile");
});

test("BUG-005/006 Ram proposes a calendar and sees the honest pending-approval state", async ({ page, request, baseURL }, info) => {
  test.setTimeout(240_000);
  const rt = await prepareTester(page, request, baseURL);
  const docketId = rt.local ? (await localOpposition(rt, request)).docketId : PROD_DOCKET;
  const card = await openGovernance(page, rt, docketId);
  const before = await workspaceOf(rt, request, docketId);
  expect(before.governance.calendar_proposal.available, "test-legal is entitled to calendar governance").toBe(true);
  // Rule controls follow the projection in both rollout states.
  if (before.governance.rule_proposal.available) {
    await expect(card.getByTestId("ip-rule-proposal")).toBeVisible();
  } else {
    await expect(card.getByTestId("ip-rule-proposal")).toHaveCount(0);
    await expect(card.getByTestId("ip-governance-blocked-rule-propose")).toBeVisible();
  }

  const name = stamp("BUG-005 working calendar");
  const created = await proposeCalendar(page, card, name);
  expect(created.status).toBe("candidate");
  const row = card.getByTestId(`ip-calendar-version-${created.id}`);
  await expect(row).toContainText(`${name} v1`);
  const blocked = row.getByTestId(`ip-calendar-activation-blocked-${created.id}`);
  await expect(blocked).toContainText("You proposed this version, so another owner, admin or partner must activate it.");
  await expect(row.getByRole("button", { name: "Independently activate calendar" })).toHaveCount(0);
  await expect(card.locator("#calendar-source-hash-result")).toContainText("Choose the official source");

  const after = await workspaceOf(rt, request, docketId);
  const server = (after.calendars as Array<Record<string, unknown>>).find((item) => item.id === created.id) as
    { activation_blocked_reasons: string[] } & Record<string, unknown>;
  expect(server).toMatchObject({ status: "candidate", can_activate: false, can_withdraw: true });
  expect(server.activation_blocked_reasons).toContain("proposer_cannot_self_approve");
  // Every reason the server gives is on screen (a workspace without another
  // approver is told so, with the way to add one).
  for (const reason of server.activation_blocked_reasons) {
    await expect(blocked.locator(`[data-reason="${reason}"]`)).toBeVisible();
  }
  if (after.governance.rule_proposal.available) {
    const hasActive = (after.calendars as Array<{ status: string }>).some((item) => item.status === "active");
    const submit = card.getByRole("button", { name: "Propose rule and fixture" });
    if (hasActive) await expect(submit).toBeEnabled();
    else {
      await expect(submit).toBeDisabled();
      await expect(card.locator("#rule-proposal-prerequisite")).toContainText("awaiting activation by an approver other than the proposer.");
    }
  }
  await markPositive(info, "bug-005-006-calendar-proposed", { calendar_version_id: created.id });
  await withdrawCalendar(page, card, created.id);
  const withdrawn = await workspaceOf(rt, request, docketId);
  expect((withdrawn.calendars as Array<{ id: string; status: string }>).find((item) => item.id === created.id))
    .toMatchObject({ status: "retired" });
});

test("[mobile] BUG-005 governance card controls fit 393px with a computed source hash", async ({ page, request, baseURL }, info) => {
  test.setTimeout(240_000);
  const rt = await prepareTester(page, request, baseURL, MOBILE);
  const docketId = rt.local ? (await localOpposition(rt, request)).docketId : PROD_DOCKET;
  const card = await openGovernance(page, rt, docketId);
  const form = card.getByTestId("ip-calendar-proposal");
  await form.getByRole("button", { name: "Propose calendar version" }).click();
  await expect(form.locator("#calendar-source-reference-error")).toContainText("official source reference");
  await expect(form.locator("#calendar-source-hash-error")).toContainText("Choose the official source file");
  await chooseSourceFile(form, "calendar-source-hash", "IP India holiday list 2026 mobile");
  await expect(form.locator("#calendar-source-hash-error")).toHaveCount(0);
  await expect(form.locator("#calendar-source-reference-error")).toContainText("official source reference");
  await expectNoPageOverflow(page);
  expect(await deadSelects(page, card)).toEqual([]);
  const created = await proposeCalendar(page, card, stamp("BUG-005 mobile calendar"));
  const row = card.getByTestId(`ip-calendar-version-${created.id}`);
  await row.getByRole("button", { name: "Withdraw my proposal" }).scrollIntoViewIfNeeded();
  await expectOnScreen(row.getByRole("button", { name: "Withdraw my proposal" }), "The proposer's withdraw control fits a phone");
  await expectNoPageOverflow(page);
  await withdrawCalendar(page, card, created.id);
  await expectNoPageOverflow(page);
  await markPositive(info, "bug-005-mobile-validation", { calendar_version_id: created.id });
});

test("BUG-003/004/005/006 [local-only] three people govern a rule end to end through the UI", async ({ page, request, baseURL, browser }, info) => {
  test.setTimeout(600_000);
  const rt = await prepareTester(page, request, baseURL);
  expect(rt.local, "Activation needs three people; production Ram only proposes").toBe(true);
  const target = await localOpposition(rt, request);
  const reviewer = await colleague(rt, "partner", "Bina Reviewer");
  const approver = await colleague(rt, "admin", "Chetan Approver");

  // 1. The empty opposition picker sends Ram to governance with the scope prefilled.
  const opponent = await openOpponent(page, rt, target);
  await expect(opponent.getByLabel("Governed rule", { exact: true })).toBeDisabled();
  await opponent.getByRole("link", { name: "Open rule and calendar governance" }).click();
  await page.waitForURL(/rule_scope=opponent_notice/);
  let card = page.getByTestId("ip-deadline-governance");
  await expect(card.getByText("Calendar versions", { exact: true })).toBeVisible();

  // 2. Ram proposes a calendar; he cannot activate his own proposal.
  const calendarName = stamp("BUG-004 Delhi registry calendar");
  const calendar = await proposeCalendar(page, card, calendarName);
  await expect(card.getByTestId(`ip-calendar-activation-blocked-${calendar.id}`)).toContainText("another owner, admin or partner");
  await expect(card.getByRole("button", { name: "Propose rule and fixture" })).toBeDisabled();

  // 3. Bina (partner) independently activates it.
  const bina = await colleaguePage(browser, rt, reviewer.credentials);
  const binaCard = await openGovernance(bina, rt, target.docketId);
  const binaRow = binaCard.getByTestId(`ip-calendar-version-${calendar.id}`);
  await binaRow.getByLabel("Activation reason").fill("Checked against the gazetted 2026 holiday list.");
  const calendarActivated = responseTo(bina, /\/working-calendars\/[^/]+\/activate$/, "POST");
  await binaRow.getByRole("button", { name: "Independently activate calendar" }).click();
  expect((await calendarActivated).status()).toBe(200);
  await expect(binaRow).toContainText("active");

  // 4. Ram proposes the opposition notice rule with its own source evidence.
  await page.goto(`${rt.web.origin}/app/ip?docket=${target.docketId}&view=schedule&rule_scope=opponent_notice`);
  card = page.getByTestId("ip-deadline-governance");
  const ruleForm = card.getByTestId("ip-rule-proposal");
  await expect(ruleForm.getByLabel("Applies to")).toHaveValue("opponent_notice");
  await expect(ruleForm.getByLabel("Rule key")).toHaveCount(0);
  await expect(ruleForm).toContainText("Starts from: Trade mark advertised in the TM Journal.");
  const ruleKey = slug("b4-opponent-notice");
  await ruleForm.getByLabel("Period (months)").fill("4");
  await ruleForm.getByLabel("Rule citation").fill("Trade Marks Act 1999, s.21(1) (firm-authored test rule)");
  await ruleForm.getByLabel("Effective from").fill("2026-01-01");
  await ruleForm.getByLabel("Rule source reference").fill("https://ipindia.gov.in/trade-marks-act-1999");
  await chooseSourceFile(ruleForm, "rule-source-hash", `Trade Marks Act 1999 s.21 ${ruleKey}`);
  await ruleForm.getByLabel("Fixture trigger date").fill("2026-01-13");
  await ruleForm.getByLabel("Expected fixture deadline").fill("2026-05-13");
  const ruleProposed = responseTo(page, /\/api\/ip\/deadline-rules$/, "POST");
  await ruleForm.getByRole("button", { name: "Propose rule and fixture" }).click();
  const ruleResponse = await ruleProposed;
  expect(ruleResponse.status()).toBe(201);
  const rule = await ruleResponse.json();
  expect(rule).toMatchObject({ proceeding_kind: "opposition", role: "opponent", stage: "notice_filing_due", status: "candidate",
    key: "in-tm-opponent-notice", definition: expect.objectContaining({ trigger_kind: "trademark_advertised" }) });
  await expect(card.getByTestId(`ip-rule-activation-blocked-${rule.id}`)).toContainText(
    "You proposed this version, so another owner, admin or partner must activate it.");
  await expect(card.getByTestId(`ip-rule-version-${rule.id}`).getByRole("button", { name: "Run fixtures and activate rule" })).toHaveCount(0);

  // 5. Chetan (admin) activates with Bina as the fixture reviewer: the picker offers exactly her.
  const chetan = await colleaguePage(browser, rt, approver.credentials);
  const chetanCard = await openGovernance(chetan, rt, target.docketId);
  const chetanRow = chetanCard.getByTestId(`ip-rule-version-${rule.id}`);
  const reviewerPicker = chetanRow.getByLabel("Independent fixture reviewer");
  await expect(reviewerPicker.locator(`option[value="${reviewer.membershipId}"]`)).toHaveCount(1);
  const reviewerOptions = await reviewerPicker.locator("option").evaluateAll((rows) => rows.map((row) => (row as HTMLOptionElement).value).filter(Boolean));
  expect(reviewerOptions).toEqual([reviewer.membershipId]);
  await reviewerPicker.selectOption(reviewer.membershipId);
  await chetanRow.getByLabel("Activation note").fill("Fixture checked against s.21(1); four months from advertisement.");
  // Activation is never sent on an impact nobody saw: preview first.
  const activateButton = chetanRow.getByRole("button", { name: "Run fixtures and activate rule" });
  await expect(activateButton).toBeDisabled();
  await chetanRow.getByRole("button", { name: "Preview activation impact" }).click();
  await expect(chetanRow.getByTestId(`ip-rule-activation-impact-${rule.id}`)).toContainText(
    "No company selection or open deadline uses this rule yet.");
  const ruleActivated = responseTo(chetan, /\/deadline-rules\/[^/]+\/activate$/, "POST");
  await activateButton.click();
  const activation = await ruleActivated;
  expect(activation.status()).toBe(200);
  expect(JSON.parse(activation.request().postData() ?? "{}")).toMatchObject({ reviewer_membership_id: reviewer.membershipId, supersede_overlapping: false });
  await expect(chetanRow).toContainText("Selected for company deadlines");
  await expect(chetanCard.getByTestId(`ip-rule-policy-${rule.rule_set_id}`)).toContainText("Selected: v1 (active) · policy version 1");

  // 6. The opposition picker now lists the governed rule and calendar.
  const ready = await openOpponent(page, rt, target);
  const rulePicker = ready.getByLabel("Governed rule", { exact: true });
  await expect(rulePicker).toBeEnabled();
  await expect(rulePicker).toHaveValue(rule.id);
  await expect(ready.getByLabel("Working calendar", { exact: true })).toHaveValue(calendar.id);
  expect(await deadSelects(page, ready)).toEqual([]);
  await markPositive(info, "bug-003-004-picker-lists-governed-rule", { rule_version_id: rule.id, calendar_version_id: calendar.id });

  // 7. Ram proposes and confirms the notice deadline in Opponent docketing with
  // the governed rule: the journey after the picker works end to end.
  const advertised = ready.getByLabel("TM Journal advertisement date");
  await expect(advertised).toHaveValue("");
  await advertised.fill("2026-07-01");
  const opponentProposed = responseTo(page, /\/proceedings\/[^/]+\/opponent-deadlines$/, "POST");
  await ready.getByRole("button", { name: "Propose deadline" }).click();
  const proposedResponse = await opponentProposed;
  expect(proposedResponse.status(), "The opposition deadline proposal succeeds").toBe(201);
  const proposed = (await proposedResponse.json()).deadline as { id: string; rule_version_id: string; calendar_version_id: string; base_date: string };
  expect(proposed).toMatchObject({ rule_version_id: rule.id, calendar_version_id: calendar.id, base_date: "2026-07-01" });
  const oracle = await workspaceOf(rt, request, target.docketId);
  const eligiblePeople = oracle.eligible_responsible_membership_ids as string[];
  expect(eligiblePeople).toEqual(expect.arrayContaining([rt.actor.membership.id, reviewer.membershipId, approver.membershipId]));
  const backupPicker = ready.locator(`#opponent-backup-${proposed.id}`);
  await expect(backupPicker).toBeEnabled();
  const backupOffered = await backupPicker.locator("option").evaluateAll((rows) => rows.map((row) => (row as HTMLOptionElement).value).filter(Boolean));
  expect(backupOffered.sort()).toEqual(eligiblePeople.filter((id) => id !== rt.actor.membership.id).sort());
  await backupPicker.selectOption(reviewer.membershipId);
  const confirmed = responseTo(page, /\/api\/ip\/deadlines\/[^/]+\/confirm$/, "POST");
  await ready.getByRole("button", { name: "Confirm", exact: true }).click();
  const confirmedResponse = await confirmed;
  expect(confirmedResponse.status(), "Confirmation accepts the offered people").toBe(200);
  expect(await confirmedResponse.json()).toMatchObject({ id: proposed.id, state: "confirmed" });
  await markPositive(info, "bug-003-opposition-deadline-confirmed", { deadline_id: proposed.id });

  // 8. Emergency disable flags the confirmed deadline, with a readable label.
  await page.goto(`${rt.web.origin}/app/ip?docket=${target.docketId}&view=schedule`);
  const ramRow = page.getByTestId(`ip-rule-version-${rule.id}`);
  await ramRow.getByLabel("Reason to disable or retire").fill("Firm-authored test rule withdrawn after review.");
  await ramRow.getByRole("button", { name: "Preview impact" }).click();
  await expect(ramRow.getByRole("status")).toContainText("1 open deadline(s)");
  const disabled = responseTo(page, /\/deadline-rules\/[^/]+\/transition$/, "POST");
  await ramRow.getByRole("button", { name: "Emergency-disable rule" }).click();
  expect((await disabled).status()).toBe(200);
  const exceptions = page.getByTestId("ip-deadline-exceptions");
  await expect(exceptions).toContainText("Rule disabled");
  await expect(exceptions).not.toContainText("rule_disabled");
  await expect(exceptions).not.toContainText(proposed.id);
  const afterDisable = await workspaceOf(rt, request, target.docketId);
  expect(afterDisable.eligible_rule_version_ids).not.toContain(rule.id);
  expect((afterDisable.exceptions as Array<{ deadline_id: string; exception_kinds: string[] }>)
    .find((row) => row.deadline_id === proposed.id)?.exception_kinds).toContain("rule_disabled");
  await markPositive(info, "bug-006-emergency-disable", { rule_version_id: rule.id });

  await bina.context().close();
  await chetan.context().close();
});
