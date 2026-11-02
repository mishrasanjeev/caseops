/**
 * B4-ADJ-25 / IPLF-057..059 / UJ-35..37: bounded IP list reads.
 * Authored only; not executed yet. Parent owns normal-suite discovery and
 * Docker/production acceptance. All invented identities stay in browser GET
 * fixtures; workspace failure is independent of list pagination acceptance.
 */
import { expect, test, type APIRequestContext, type Locator, type Page, type Route } from "@playwright/test";

import type {
  IpForeignAssociateInstruction, IpOffsetPage, IpRecordalListItem, MadridRecord,
} from "../../apps/web/lib/api/endpoints";
import { localTransportHeaders, noPaidProviderHeaders } from "./support/cost-controls";
import { expectNoPageOverflow, expectOnScreen, prepareTester, type TesterRuntime } from "./support/ram-bugs4";

test.use({
  trace: "off", screenshot: "off", video: "off", storageState: { cookies: [], origins: [] },
  extraHTTPHeaders: noPaidProviderHeaders,
});
test.describe.configure({ mode: "default", retries: 0 });

const PAGE_SIZE = 100;
const TOTAL = 201;
const AT = "2026-11-02T00:00:00Z";
const FAKE_PREFIX = "00000572-";
const MADRID = "/api/ip/international-registrations";
const WORKSPACE_ERROR = "Paging-only workspace intentionally unavailable.";
const viewports = [
  { name: "desktop", viewport: { width: 1440, height: 900 } },
  { name: "narrow phone", viewport: { width: 393, height: 851 } },
] as const;

function fixtureId(index: number): string {
  return `${FAKE_PREFIX}0000-4000-8000-${String(index).padStart(12, "0")}`;
}

function madridRow(rt: TesterRuntime, index: number): MadridRecord {
  return {
    id: fixtureId(index), company_id: rt.actor.company.id, docket_id: fixtureId(10_000 + index),
    record_kind: "international_registration", direction: "inbound", parent_registration_id: null,
    basic_application_id: null, international_application_number: null, ir_number: `IR${index}`,
    wipo_reference: `paging-IR${index}`, holder_name: "Pagination fixture holder", mark_name: `Paging Madrid ${index}`,
    office_of_origin: "WIPO", designated_member_code: null, designated_office: null, jurisdiction: null,
    designation_kind: null, classes_json: [9], goods_services_json: { "9": "Software" }, priority_claims_json: [],
    form_kind: null, wipo_status: "registered", national_status: null, local_agent_name: null,
    source_url: "https://www.wipo.int/madrid/monitor/en/", source_reference: "browser-read-fixture",
    source_retrieved_at: AT, application_date: null, international_registration_date: null,
    designation_effective_date: null, notification_date: null, publication_date: null, statement_date: null,
    dependency_end_date: null, renewal_due_date: null, version: 1,
    created_by_membership_id: rt.actor.membership.id, updated_by_membership_id: rt.actor.membership.id,
    created_at: AT, updated_at: AT,
  };
}

function instructionRow(rt: TesterRuntime, index: number): IpForeignAssociateInstruction {
  return {
    id: fixtureId(20_000 + index), company_id: rt.actor.company.id, docket_id: fixtureId(30_000 + index),
    instruction_thread_key: `paging-${index}`, instruction_version: 1, row_version: 1,
    supersedes_instruction_id: null, source_client_instruction_id: null, client_authority_reference: "Browser read fixture",
    target_jurisdiction: "GB", outside_counsel_id: fixtureId(40_000 + index), assignment_id: null,
    responsible_membership_id: rt.actor.membership.id,
    scope_json: { source_kind: "application", source_reference: `paging-${index}`, filing_kind: `Paging instruction ${index}` },
    selected_document_refs_json: [], privileged_document_refs_json: [], estimate_cost_item_id: fixtureId(50_000 + index),
    estimate_terms_json: {}, budget_policy_reference: "browser-read-fixture", approved_by_membership_id: null,
    approved_at: null, privileged_approved_by_membership_id: null, privileged_approved_at: null,
    dispatch_communication_id: null, external_dispatch_reference: null, external_delivery_reference: null,
    external_delivered_at: null, dispatched_at: null, acknowledged_at: null, acknowledgement_reference: null,
    response_due_at: null, filing_identifier: null, filing_reported_at: null, filing_evidence_refs_json: [],
    filing_verified_at: null, actual_cost_item_id: null, spend_record_id: null, status: "draft",
    created_by_membership_id: rt.actor.membership.id, updated_by_membership_id: rt.actor.membership.id,
    created_at: AT, updated_at: AT,
  };
}

function recordalRow(rt: TesterRuntime, index: number): IpRecordalListItem {
  return {
    id: fixtureId(60_000 + index), company_id: rt.actor.company.id, docket_id: fixtureId(70_000 + index),
    docket_title: `Paging recordal ${index}`, recordal_type: "assignment", legal_basis: "Browser read fixture",
    form_code: "TM-P", parties_json: [
      { role: "assignor", name: "Fixture assignor", identifier: null, address: null, evidence_reference: fixtureId(80_000 + index) },
      { role: "assignee", name: "Fixture assignee", identifier: null, address: null, evidence_reference: fixtureId(80_000 + index) },
    ], executed_on: "2026-11-01", effective_on: "2026-11-02",
    affected_registration_refs_json: [`TM-${index}`], affected_classes_json: [9], scope_json: { scope_kind: "whole_right" },
    supporting_instrument_refs_json: [fixtureId(80_000 + index)],
    fee_cost_item_refs_json: [], filing_evidence_refs_json: [], acceptance_evidence_refs_json: [],
    deadline_rule_key: null, registry_snapshot_id: null, status: "draft", version: 1,
    created_by_membership_id: rt.actor.membership.id, updated_by_membership_id: rt.actor.membership.id,
    created_at: AT, updated_at: AT,
  };
}

async function localTester(page: Page, request: APIRequestContext, baseURL: string | undefined, viewport: { width: number; height: number }) {
  // This assertion precedes authentication, tenant provisioning and all mocks.
  expect(baseURL, "Use the standard app/Docker configured baseURL").toBeTruthy();
  const web = new URL(baseURL!);
  expect(["localhost", "127.0.0.1", "[::1]"]).toContain(web.hostname);
  expect(["http:", "https:"]).toContain(web.protocol);
  expect(web.username + web.password).toBe("");
  const api = new URL(`http://${web.hostname}:${process.env.CASEOPS_E2E_API_PORT ?? "8000"}`);
  let mockReads: ((route: Route) => Promise<void>) | undefined;
  const violations: string[] = [];
  await page.context().setExtraHTTPHeaders(localTransportHeaders(web.origin));
  await page.route("**/*", async route => {
    const req = route.request();
    const url = new URL(req.url());
    if (!["http:", "https:"].includes(url.protocol)) return route.continue();
    const localOrigin = [web.origin, api.origin].includes(url.origin);
    const marked = req.headers()["x-caseops-automated-test"] === "no-paid-providers";
    const ipWrite = url.pathname.startsWith("/api/ip/") && !["GET", "HEAD", "OPTIONS"].includes(req.method());
    if (!localOrigin || !marked || ipWrite) {
      violations.push(`${req.method()} ${url.origin}${url.pathname}: ${!localOrigin ? "external" : !marked ? "unmarked" : "IP mutation"}`);
      return route.abort("blockedbyclient");
    }
    if (mockReads && url.pathname.startsWith("/api/ip/")) return mockReads(route);
    return route.continue();
  });
  const rt = await prepareTester(page, request, baseURL, viewport);
  expect(rt.local).toBe(true);
  expect(rt.api.origin).toBe(api.origin);
  return {
    rt,
    mockReads: (handler: (route: Route) => Promise<void>) => { mockReads = handler; },
    assertSafe: () => expect(violations, "Every app request is local, marked no-paid-providers, and read-only for IP").toEqual([]),
  };
}

function latch() {
  let release!: () => void;
  const promise = new Promise<void>(resolve => { release = resolve; });
  return { promise, release };
}

async function reply(route: Route, body: unknown, status = 200) {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

type ListRow = MadridRecord | IpForeignAssociateInstruction | IpRecordalListItem;

function readFixture(path: string, rows: ListRow[], parentChooser = false) {
  const offsets: number[] = [];
  const problems: string[] = [];
  let next: { release: Promise<void>; fail: boolean } | undefined;
  let parentReads = false;
  const handle = async (route: Route) => {
    const url = new URL(route.request().url());
    if (url.pathname === path) {
      const filtered = url.searchParams.get("record_kind") === "international_registration";
      if (parentChooser && !filtered) {
        const body: IpOffsetPage<ListRow> = { items: rows.slice(0, 1), total: 1, limit: PAGE_SIZE, offset: 0 };
        return reply(route, body);
      }
      const offset = Number(url.searchParams.get("offset"));
      offsets.push(offset);
      if ((parentChooser && !parentReads) || url.searchParams.get("limit") !== String(PAGE_SIZE)
        || !["0", String(PAGE_SIZE)].includes(url.searchParams.get("offset") ?? "")) {
        problems.push(`Unexpected list read: ${url.search}`);
        return route.abort("blockedbyclient");
      }
      if (offset) {
        const permitted = next;
        next = undefined;
        if (!permitted) {
          problems.push(`Automatic next-page read at ${offset}`);
          return route.abort("blockedbyclient");
        }
        await permitted.release;
        if (permitted.fail) return reply(route, { detail: "Next page temporarily unavailable." }, 503);
      }
      const body: IpOffsetPage<ListRow> = { items: rows.slice(offset, offset + PAGE_SIZE), total: rows.length, limit: PAGE_SIZE, offset };
      return reply(route, body);
    }
    if (new RegExp(`^/api/ip/(international-registrations|foreign-associate-instructions|recordals)/${FAKE_PREFIX}[^/]+/workspace$`).test(url.pathname)) {
      return reply(route, { detail: WORKSPACE_ERROR }, 503);
    }
    if (url.href.includes(FAKE_PREFIX)) {
      problems.push(`Unexpected fixture identity read: ${url.pathname}`);
      return route.abort("blockedbyclient");
    }
    return route.continue();
  };
  return {
    handle, offsets,
    openParents: () => { parentReads = true; },
    allowNext: (release: Promise<void>, fail: boolean) => { next = { release, fail }; },
    assertSafe: () => expect(problems, "No eager, unbounded or automatic next-page reads").toEqual([]),
  };
}

async function reachable(page: Page, control: Locator) {
  await control.scrollIntoViewIfNeeded();
  await expect(control).toBeVisible();
  await expectOnScreen(control, "The pagination control or row is reachable at this viewport");
  const box = await control.boundingBox();
  expect(box?.width ?? 0, "The control must not collapse on a phone").toBeGreaterThanOrEqual(44);
  await expectNoPageOverflow(page);
}

for (const { name, viewport } of viewports) {
  test.describe(`[local-only] IP pagination ${name}`, () => {
    test("Madrid parent IR101 is selectable after one explicit bounded next-page read", async ({ page, request, baseURL }) => {
      const local = await localTester(page, request, baseURL, viewport);
      const rows = Array.from({ length: TOTAL }, (_, index) => madridRow(local.rt, index + 1));
      const fixture = readFixture(MADRID, rows, true);
      local.mockReads(fixture.handle);
      await page.goto("/app/ip/madrid");
      await expect(page.getByRole("button", { name: /^Paging Madrid 1\b/ })).toBeVisible();
      expect(fixture.offsets, "Closed intake must not fetch the parent catalog").toEqual([]);
      await page.getByRole("button", { name: "New record", exact: true }).click();
      const form = page.locator("form").filter({ has: page.getByRole("button", { name: "Create record", exact: true }) });
      fixture.openParents();
      await form.getByLabel("Record type", { exact: true }).selectOption("international_designation");
      const parent = form.getByRole("combobox", { name: "Parent IR", exact: true });
      const more = form.getByRole("button", { name: "Load more parent IRs", exact: true });
      await expect(parent.locator('option:not([value=""])')).toHaveCount(PAGE_SIZE);
      await expect(parent).toHaveValue("");
      await expect(parent.locator(`option[value="${rows[100].id}"]`)).toHaveCount(0);
      expect(fixture.offsets).toEqual([0]);
      await reachable(page, more);
      await expect(more).toHaveAttribute("aria-busy", "false");
      const pending = latch();
      fixture.allowNext(pending.promise, false);
      try {
        await more.click();
        await expect.poll(() => fixture.offsets).toEqual([0, PAGE_SIZE]);
        await expect(more).toHaveAttribute("aria-busy", "true");
        await expect(more).toBeDisabled();
        await expect(parent.locator('option:not([value=""])')).toHaveCount(PAGE_SIZE);
      } finally { pending.release(); }
      await expect(parent.locator('option:not([value=""])')).toHaveCount(2 * PAGE_SIZE);
      await expect(parent.locator(`option[value="${rows[100].id}"]`)).toHaveText("Paging Madrid 101 \u00b7 IR101");
      await expect(parent).toHaveValue("");
      await reachable(page, parent);
      await parent.selectOption(rows[100].id);
      await expect(parent).toHaveValue(rows[100].id);
      await reachable(page, more);
      await expect(more).toBeEnabled();
      await expect(more).toHaveAttribute("aria-busy", "false");
      expect(fixture.offsets, "IR201 must remain unread until another explicit click").toEqual([0, PAGE_SIZE]);
      fixture.assertSafe();
      local.assertSafe();
    });

    test("Madrid, foreign-associate and recordal lists retain cached rows after one next-page 503 and retry the same offset", async ({ page, request, baseURL }) => {
      const local = await localTester(page, request, baseURL, viewport);
      const lanes = [
        { path: MADRID, pagePath: "/app/ip/madrid", noun: "Madrid records", label: "Paging Madrid", build: madridRow },
        { path: "/api/ip/foreign-associate-instructions", pagePath: "/app/ip/foreign-associates", noun: "instructions", label: "Paging instruction", build: instructionRow },
        { path: "/api/ip/recordals", pagePath: "/app/ip/recordals", noun: "recordals", label: "Paging recordal", build: recordalRow },
      ];
      for (const lane of lanes) {
        await test.step(lane.noun, async () => {
          const rows = Array.from({ length: TOTAL }, (_, index) => lane.build(local.rt, index + 1));
          const fixture = readFixture(lane.path, rows);
          local.mockReads(fixture.handle);
          await page.goto(lane.pagePath);
          const first = page.getByRole("button", { name: new RegExp(`\\b${lane.label} 1\\b`) });
          const hundredth = page.getByRole("button", { name: new RegExp(`\\b${lane.label} 100\\b`) });
          const older = page.getByRole("button", { name: new RegExp(`\\b${lane.label} 101\\b`) });
          const listRows = page.getByRole("button", { name: new RegExp(`\\b${lane.label} \\d+\\b`) });
          const more = page.getByRole("button", { name: `Load more ${lane.noun}`, exact: true });
          const error = page.getByRole("alert").filter({ hasText: `Could not load more ${lane.noun}.` });
          const count = page.getByRole("status").filter({ hasText: new RegExp(`^Showing \\d+ of ${TOTAL} ${lane.noun}$`) });
          await reachable(page, first);
          await expect(listRows).toHaveCount(PAGE_SIZE);
          await expect(count).toHaveText(`Showing ${PAGE_SIZE} of ${TOTAL} ${lane.noun}`);
          await expect(older).toHaveCount(0);
          expect(fixture.offsets).toEqual([0]);
          await reachable(page, hundredth);
          await reachable(page, more);
          const pending = latch();
          fixture.allowNext(pending.promise, true);
          try {
            await more.click();
            await expect.poll(() => fixture.offsets).toEqual([0, PAGE_SIZE]);
            await expect(more).toHaveAttribute("aria-busy", "true");
            await expect(more).toBeDisabled();
            await expect(first).toBeVisible();
            await expect(hundredth).toBeVisible();
          } finally { pending.release(); }
          await expect(error).toHaveText(`Could not load more ${lane.noun}. Try Load more again.`);
          await reachable(page, error);
          await expect(listRows).toHaveCount(PAGE_SIZE);
          await expect(count).toHaveText(`Showing ${PAGE_SIZE} of ${TOTAL} ${lane.noun}`);
          await reachable(page, first);
          await reachable(page, hundredth);
          await expect(older).toHaveCount(0);
          await reachable(page, more);
          await expect(more).toBeEnabled();
          await expect(more).toHaveAttribute("aria-busy", "false");
          // Keep the explicit-retry permit closed across the default 1s retry
          // window; any automatic read is rejected and retained in problems.
          await page.waitForTimeout(1_100);
          expect(fixture.offsets).toEqual([0, PAGE_SIZE]);
          fixture.assertSafe();
          fixture.allowNext(Promise.resolve(), false);
          await more.click();
          await expect(count).toHaveText(`Showing ${2 * PAGE_SIZE} of ${TOTAL} ${lane.noun}`);
          await expect(listRows).toHaveCount(2 * PAGE_SIZE);
          await expect(error).toHaveCount(0);
          await reachable(page, first);
          await reachable(page, hundredth);
          await reachable(page, older);
          await reachable(page, more);
          await expect(more).toBeEnabled();
          await expect(more).toHaveAttribute("aria-busy", "false");
          expect(fixture.offsets, "Retry the failed offset once; do not fetch the third page").toEqual([0, PAGE_SIZE, PAGE_SIZE]);
          fixture.assertSafe();
          local.assertSafe();
        });
      }
    });
  });
}
