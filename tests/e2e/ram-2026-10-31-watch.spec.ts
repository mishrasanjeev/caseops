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
 *   listed among recorded entries, and its evidence is shown on the hit with
 *   labelled similarity fields (no internal ids, no JSON);
 * - the test's own hit and profile are retired through the product
 *   (attorney disposition, profile pause), and the entry stays listed after
 *   the profile is paused. Journal entries are append-only. If the journey
 *   fails part-way, the finally block still retires the stamped hit and
 *   profile by server id, so no active stamped profile is left in the tenant.
 *
 * Production retains every run's records, so everything is stamped and
 * selected by server identity. Locally the docket is created through the API:
 * it is an unrelated prerequisite (docket creation is not under test).
 */
import {
  expect, test, type APIRequestContext, type Page, type Response, type TestInfo,
} from "@playwright/test";
import { types } from "node:util";

import {
  expectNoPageOverflow, expectOnScreen, json, deadSelects, markPositive, prepareTester, stamp,
  type TesterRuntime,
} from "./support/ram-bugs4";
import { recordBatch4Diagnostic, type WatchIntakeError, type WatchUuidProvenance } from "./support/batch4-safe-diagnostics";

test.use({ trace: "off", screenshot: "off", video: "off", storageState: { cookies: [], origins: [] } });
test.describe.configure({ mode: "default", retries: 0 });

const SOURCE_URL = "https://search.ipindia.gov.in/IPOJournal/Journal/ViewJournal";
const INTERNAL_FIELD = /\b(?:membership ids?|member ids?|uuid|sha-?256|raw (?:source )?json|json)\b/i;
const UUID_TEXT = /\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b/i;
const JSON_TEXT = /\{\s*"[a-z_]+"\s*:/i;

type WatchUuidReferences = { technical_ids: string[]; business_uuids: string[] };

/** Classify only this visible error's first paragraph; never return its text. */
function renderedJournalError(): WatchIntakeError["code"] | false {
  const matches = document.querySelectorAll('[data-testid="journal-intake-error"]');
  if (matches.length !== 1) return false;
  const root = matches[0];
  if (!(root instanceof HTMLElement)) return false;
  const bounds = root.getBoundingClientRect();
  const style = window.getComputedStyle(root);
  if (bounds.width === 0 || bounds.height === 0 || style.visibility === "hidden" || style.display === "none") return false;
  const paragraph = root.querySelector(":scope > p");
  const text = paragraph?.textContent?.replace(/\s+/g, " ").trim() ?? "";
  if (!text || text === "Correct the highlighted fields before recording the entry.") return false;
  if (text.length > 16384) return "unknown";
  if (text === "This idempotency key was already used for a different journal payload.") return "idempotency_payload_mismatch";
  if (text === "No active watch profile can be compared with this journal entry. Create or resume a watch profile, then capture the entry.") return "no_active_profile";
  if (text === "Journal ingestion conflicted; retry safely.") return "ingestion_conflict";
  if (text.startsWith("Journal ") && text.endsWith(" is already recorded with different details or evidence. The first capture is kept unchanged. Review the recorded entry; record a correction or re-advertisement only if the journal itself published one.")) return "recorded_entry_differs";
  return "unknown";
}

/** Deadline is conservative inside the unchanged original test timeout. No HTTP. */
async function captureJournalIntakeError(page: Page, diagnosticUntil: number): Promise<WatchIntakeError> {
  const stop = Math.min(diagnosticUntil, performance.now() + 2000);
  const remaining = stop - performance.now();
  if (remaining <= 0) return { kind: "watch_intake_error", code: "unavailable" };
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    const observation = async () => {
      const handle = await page.waitForFunction(renderedJournalError, undefined, { timeout: remaining, polling: 50 });
      try { return await handle.jsonValue(); }
      finally { await handle.dispose(); }
    };
    const code = await Promise.race([
      observation(),
      new Promise<WatchIntakeError["code"]>((resolve) => { timer = setTimeout(() => resolve("unavailable"), remaining); }),
    ]);
    if (performance.now() >= stop || code === false) return { kind: "watch_intake_error", code: "unavailable" };
    return { kind: "watch_intake_error", code };
  } catch { return { kind: "watch_intake_error", code: "unavailable" }; }
  finally { clearTimeout(timer); }
}

/** Only named scalar fields from responses already read by the original journey. */
function watchUuidReferences(
  rt: TesterRuntime, docket: Docket, profile: unknown, ingested: unknown, workspace: unknown,
): WatchUuidReferences {
  const technical = new Set<string>();
  const business = new Set<string>();
  const reject = (): never => { throw new Error("WATCH_UUID_PROVENANCE_REFUSED"); };
  const field = (value: unknown, key: string): unknown => {
    if (value === null || value === undefined) return undefined;
    if (typeof value !== "object" || Array.isArray(value) || types.isProxy(value)
      || ![Object.prototype, null].includes(Object.getPrototypeOf(value))) reject();
    const descriptor = Object.getOwnPropertyDescriptor(value, key);
    if (!descriptor) return undefined;
    if (!Object.hasOwn(descriptor, "value") || descriptor.get || descriptor.set) reject();
    return descriptor.value;
  };
  const list = (value: unknown): unknown[] => {
    if (value === undefined || value === null) return [];
    if (!Array.isArray(value) || types.isProxy(value) || value.length > 1000) reject();
    return Array.from({ length: (value as unknown[]).length }, (_, index) => {
      const descriptor = Object.getOwnPropertyDescriptor(value, String(index));
      if (!descriptor || !Object.hasOwn(descriptor, "value") || descriptor.get || descriptor.set) reject();
      return descriptor!.value;
    });
  };
  const add = (set: Set<string>, value: unknown, technicalValue = false) => {
    if (value === null || value === undefined) return;
    if (typeof value !== "string" || value.length > 20000) reject();
    const found = technicalValue
      ? new RegExp(`^(?:${UUID_TEXT.source})$`, "i").test(value as string) ? [value as string] : []
      : Array.from((value as string).matchAll(new RegExp(UUID_TEXT.source, "gi")), (match) => match[0]);
    for (const token of found) set.add(token.toLowerCase());
    if (set.size > 10000) reject();
  };
  const ids = (value: unknown, names: string[]) => names.forEach((key) => add(technical, field(value, key), true));
  const texts = (value: unknown, names: string[]) => names.forEach((key) => add(business, field(value, key)));
  const optionalAnyText = (value: unknown) => {
    if (types.isProxy(value)) reject();
    if (typeof value === "string") add(business, value);
  };
  const optionalAnyTexts = (value: unknown, names: string[]) =>
    names.forEach((key) => optionalAnyText(field(value, key)));
  const optionalAnyList = (value: unknown): unknown[] => {
    if (types.isProxy(value)) reject();
    return Array.isArray(value) ? list(value) : [];
  };
  const profileFields = (value: unknown) => {
    ids(value, ["id", "company_id", "docket_id", "created_by_membership_id"]);
    list(field(value, "recipient_membership_ids_json")).forEach((item) => add(technical, item, true));
    texts(value, ["name"]);
    for (const key of ["word_terms_json", "phonetic_terms_json", "proprietor_terms_json"])
      list(field(value, key)).forEach((item) => add(business, item));
  };
  const publicationFields = (value: unknown) => {
    ids(value, ["id", "company_id", "application_id", "supersedes_publication_id"]);
    texts(value, ["mark_text", "application_number", "journal_number", "proprietor_name", "source_page", "source_url"]);
    // A closed whitelist, never recursive traversal of raw_evidence_json.
    optionalAnyTexts(field(value, "raw_evidence_json"), ["extract_text", "evidence_reference", "notes"]);
    for (let niceClass = 1; niceClass <= 45; niceClass += 1)
      list(field(field(value, "goods_services_json"), String(niceClass))).forEach((item) => add(business, item));
  };
  const hitFields = (value: unknown) => {
    ids(value, ["id", "company_id", "profile_id", "publication_id", "duplicate_of_hit_id", "reviewed_by_membership_id"]);
    optionalAnyTexts(field(value, "candidate_mark_json"), ["mark_text", "application_number"]);
    const similarity = field(value, "similarity_evidence_json");
    for (const key of ["word", "phonetic"])
      optionalAnyList(field(similarity, key)).forEach((item) => {
        if (types.isProxy(item)) reject();
        if (item !== null && typeof item === "object" && !Array.isArray(item)) optionalAnyTexts(item, ["term"]);
      });
    optionalAnyList(field(similarity, "proprietor_matches")).forEach(optionalAnyText);
  };
  ids(rt.actor.company, ["id"]); ids(rt.actor.membership, ["id"]);
  ids(docket, ["id"]); texts(docket, ["title"]); profileFields(profile);
  for (const source of [ingested, workspace]) {
    list(field(source, "profiles")).forEach(profileFields);
    list(field(source, "hit_profiles")).forEach(profileFields);
    list(field(source, "publications")).forEach(publicationFields);
    list(field(source, "hits")).forEach(hitFields);
    for (const run of [field(source, "run"), ...list(field(source, "ingestion_runs"))]) {
      ids(run, ["id", "company_id", "requested_by_membership_id"]);
      for (const key of ["publication_ids_json", "hit_ids_json"])
        list(field(run, key)).forEach((item) => add(technical, item, true));
    }
    for (const handoff of list(field(source, "handoffs")))
      ids(handoff, ["id", "company_id", "hit_id", "target_id", "created_by_membership_id"]);
  }
  return { technical_ids: [...technical], business_uuids: [...business] };
}

/** One synchronous DOM observation; only row aggregates reach the diagnostic sink. */
function observeWatchUuidProvenance(root: HTMLElement | SVGElement, references: WatchUuidReferences) {
  const refuse = (): never => { throw new Error("WATCH_UUID_PROVENANCE_REFUSED"); };
  if (!(root instanceof HTMLElement) || root.tagName !== "MAIN") refuse();
  const hitText = (root as HTMLElement).innerText;
  if (hitText.length > 2_000_000) refuse();
  const pattern = /\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b/gi;
  const tokens = (text: string) => Array.from(text.matchAll(new RegExp(pattern.source, "gi")), (match) => match[0].toLowerCase());
  const matches = tokens(hitText);
  if (matches.length > 10000 || references.technical_ids.length > 10000 || references.business_uuids.length > 10000) refuse();
  const technical = new Set(references.technical_ids);
  const business = new Set(references.business_uuids);
  const surfaces = Array.from({ length: 5 }, () => new Set<string>());
  const observe = (category: number, element: Element | null | undefined) => {
    if (!element) return;
    const text = element instanceof HTMLElement ? element.innerText : element.textContent ?? "";
    if (text.length > 2_000_000) refuse();
    for (const token of tokens(text)) surfaces[category].add(token);
  };
  root.querySelectorAll('button[data-testid^="watch-hit-"] > strong').forEach((element) => observe(0, element));
  root.querySelectorAll("span").forEach((label) => {
    const value = label.nextElementSibling;
    if (value?.tagName !== "STRONG") return;
    if (label.textContent?.trim() === "Compared profile") observe(1, value);
    else if (["Classes", "Proprietor", "Publication scope"].includes(label.textContent?.trim() ?? "")) observe(4, value);
  });
  const evidenceLabels = new Set(["Journal entry as published", "Saved page reference", "Capture notes", "Goods and services", "Source page · retrieved"]);
  root.querySelectorAll("h3").forEach((heading) => {
    if (heading.textContent?.trim() !== "Official source evidence") return;
    heading.parentElement?.parentElement?.querySelectorAll("dl > div").forEach((item) => {
      if (evidenceLabels.has(item.querySelector("dt")?.textContent?.trim() ?? "")) observe(2, item.querySelector("dd"));
    });
  });
  root.querySelectorAll("select#watch-docket > option, p[data-selected-option-value]").forEach((element) => observe(3, element));
  root.querySelectorAll('h2, [data-testid="similarity-evidence"] dd').forEach((element) => observe(4, element));
  root.querySelectorAll("h2").forEach((heading) => {
    if (heading.nextElementSibling?.tagName === "P") observe(4, heading.nextElementSibling);
  });
  const row: WatchUuidProvenance = {
    kind: "watch_uuid_provenance", scope: "whole_main", occurrence_count: matches.length, unique_count: new Set(matches).size,
    technical_only_count: 0, business_only_count: 0, technical_and_business_count: 0, unknown_value_count: 0,
    queue_mark_only_count: 0, profile_name_only_count: 0, source_evidence_only_count: 0,
    docket_option_only_count: 0, labelled_business_only_count: 0, multiple_surface_count: 0, unknown_surface_count: 0,
  };
  const surfaceKeys = ["queue_mark_only_count", "profile_name_only_count", "source_evidence_only_count",
    "docket_option_only_count", "labelled_business_only_count"] as const;
  for (const token of matches) {
    if (technical.has(token) && business.has(token)) row.technical_and_business_count += 1;
    else if (technical.has(token)) row.technical_only_count += 1;
    else if (business.has(token)) row.business_only_count += 1;
    else row.unknown_value_count += 1;
    // Candidate roles are not a claim of exclusive DOM origin when a value repeats.
    const candidates = surfaces.flatMap((values, index) => values.has(token) ? [index] : []);
    if (candidates.length === 0) row.unknown_surface_count += 1;
    else if (candidates.length > 1) row.multiple_surface_count += 1;
    else row[surfaceKeys[candidates[0]]] += 1;
  }
  return { hitText, row };
}
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
type WatchDiagnosticFailure = { failed: boolean; error: unknown };

/** A browser response the UI itself made; body intentionally not logged. */
async function uiJson<T = any>(
  response: Response,
  operation: string,
  phase: "profile_create" | "journal_intake" | "hit_disposition" | "profile_pause",
  diagnosticFailure: WatchDiagnosticFailure,
  expected = 200,
  journalFailure?: () => Promise<WatchIntakeError>,
): Promise<T> {
  try {
    recordBatch4Diagnostic({ kind: "watch_http", phase, status: response.status() });
  } catch (error) {
    if (!diagnosticFailure.failed) {
      diagnosticFailure.failed = true;
      diagnosticFailure.error = error;
    }
  }
  try {
    expect(response.status(), `${operation} returned ${response.status()}`).toBe(expected);
  } catch (statusFailure) {
    if (phase === "journal_intake" && response.status() === 409 && journalFailure) {
      try { recordBatch4Diagnostic(await journalFailure()); }
      catch (error) {
        if (!diagnosticFailure.failed) { diagnosticFailure.failed = true; diagnosticFailure.error = error; }
      }
    }
    throw statusFailure;
  }
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
  // The docket list has no record-type filter: page through it until a trademark docket appears.
  let cursor: string | null = null;
  for (let pageNumber = 0; pageNumber < 20; pageNumber += 1) {
    const params = new URLSearchParams({ limit: "200" });
    if (cursor) params.set("cursor", cursor);
    const page = await json(await request.get(`${rt.api.origin}/api/ip/dockets?${params}`, { headers: rt.headers }), "Tester dockets");
    const docket = (page.dockets as Array<Docket & { record_type: string }>).find(row => row.record_type === "trademark");
    if (docket) return { id: docket.id, title: docket.title };
    if (!page.has_more || !page.next_cursor) break;
    cursor = page.next_cursor;
  }
  throw new Error("test-legal must have a visible trademark docket for a watch profile");
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

type Created = { profileId: string | null; profilePaused: boolean; hitId: string | null; hitRetired: boolean };

/** Fallback clean-up after a failed run, keyed by server id (the product path runs first). */
async function retireLeftovers(request: APIRequestContext, rt: TesterRuntime, created: Created) {
  if (!created.hitId && !created.profileId) return;
  const workspace = await json(await request.get(`${rt.api.origin}/api/ip/watch?limit=250`, { headers: rt.headers }), "Watch workspace for clean-up");
  if (created.hitId && !created.hitRetired) {
    const hit = workspace.hits.find((row: { id: string }) => row.id === created.hitId);
    if (hit && hit.disposition !== "not_relevant") {
      await json(await request.post(`${rt.api.origin}/api/ip/watch/hits/${hit.id}/disposition`, {
        headers: rt.headers,
        data: { expected_version: hit.version, disposition: "not_relevant", reason: "BUG-014 journey clean-up after a failed run", source_confirmed: true },
      }), "Retire the journey hit after a failure");
    }
  }
  if (created.profileId && !created.profilePaused) {
    const profile = workspace.profiles.find((row: { id: string }) => row.id === created.profileId);
    if (profile && profile.poll_status === "active") {
      await json(await request.post(`${rt.api.origin}/api/ip/watch/profiles/${profile.id}/status`, {
        headers: rt.headers,
        data: { expected_version: profile.version, poll_status: "paused", reason: "BUG-014 journey clean-up after a failed run" },
      }), "Pause the journey profile after a failure");
    }
  }
}

async function captureJournalEntry(
  page: Page, request: APIRequestContext, rt: TesterRuntime, info: TestInfo, mobile: boolean, diagnosticUntil: number,
) {
  const created: Created = { profileId: null, profilePaused: false, hitId: null, hitRetired: false };
  const diagnosticFailure: WatchDiagnosticFailure = { failed: false, error: undefined };
  try {
    await journey(page, request, rt, info, mobile, created, diagnosticFailure, diagnosticUntil);
  } finally {
    await retireLeftovers(request, rt, created);
  }
  return diagnosticFailure;
}

async function journey(
  page: Page, request: APIRequestContext, rt: TesterRuntime, info: TestInfo, mobile: boolean, created: Created,
  diagnosticFailure: WatchDiagnosticFailure, diagnosticUntil: number,
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
  // No automated journal source exists, so "Available" is never claimed for polling.
  await expect(automated.getByText("No journal source connected", { exact: true })).toBeVisible();
  await expect(automated.getByText("Available", { exact: true })).toHaveCount(0);
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
  const profile = await uiJson(await profileResponse, "Create watch profile through the UI", "profile_create", diagnosticFailure, 201);
  created.profileId = profile.id;
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
  const ingested = await uiJson(await ingestResponse, "Record the journal entry through the UI", "journal_intake", diagnosticFailure, 201,
    () => captureJournalIntakeError(page, diagnosticUntil));
  const entry = ingested.publications[0];
  expect(entry.class_numbers_json).toEqual([45]);
  expect(entry.goods_services_json).toEqual({ "45": ["Legal services"] });
  expect(entry.raw_evidence_json).toEqual({ capture_method: "manual", extract_text: extract });
  const ownHit = ingested.hits.find((hit: { profile_id: string }) => hit.profile_id === profile.id);
  expect(ownHit, "The stamped profile matches the stamped mark").toBeTruthy();
  created.hitId = ownHit.id;
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
  const similarity = page.getByTestId("similarity-evidence");
  await expect(similarity).toContainText("Word matches");
  await expect(similarity).toContainText("Class 45");
  let uuidSnapshot: ReturnType<typeof observeWatchUuidProvenance> | undefined;
  try {
    const references = watchUuidReferences(rt, docket, profile, ingested, workspace);
    uuidSnapshot = await page.locator("main").evaluate(observeWatchUuidProvenance, references);
  } catch (error) {
    if (!diagnosticFailure.failed) { diagnosticFailure.failed = true; diagnosticFailure.error = error; }
  }
  // A refused diagnostic has no row. The original oracle still runs unchanged.
  const hitText = uuidSnapshot ? uuidSnapshot.hitText : await page.locator("main").innerText();
  if (uuidSnapshot) {
    try { recordBatch4Diagnostic(uuidSnapshot.row); }
    catch (error) {
      if (!diagnosticFailure.failed) { diagnosticFailure.failed = true; diagnosticFailure.error = error; }
    }
  }
  expect(hitText, "The hit screen shows no internal id").not.toMatch(UUID_TEXT);
  expect(hitText, "The hit screen shows no raw JSON").not.toMatch(JSON_TEXT);
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
  expect((await uiJson(await reviewed, "Retire the journey hit", "hit_disposition", diagnosticFailure)).disposition).toBe("not_relevant");
  created.hitRetired = true;
  await page.getByRole("button", { name: "Profiles", exact: true }).click();
  const card = page.getByTestId(`watch-profile-${profile.id}`);
  const paused = page.waitForResponse(response =>
    response.url().endsWith(`/api/ip/watch/profiles/${profile.id}/status`) && response.request().method() === "POST");
  await card.getByRole("button", { name: "Pause" }).click();
  expect((await uiJson(await paused, "Pause the journey profile", "profile_pause", diagnosticFailure)).poll_status).toBe("paused");
  created.profilePaused = true;
  await expect(card.getByText("paused", { exact: true })).toBeVisible();

  // The recorded entry stays listed after its profile is paused, whatever the capture gate shows.
  await page.getByRole("button", { name: "Journal intake", exact: true }).click();
  const stillListed = page.getByTestId(`journal-entry-${entry.id}`);
  await stillListed.scrollIntoViewIfNeeded();
  await expectOnScreen(stillListed, "The recorded entry is still listed after the profile is paused");
  await expect(stillListed).toContainText(`Application ${applicationNumber}`);
  await checkLayout();
}

test("BUG-014 journal capture: 'Class 45' with captured evidence is recorded, listed and shown on the hit; a bad class token is refused at its field", async ({ page, request, baseURL }, info) => {
  test.setTimeout(6 * 60_000);
  // Before this callback the frozen project allows120s. Conservatively reserve it,
  // so this clock cannot extend the original360s including fixture setup.
  const diagnosticUntil = info.project.timeout === 120000 ? performance.now() + 239000 : 0;
  const rt = await prepareTester(page, request, baseURL);
  const diagnosticFailure = await captureJournalEntry(page, request, rt, info, false, diagnosticUntil);
  await rt.release();
  if (diagnosticFailure.failed) throw diagnosticFailure.error;
});

test("[mobile] BUG-014 journal capture works at 393px without horizontal page scroll", async ({ page, request, baseURL }, info) => {
  test.setTimeout(6 * 60_000);
  const diagnosticUntil = info.project.timeout === 120000 ? performance.now() + 239000 : 0;
  const rt = await prepareTester(page, request, baseURL, { width: 393, height: 851 });
  const diagnosticFailure = await captureJournalEntry(page, request, rt, info, true, diagnosticUntil);
  await rt.release();
  if (diagnosticFailure.failed) throw diagnosticFailure.error;
});
