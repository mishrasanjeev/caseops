/**
 * BUG-014 (Ram, 2026-10-30; IP UJ-21 journal watch, IP-WATCH-01/02): Ram's
 * journal capture with "Class 45" and captured evidence failed with a 422
 * that named no field. Signed in as the reporting tester in their own tenant,
 * this spec drives the real Journal watch UI end to end:
 *
 * - availability names manual intake and each automated-polling gate;
 * - a watch profile is created with a docket and recipients chosen by name;
 * - a bad class token and missing evidence are refused at their fields, with
 *   no request sent;
 * - "Class 45" with a goods row and the journal extract is recorded (201),
 *   listed among recorded entries, and its evidence is shown on the hit;
 * - the test's own hit and profile are retired through the product
 *   (attorney disposition, profile pause). Journal entries are append-only.
 *
 * Production retains every run's records, so everything is stamped and
 * selected by server identity. Locally the docket is created through the API:
 * it is an unrelated prerequisite (docket creation is not under test).
 */
import {
  expect, test, type APIRequestContext, type Page, type Response, type TestInfo,
} from "@playwright/test";

import {
  expectNoPageOverflow, expectOnScreen, json, deadSelects, markPositive, prepareTester, stamp,
  type TesterRuntime,
} from "./support/ram-bugs4";

test.use({ trace: "off", screenshot: "off", video: "off", storageState: { cookies: [], origins: [] } });
test.describe.configure({ mode: "default", retries: 0 });

const SOURCE_URL = "https://search.ipindia.gov.in/IPOJournal/Journal/ViewJournal";
const INTERNAL_FIELD = /\b(?:membership ids?|member ids?|uuid|sha-?256|raw (?:source )?json|json)\b/i;
const BLOCKED_CATEGORY: Record<string, string> = {
  incident_kill_switch: "Paused by CaseOps",
  rollout_disabled: "Paused by CaseOps",
  rollout_expired: "Paused by CaseOps",
  missing_entitlement: "Not in your plan",
  workspace_not_configured: "Needs setup",
  tenant_disabled: "Needs setup",
  readiness_test_failed: "Needs setup",
  missing_capability: "Your role cannot",
  unknown_feature: "Unavailable",
};

type Docket = { id: string; title: string };

/** A browser response the UI itself made; body intentionally not logged. */
async function uiJson<T = any>(response: Response, operation: string, expected = 200): Promise<T> {
  expect(response.status(), `${operation} returned ${response.status()}`).toBe(expected);
  return response.json() as Promise<T>;
}

/** The docket the stamped watch profile belongs to (not the item under test). */
async function watchDocket(rt: TesterRuntime, request: APIRequestContext): Promise<Docket> {
  if (rt.local) {
    const title = stamp("BUG014 WATCH DOCKET");
    const created = await json(await request.post(`${rt.api.origin}/api/ip/trademark-applications/manual`, {
      headers: rt.headers,
      data: {
        title, restricted: false, asset_title: title, jurisdiction: "IN", office: "IP India",
        filing_phase: "draft", source_pending_identifier_allocation: false,
        application_number: { raw_value: `TM-${Date.now()}`, source: "bugs4 watch prerequisite", effective_from: "2026-10-31", is_primary: true },
        particulars: {
          form_key: "TM-A", form_version: "2026.1", mark_kind: "word",
          representation: { text: title, evidence_reference: "bugs4:watch-docket" },
          classes: [{ class_number: 45, specification: "Legal services" }],
          use_priority: null, parties: [{ role: "applicant", name: "Test Legal LLP" }], agent: null,
          filing_manifest: [{ key: "representation", label: "Mark representation", required: true, evidence_reference: "bugs4:watch-docket" }],
        },
      },
    }), "Local watch docket prerequisite", 201);
    return { id: created.docket.id, title: created.docket.title };
  }
  const page = await json(await request.get(`${rt.api.origin}/api/ip/dockets?limit=50`, { headers: rt.headers }), "Tester dockets");
  const docket = (page.dockets as Array<Docket & { record_type: string }>).find(row => row.record_type === "trademark");
  expect(docket, "test-legal must have a visible trademark docket for a watch profile").toBeTruthy();
  return { id: docket!.id, title: docket!.title };
}

async function internalFieldLabels(page: Page): Promise<string[]> {
  return page.locator("main").evaluate((root, pattern) => {
    const re = new RegExp(pattern, "i");
    return Array.from(root.querySelectorAll<HTMLInputElement | HTMLTextAreaElement>("input, textarea"))
      .filter(field => field.type !== "hidden" && !field.disabled && field.getBoundingClientRect().width > 0)
      .map(field => field.labels?.[0]?.innerText || field.getAttribute("aria-label") || field.placeholder || "")
      .filter(label => re.test(label));
  }, INTERNAL_FIELD.source);
}

async function captureJournalEntry(
  page: Page, request: APIRequestContext, rt: TesterRuntime, info: TestInfo, mobile: boolean,
) {
  const checkLayout = async () => { if (mobile) await expectNoPageOverflow(page); };
  const docket = await watchDocket(rt, request);
  const label = stamp(mobile ? "B4W M" : "B4W D");
  const mark = `ZQXV ${label.replace(/[^A-Z0-9]+/gi, " ").trim()}`;
  const applicationNumber = `BUG014-${label.replace(/[^A-Z0-9]+/gi, "-")}`;
  const extract = `Journal ${label} page 45: ${mark}, class 45, legal services (captured by the BUG-014 journey).`;
  const journalDate = new Date().toISOString().slice(0, 10);

  await page.goto(`${rt.web.origin}/app/ip/watch`);
  await expect(page.getByRole("heading", { name: "Trademark journal watch" })).toBeVisible();
  const scope = page.getByRole("combobox", { name: "Docket scope", exact: true });
  await expect(scope).toHaveValue("");
  await expect(scope.locator("option:checked")).toHaveText("All accessible dockets");

  // Availability: manual intake vs each automated-polling gate, from the same readiness the API reports.
  const readiness = await json(await request.get(`${rt.api.origin}/api/ip/readiness`, { headers: rt.headers }), "Tester readiness");
  const watch = readiness.features.find((row: { feature_id: string }) => row.feature_id === "watch_operations");
  expect(watch, "readiness reports watch operations").toBeTruthy();
  const reasons: string[] = watch.blocked_reasons?.length ? watch.blocked_reasons : watch.available ? [] : [watch.reason];
  const automated = page.getByTestId("watch-readiness-automated");
  for (const category of new Set(reasons.map(reason => BLOCKED_CATEGORY[reason]))) {
    await expect(automated.getByText(category, { exact: true })).toBeVisible();
  }
  if (reasons.length === 0) await expect(automated.getByText("Available", { exact: true })).toBeVisible();
  await expect(page.getByTestId("watch-readiness-manual").getByText("Available", { exact: true })).toBeVisible();
  await expect(page.getByTestId("watch-readiness-manual")).toContainText("This is the manual path");
  await checkLayout();

  // A stamped profile that watches the stamped mark in class 45, recipients chosen by name.
  await page.getByRole("button", { name: "Profiles", exact: true }).click();
  const profileDocket = page.getByRole("combobox", { name: "Docket", exact: true });
  await page.getByLabel("Find docket", { exact: true }).fill(docket.title);
  await expect(profileDocket.locator(`option[value="${docket.id}"]`)).toHaveCount(1);
  await expect(profileDocket).toBeEnabled();
  await profileDocket.selectOption(docket.id);
  await page.getByLabel("Profile name", { exact: true }).fill(`BUG-014 ${label}`);
  await page.getByLabel("Word terms", { exact: true }).fill(mark);
  await page.getByLabel("Nice classes", { exact: true }).fill("Class 45");
  const chosen = page.getByRole("list", { name: "Chosen recipients" });
  await expect(chosen).toContainText(new RegExp(rt.credentials.email.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "i"));
  expect(await internalFieldLabels(page), "No profile field asks for an internal id or raw JSON").toEqual([]);
  expect(await deadSelects(page, page.locator("main")), "No dead select in the profile form").toEqual([]);
  await checkLayout();
  const profileResponse = page.waitForResponse(response =>
    response.url().endsWith("/api/ip/watch/profiles") && response.request().method() === "POST");
  await page.getByRole("button", { name: "Create profile" }).click();
  const profile = await uiJson(await profileResponse, "Create watch profile through the UI", 201);
  expect(profile.class_numbers_json).toEqual([45]);
  expect(profile.recipient_membership_ids_json).toEqual([rt.actor.membership.id]);
  await expect(page.getByTestId(`watch-profile-${profile.id}`)).toContainText(`BUG-014 ${label}`);

  // The reported failure: a token that is not a class, and no captured evidence.
  await page.getByRole("button", { name: "Journal intake", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Manual official-journal intake" })).toBeVisible();
  const ingestRequests: string[] = [];
  page.on("request", req => {
    if (req.url().includes("/api/ip/watch/journal-ingestions")) ingestRequests.push(req.method());
  });
  await page.getByLabel("Journal number", { exact: true }).fill(label);
  await page.getByLabel("Journal date", { exact: true }).fill(journalDate);
  await page.getByLabel("Registry application number", { exact: true }).fill(applicationNumber);
  await page.getByLabel("Published word mark", { exact: true }).fill(mark);
  const classes = page.getByLabel("Published Nice classes", { exact: true });
  await classes.fill("Class 30 - Biscuits");
  await page.getByLabel("Official source URL", { exact: true }).fill(SOURCE_URL);
  await page.getByLabel("Source page", { exact: true }).fill("45");
  expect(await internalFieldLabels(page), "No intake field asks for an internal id or raw JSON").toEqual([]);
  expect(await deadSelects(page, page.locator("main")), "No dead select in the intake form").toEqual([]);
  await page.getByRole("button", { name: "Record and compare" }).click();
  await expect(classes).toHaveAttribute("aria-invalid", "true");
  await expect(classes).toHaveAccessibleDescription(/"Biscuits" is not a Nice class number/);
  await expect(classes).toBeFocused();
  await expectOnScreen(classes, "The bad class field is shown where the tester is looking");
  const extractField = page.getByLabel("Journal entry as published", { exact: true });
  await expect(extractField).toHaveAttribute("aria-invalid", "true");
  await expect(extractField).toHaveAccessibleDescription(/Capture the source evidence/);
  await expect(page.getByTestId("journal-intake-error")).toContainText("Published Nice classes, Captured source evidence");
  await page.waitForTimeout(300);
  expect(ingestRequests, "A refused form sends nothing").toEqual([]);
  await checkLayout();

  // Ram's reported inputs, now recorded.
  await classes.fill("Class 45");
  await page.getByLabel("Class 45 goods/services as published", { exact: true }).fill("Legal services");
  await extractField.fill(extract);
  await expect(classes).not.toHaveAttribute("aria-invalid", "true");
  const ingestResponse = page.waitForResponse(response =>
    response.url().endsWith("/api/ip/watch/journal-ingestions") && response.request().method() === "POST");
  await page.getByRole("button", { name: "Record and compare" }).click();
  const ingested = await uiJson(await ingestResponse, "Record the journal entry through the UI", 201);
  const entry = ingested.publications[0];
  expect(entry.class_numbers_json).toEqual([45]);
  expect(entry.goods_services_json).toEqual({ "45": ["Legal services"] });
  expect(entry.raw_evidence_json).toEqual({ capture_method: "manual", extract_text: extract });
  const ownHit = ingested.hits.find((hit: { profile_id: string }) => hit.profile_id === profile.id);
  expect(ownHit, "The stamped profile matches the stamped mark").toBeTruthy();
  const result = page.getByTestId("journal-intake-result");
  await expect(result).toContainText(`Recorded: Journal ${label} · Application ${applicationNumber} · ${mark}`);
  await expect(result).toContainText(`${ingested.hits.length} new watch ${ingested.hits.length === 1 ? "hit" : "hits"}`);
  await expectOnScreen(result, "The recorded summary is on screen after submit");
  const listed = page.getByTestId(`journal-entry-${entry.id}`);
  await listed.scrollIntoViewIfNeeded();
  await expectOnScreen(listed, "The recorded entry is listed");
  await expect(listed).toContainText(`Application ${applicationNumber}`);
  const workspace = await json(await request.get(`${rt.api.origin}/api/ip/watch?limit=250`, { headers: rt.headers }), "Watch workspace");
  expect(workspace.publications.map((row: { id: string }) => row.id)).toContain(entry.id);
  await checkLayout();

  // IP-WATCH-02: the captured evidence is shown with the hit.
  await result.getByRole("button", { name: /^Review (the hit|\d+ hits)$/ }).click();
  await page.getByTestId(`watch-hit-${ownHit.id}`).click();
  await expect(page.getByRole("heading", { name: mark })).toBeVisible();
  await expect(page.getByText(extract)).toBeVisible();
  await checkLayout();
  await markPositive(info, mobile ? "bug-014-capture-mobile" : "bug-014-capture", {
    local: rt.local, publication_id: entry.id, hit_id: ownHit.id, profile_id: profile.id, readiness: reasons,
  });

  // Retire what this run created through the product.
  await page.getByLabel("Disposition", { exact: true }).selectOption("not_relevant");
  await page.getByLabel("Reason", { exact: true }).fill(`BUG-014 journey ${label} retired`);
  await page.getByLabel(/I opened and confirmed/).check();
  const reviewed = page.waitForResponse(response =>
    response.url().endsWith(`/api/ip/watch/hits/${ownHit.id}/disposition`) && response.request().method() === "POST");
  await page.getByRole("button", { name: "Record review" }).click();
  expect((await uiJson(await reviewed, "Retire the journey hit")).disposition).toBe("not_relevant");
  await page.getByRole("button", { name: "Profiles", exact: true }).click();
  const card = page.getByTestId(`watch-profile-${profile.id}`);
  const paused = page.waitForResponse(response =>
    response.url().endsWith(`/api/ip/watch/profiles/${profile.id}/status`) && response.request().method() === "POST");
  await card.getByRole("button", { name: "Pause" }).click();
  expect((await uiJson(await paused, "Pause the journey profile")).poll_status).toBe("paused");
  await expect(card.getByText("paused", { exact: true })).toBeVisible();
}

test("BUG-014 journal capture: 'Class 45' with captured evidence is recorded, listed and shown on the hit; a bad class token is refused at its field", async ({ page, request, baseURL }, info) => {
  test.setTimeout(6 * 60_000);
  const rt = await prepareTester(page, request, baseURL);
  await captureJournalEntry(page, request, rt, info, false);
  await rt.release();
});

test("[mobile] BUG-014 journal capture works at 393px without horizontal page scroll", async ({ page, request, baseURL }, info) => {
  test.setTimeout(6 * 60_000);
  const rt = await prepareTester(page, request, baseURL, { width: 393, height: 851 });
  await captureJournalEntry(page, request, rt, info, true);
  await rt.release();
});
