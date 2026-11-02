import { readFileSync } from "node:fs";
import ts from "typescript";
import { test } from "node:test";
import assert from "node:assert/strict";
import { ContractError, displayDay } from "./contracts.ts";
import { readFailure } from "./repository.ts";
import type { AuthorizedRequest } from "./repository.ts";
import {
  advanceSourcePage,
  createSourceRecordsRepository,
  decodeContractSource,
  decodeContractSourcePage,
  decodeIpAvailability,
  decodeIpDocketSource,
  decodeIpPortfolioSource,
  decodeIpSourcePage,
  decodeSourceRef,
  formatSourceValue,
  SOURCE_GAPS,
  sourceDateStateLabel,
  sourceKey,
} from "./source-records.ts";

// Synthetic, unverified evidence. Shapes follow the current Python response
// schemas; these unit transports are not backend/native acceptance receipts.
const company = "synthetic-company";
const stamp = "2026-10-25T01:02:03.123456+05:30";
function contract(overrides: Record<string, unknown> = {}) {
  return {
    id: "synthetic-contract",
    company_id: company,
    linked_matter_id: null,
    owner_membership_id: "synthetic-owner",
    title: "Synthetic unverified contract",
    contract_code: "SYN-C-01",
    counterparty_name: null,
    contract_type: "NDA",
    contract_type_key: "nda",
    contract_type_notes: null,
    status: "draft",
    jurisdiction: null,
    effective_on: "2024-02-29",
    expires_on: null,
    renewal_on: "2026-10-25",
    auto_renewal: false,
    currency: "INR",
    total_value_minor: 1,
    summary: null,
    created_at: stamp,
    updated_at: stamp,
    ...overrides,
  };
}
function docket(overrides: Record<string, unknown> = {}) {
  return {
    id: "synthetic-docket",
    company_id: company,
    matter_id: null,
    record_type: "patent",
    title: "Synthetic patent",
    primary_identifier: null,
    status: "draft",
    is_active: true,
    lifecycle_version: 3,
    access_policy_version: 2,
    current_version: 4,
    updated_at: stamp,
    ...overrides,
  };
}
function ip(overrides: Record<string, unknown> = {}) {
  return {
    application_id: "synthetic-application",
    docket_id: "synthetic-docket",
    matter_id: null,
    asset_id: null,
    asset_kind: null,
    asset_title: null,
    asset_jurisdiction: null,
    docket_title: "Synthetic unverified application",
    docket_status: "draft",
    primary_identifier: null,
    application_numbers: [],
    opposition_numbers: [],
    nice_classes: [],
    goods_services: [],
    representation_kinds: [],
    proprietors: [],
    agents: [],
    source_renewal_due_on: "2028-02-29",
    source_application_on: "2024-02-29",
    current_version: 2,
    source_application_state: "imported_unverified",
    source_renewal_state: "manual",
    source_renewal_alert_at: null,
    source_renewal_alert_status: null,
    source_renewal_alert_body: null,
    client_name: null,
    responsible_lawyer: "Synthetic responsible lawyer",
    responsible_membership_id: "synthetic-owner",
    team_name: null,
    team_id: null,
    office: null,
    jurisdiction: null,
    filing_phase: "draft",
    is_active: true,
    lifecycle_version: 0,
    pending_identifier_allocation: true,
    record_complete: false,
    incomplete_reasons: ["Source identifier pending"],
    open_deadline_count: 0,
    unconfirmed_deadline_count: 0,
    overdue_deadline_count: 0,
    registry_sync_state: "unavailable",
    registry_last_success_at: null,
    provenance: ["Synthetic unverified import"],
    application_created_at: stamp,
    updated_at: stamp,
    ...overrides,
  };
}
function filters() {
  return {
    query: null,
    matter_id: null,
    client: [],
    proprietor: [],
    nice_class: [],
    responsible_membership_id: [],
    team_id: [],
    asset_kind: [],
    jurisdiction: [],
    office: [],
    filing_phase: [],
    docket_status: [],
    deadline_state: [],
    opposition_only: false,
    registry_sync_state: [],
    include_inactive: false,
    application_date_from: null,
    application_date_to: null,
    renewal_due_from: null,
    renewal_due_to: null,
    renewal_tracker_state: [],
  };
}
function ipPage(rows = [ip()], next: string | null = null) {
  return {
    rows,
    counts: {
      total: rows.length,
      complete_records: 0,
      incomplete_records: rows.length,
      unconfirmed_deadline_records: 0,
      overdue_records: 0,
      stale_sync_records: 0,
      synchronized_records: 0,
      sync_failure_records: null,
      registry_sync_state: "unavailable",
    },
    filters: filters(),
    limit: 25,
    next_cursor: next,
    latest_record_updated_at: stamp,
    latest_registry_success_at: null,
  };
}
function feature(overrides: Record<string, unknown> = {}) {
  return {
    feature_id: "workspace_core",
    available: true,
    reason: "available",
    owner: "product-ip",
    required_capabilities: ["ip:read"],
    missing_capabilities: [],
    entitlement_key: "ip_workspace",
    entitled: true,
    rollout_flag: "ip_workspace_enabled",
    rollout_enabled: true,
    rollout_expires_at: null,
    manual_fallback_feature_id: null,
    blocked_by_incident_id: null,
    ...overrides,
  };
}
function readiness(overrides: Record<string, unknown> = {}) {
  return {
    timezone: "Asia/Kolkata",
    workspace_available: true,
    manual_docketing_available: false,
    configuration_status: {
      configuration: {
        id: "synthetic-configuration",
        version: 1,
        enabled_asset_types_json: ["trademark"],
        jurisdictions_json: ["IN"],
        offices_json: ["Synthetic office"],
        timezone: "Asia/Kolkata",
        holiday_calendar_key: "synthetic",
        working_day_policy_json: {},
        document_taxonomy_version: "synthetic",
        event_catalog_version: "synthetic",
        deadline_rule_versions_json: {},
        notification_channels_json: [],
        renewal_reminder_cadence_days: 1,
        renewal_reminder_delivery_time: "09:00",
        critical_event_policy_json: {},
        escalation_owner_membership_id: "synthetic-owner",
        provider_keys_json: [],
        provider_terms_version: null,
        provider_terms_accepted_by_membership_id: null,
        provider_terms_accepted_at: null,
        enabled_automations_json: [],
        workspace_enabled: true,
        updated_by_membership_id: "synthetic-owner",
        created_at: stamp,
        updated_at: stamp,
      },
      tests: [],
      ready_for_manual_docketing: false,
      enablement_blockers: [],
      provider_adapters: [],
    },
    features: [feature()],
    domains: [],
    ...overrides,
  };
}
function setup(
  handler: (path: string, init?: RequestInit) => unknown | Promise<unknown>,
  capabilities = ["ip:read"],
) {
  const calls: { path: string; init?: RequestInit }[] = [];
  const request: AuthorizedRequest = async <T>(
    path: string,
    init?: RequestInit,
  ): Promise<T> => {
    calls.push({ path, init });
    return (await handler(path, init)) as T;
  };
  return {
    repository: createSourceRecordsRepository(request, company, capabilities),
    calls,
  };
}
const locator = {
  kind: "ip_docket" as const,
  docketId: "synthetic-docket",
  applicationId: "synthetic-application",
  cursor: null,
};
const contractRef = { kind: "contract", id: "synthetic-contract" } as const;
const contractLocator = {
  kind: "contract",
  contractId: "synthetic-contract",
  cursor: null,
} as const;
const ipRef = { kind: "ip_docket", id: "synthetic-docket" } as const;

test("canonical contract projection preserves nullable retained data, real dates, status, identity and exact minor units", () => {
  const value = decodeContractSource(contract(), company, "synthetic-contract");
  assert.equal(value.kind, "contract");
  assert.equal(value.linked_matter_id, null);
  assert.equal(value.effective_on, "2024-02-29");
  assert.equal(value.renewal_on, "2026-10-25");
  assert.equal(value.expires_on, null);
  assert.equal(value.status, "draft");
  assert.equal(value.updated_at, stamp);
  assert.equal(value.currency, "INR");
  assert.equal(
    formatSourceValue(value.total_value_minor, value.currency),
    "INR 1 minor unit",
  );
  assert.equal(
    formatSourceValue(9007199254740991, "USD"),
    "USD 9007199254740991 minor units",
  );
  assert.equal(formatSourceValue(0, "JPY"), "JPY 0 minor units");
  assert.equal(formatSourceValue(null, "KWD"), "Not recorded");
  assert.throws(() => formatSourceValue(0.5, "INR"), ContractError);
  assert.equal(
    decodeContractSource(
      contract({
        owner_membership_id: null,
        contract_type: "",
        currency: "CREDIT",
        total_value_minor: null,
        updated_at: "2026-10-25T01:02:03",
      }),
      company,
    ).updated_at,
    "2026-10-25T01:02:03",
  );
  assert.match(displayDay(value.effective_on!), /29/);
  assert.equal(
    decodeContractSource(contract({ status: "terminated" }), company).status,
    "terminated",
  );
});

test("contract decoder rejects wrong tenant, identity, source type, invalid facts and missing required nullable keys", () => {
  for (const changed of [
    { company_id: "another-tenant" },
    { id: "another-contract" },
    { status: "active" },
    { effective_on: "2025-02-29" },
    { expires_on: "2026-10-25T00:00:00Z" },
    { auto_renewal: "false" },
    { total_value_minor: Number.MAX_SAFE_INTEGER + 1 },
    { total_value_minor: -1 },
    { total_value_minor: "1" },
    { currency: null },
    { currency: "" },
    { updated_at: "2026-13-01T00:00:00Z" },
    { owner_membership_id: 4 },
  ])
    assert.throws(
      () =>
        decodeContractSource(contract(changed), company, "synthetic-contract"),
      ContractError,
    );
  for (const key of [
    "linked_matter_id",
    "expires_on",
    "counterparty_name",
    "summary",
    "total_value_minor",
  ])
    assert.throws(
      () => decodeContractSource({ ...contract(), [key]: undefined }, company),
      ContractError,
    );
  assert.throws(() => decodeContractSource(ip(), company), ContractError);
});

test("canonical paged contract DTOs retain continuation without row accumulation or cross-tenant siblings", () => {
  const page = {
    company_id: company,
    contracts: [contract()],
    next_cursor: "a+b/c=",
  };
  assert.equal(decodeContractSourcePage(page, company).next_cursor, "a+b/c=");
  assert.deepEqual(
    decodeContractSourcePage(
      { ...page, contracts: [], next_cursor: null },
      company,
    ).contracts,
    [],
  );
  for (const changed of [
    { company_id: "another-company" },
    { contracts: [contract(), contract()] },
    { contracts: [contract(), contract({ id: "other", company_id: "other" })] },
    { contracts: [], next_cursor: "next" },
    { next_cursor: "" },
    { next_cursor: undefined },
    {
      contracts: Array.from({ length: 26 }, (_, i) =>
        contract({ id: `synthetic-${i}` }),
      ),
    },
  ])
    assert.throws(
      () => decodeContractSourcePage({ ...page, ...changed }, company),
      ContractError,
    );
  assert.throws(
    () => decodeContractSourcePage(page, company, "a+b/c="),
    ContractError,
  );
});

test("canonical IP portfolio preserves distinct docket/application identities and unverified source dates/provenance", () => {
  const row = decodeIpPortfolioSource(ip());
  assert.equal(row.kind, "ip_docket");
  assert.equal(row.id, "synthetic-docket");
  assert.equal(row.application_id, "synthetic-application");
  assert.equal(row.matter_id, null);
  assert.equal(row.primary_identifier, null);
  assert.equal(row.source_application_on, "2024-02-29");
  assert.equal(row.source_application_state, "imported_unverified");
  assert.equal(row.source_renewal_due_on, "2028-02-29");
  assert.equal(row.source_renewal_state, "manual");
  assert.equal(row.current_version, 2);
  assert.equal(row.responsible_membership_id, "synthetic-owner");
  assert.deepEqual(row.provenance, ["Synthetic unverified import"]);
  assert.equal(
    sourceDateStateLabel(row.source_application_state),
    "Imported; not verified",
  );
  assert.equal(
    sourceDateStateLabel(row.source_renewal_state),
    "Manual date; not verified",
  );
  assert.equal(
    sourceDateStateLabel("verified"),
    "Server reports verified; verification evidence not supplied",
  );
  assert.equal(
    decodeIpPortfolioSource(
      ip({ source_application_on: null, source_application_state: "missing" }),
    ).source_application_on,
    null,
  );
});

test("IP strict decoder rejects date/state mismatches, malformed nested source facts and cross-type DTOs", () => {
  for (const changed of [
    { source_application_state: "missing" },
    { source_application_state: "approved" },
    { source_renewal_due_on: null },
    { source_renewal_due_on: "2026-02-29" },
    { source_renewal_state: undefined },
    { current_version: 0 },
    { pending_identifier_allocation: 1 },
    { provenance: [null] },
    { responsible_membership_id: 9 },
    { registry_sync_state: "ready" },
    { registry_last_success_at: "yesterday" },
    { incomplete_reasons: "none" },
    { source_renewal_alert_at: "2026-10-25T25:01:00Z" },
  ])
    assert.throws(() => decodeIpPortfolioSource(ip(changed)), ContractError);
  assert.throws(() => decodeIpPortfolioSource(contract()), ContractError);
});

test("IP pagination validates requested limit/filter scope and application uniqueness, not merely docket uniqueness", () => {
  assert.equal(
    decodeIpSourcePage(
      ipPage([ip(), ip({ application_id: "second-application" })]),
    ).rows.length,
    2,
  );
  for (const changed of [
    { limit: 50 },
    { rows: [ip(), ip()] },
    { filters: { ...filters(), include_inactive: true } },
    { filters: { ...filters(), responsible_membership_id: ["other-member"] } },
    { filters: { ...filters(), query: "unexpected" } },
    { filters: { ...filters(), matter_id: "synthetic-matter" } },
    { rows: [ip({ is_active: false })] },
    { rows: [], next_cursor: "next" },
    {
      rows: Array.from({ length: 26 }, (_, i) =>
        ip({ application_id: `app-${i}` }),
      ),
    },
  ])
    assert.throws(
      () => decodeIpSourcePage({ ...ipPage(), ...changed }),
      ContractError,
    );
  assert.throws(
    () => decodeIpSourcePage(ipPage([ip()], "same"), "same"),
    ContractError,
  );
});

test("source references cannot relabel IP/contracts as Matters, collide across kinds or accept arbitrary kinds", () => {
  assert.notEqual(
    sourceKey({ kind: "contract", id: "same" }),
    sourceKey({ kind: "ip_docket", id: "same" }),
  );
  for (const value of [
    { kind: "matter", id: "same" },
    { kind: "ip_application", id: "same" },
    { kind: "contract", id: "" },
    { kind: "ip_docket", id: "bad\nvalue" },
  ])
    assert.throws(() => decodeSourceRef(value), ContractError);
});

test("continuation history detects non-adjacent cycles and remains bounded with an explicit first-page recovery", () => {
  assert.deepEqual(advanceSourcePage([null, "a"], "b"), [null, "a", "b"]);
  assert.throws(() => advanceSourcePage([null, "a", "b"], "a"), ContractError);
  assert.throws(
    () =>
      advanceSourcePage(
        [null, ...Array.from({ length: 99 }, (_, i) => `cursor-${i}`)],
        "next",
      ),
    ContractError,
  );
  assert.throws(() => advanceSourcePage([], "next"), ContractError);
  assert.throws(() => advanceSourcePage([null], ""), ContractError);
});

test("IP availability follows the server's workspace_core capability/entitlement/rollout decision", () => {
  assert.deepEqual(decodeIpAvailability(readiness()), { state: "available" });
  assert.deepEqual(
    decodeIpAvailability(
      readiness({
        features: [
          feature({
            feature_id: "manual_docketing",
            available: false,
            reason: "missing_capability",
          }),
          feature(),
        ],
      }),
    ),
    { state: "available" },
  );
  for (const reason of [
    "missing_entitlement",
    "rollout_expired",
    "workspace_not_configured",
    "tenant_disabled",
    "incident_kill_switch",
  ])
    assert.equal(
      decodeIpAvailability(
        readiness({
          workspace_available: false,
          features: [feature({ available: false, reason })],
        }),
      ).state,
      "unavailable",
    );
  for (const changed of [
    { features: [] },
    { workspace_available: "true" },
    { features: [feature(), feature()] },
    { workspace_available: false },
    { features: [feature({ entitled: false })] },
    { configuration_status: { configuration: null } },
    { configuration_status: { configuration: { workspace_enabled: false } } },
    { configuration_status: undefined },
    { features: [feature({ rollout_enabled: false })] },
    { features: [feature({ entitlement_key: "invented" })] },
    { features: [feature({ missing_capabilities: ["ip:read"] })] },
    { features: [feature({ required_capabilities: [] })] },
    { features: [feature({ blocked_by_incident_id: "incident" })] },
  ])
    assert.throws(
      () => decodeIpAvailability(readiness(changed)),
      ContractError,
    );
});

test("contract reads use CurrentContext rather than creator roles, billing or IP entitlement", async () => {
  const { repository, calls } = setup(
    () => assert.fail("No transport expected"),
    [],
  );
  const availability = await repository.availability();
  assert.deepEqual(availability.contract, { state: "available" });
  assert.equal(availability.ip_docket.state, "unavailable");
  assert.equal((await repository.ipPage()).state, "unavailable");
  assert.deepEqual(calls, []);
});

test("contract list is one bounded page; exact-ID detail uses one encoded GET and same signal", async () => {
  const controller = new AbortController();
  const { repository, calls } = setup(
    (path) =>
      path.startsWith("/api/contracts/?")
        ? {
            company_id: company,
            contracts: [contract({ id: "contract/test" })],
            next_cursor: null,
          }
        : contract({ id: "contract/test" }),
    [],
  );
  await repository.contracts("a+b/c=", controller.signal);
  const result = await repository.detail(
    { kind: "contract", id: "contract/test" },
    { kind: "contract", contractId: "contract/test", cursor: "a+b/c=" },
    controller.signal,
  );
  assert.equal(result.state, "ready");
  if (result.state === "ready") assert.equal(result.record.id, "contract/test");
  assert.deepEqual(
    calls.map((call) => call.path),
    [
      "/api/contracts/?limit=25&cursor=a%2Bb%2Fc%3D",
      "/api/contracts/contract%2Ftest",
    ],
  );
  assert(
    calls.every(
      (call) =>
        !call.init?.method &&
        !call.init?.body &&
        call.init?.signal === controller.signal,
    ),
  );
});

test("oversized/malformed source continuations and cross-type locators fail before transport", async () => {
  const { repository, calls } = setup(() =>
    assert.fail("No transport expected"),
  );
  await assert.rejects(repository.contracts("x".repeat(8001)), ContractError);
  await assert.rejects(repository.ipPage(""), ContractError);
  await assert.rejects(
    repository.detail(contractRef, { ...contractLocator, contractId: "other" }),
    ContractError,
  );
  await assert.rejects(
    repository.detail(ipRef, contractLocator),
    ContractError,
  );
  await assert.rejects(
    repository.detail({ kind: "contract", id: "synthetic-contract" }, locator),
    ContractError,
  );
  await assert.rejects(
    repository.detail(ipRef, { ...locator, docketId: "another-docket" }),
    ContractError,
  );
  await assert.rejects(
    repository.detail(ipRef, { ...locator, applicationId: "" }),
    ContractError,
  );
  await assert.rejects(
    repository.detail(ipRef, {
      ...locator,
      cursor: undefined as unknown as null,
    }),
    ContractError,
  );
  assert.deepEqual(calls, []);
});

test("IP page and detail each refresh the real gate once, use one bounded page and never fan out docket/source requests", async () => {
  const controller = new AbortController();
  const { repository, calls } = setup((path) =>
    path === "/api/ip/readiness" ? readiness() : ipPage(),
  );
  assert.equal(
    (await repository.ipPage(null, controller.signal)).state,
    "ready",
  );
  const detail = await repository.detail(
    ipRef,
    { ...locator, cursor: "a+b/c=" },
    controller.signal,
  );
  assert.equal(detail.state, "ready");
  if (detail.state === "ready")
    assert.equal(detail.record.id, "synthetic-docket");
  assert.deepEqual(
    calls.map((call) => call.path),
    [
      "/api/ip/readiness",
      "/api/ip/portfolio?limit=25",
      "/api/ip/readiness",
      "/api/ip/portfolio?limit=25&cursor=a%2Bb%2Fc%3D",
    ],
  );
  assert(
    calls.every(
      (call) =>
        !call.init?.method &&
        !call.init?.body &&
        call.init?.signal === controller.signal,
    ),
  );
});

test("Calendar IP source rechecks readiness then reads one generic exact-ID summary without portfolio or Matter scans", async () => {
  const controller = new AbortController();
  const { repository, calls } = setup((path) =>
    path === "/api/ip/readiness" ? readiness() : docket({ id: "docket/test" }),
  );
  const result = await repository.detail(
    { kind: "ip_docket", id: "docket/test" },
    undefined,
    controller.signal,
  );
  assert.equal(result.state, "ready");
  if (result.state === "ready") {
    assert.ok("record_type" in result.record);
    assert.equal(result.record.record_type, "patent");
    assert.equal("source_renewal_due_on" in result.record, false);
    assert.equal("application_id" in result.record, false);
  }
  assert.deepEqual(
    calls.map((call) => call.path),
    ["/api/ip/readiness", "/api/ip/dockets/docket%2Ftest/summary"],
  );
  assert(
    calls.every(
      (call) =>
        !call.init?.method &&
        !call.init?.body &&
        call.init?.signal === controller.signal,
    ),
  );
});

test("bare contract source reads and reloads current scalar DTO directly, independently of original page membership", async () => {
  let title = "Before update";
  const { repository, calls } = setup(() => contract({ title }));
  const first = await repository.detail(contractRef);
  title = "Current server title";
  const second = await repository.detail(contractRef, contractLocator);
  assert.equal(first.state, "ready");
  assert.equal(second.state, "ready");
  if (first.state === "ready" && second.state === "ready") {
    assert.equal(
      "title" in first.record && first.record.title,
      "Before update",
    );
    assert.equal(
      "title" in second.record && second.record.title,
      "Current server title",
    );
  }
  assert.deepEqual(
    calls.map((call) => call.path),
    ["/api/contracts/synthetic-contract", "/api/contracts/synthetic-contract"],
  );
});

test("IP locator must match both source identities; moving/invisible records do not trigger automatic continuation", async () => {
  for (const row of [
    ip({ docket_id: "other" }),
    ip({ application_id: "other" }),
  ]) {
    const { repository, calls } = setup((path) =>
      path === "/api/ip/readiness" ? readiness() : ipPage([row], "next"),
    );
    assert.deepEqual(
      await repository.detail(ipRef, locator),
      SOURCE_GAPS.ipMoved,
    );
    assert.equal(calls.length, 2);
  }
});

test("changed IP readiness is not cached; disabled or unentitled module returns no portfolio labels", async () => {
  let enabled = true;
  const { repository, calls } = setup((path) =>
    path === "/api/ip/readiness"
      ? readiness(
          enabled
            ? {}
            : {
                workspace_available: false,
                features: [
                  feature({
                    available: false,
                    reason: "missing_entitlement",
                    entitled: false,
                  }),
                ],
              },
        )
      : ipPage(),
  );
  assert.equal((await repository.detail(ipRef, locator)).state, "ready");
  enabled = false;
  const result = await repository.detail(ipRef, locator);
  assert.equal(result.state, "unavailable");
  assert.equal("record" in result, false);
  assert.deepEqual(
    calls.map((call) => call.path),
    ["/api/ip/readiness", "/api/ip/portfolio?limit=25", "/api/ip/readiness"],
  );
});

test("restricted, offline and invalid-contract outcomes remain distinct and never cause scan/provider retries", async () => {
  for (const status of [401, 403, 404]) {
    const failure = Object.assign(new Error("Synthetic rejection"), { status });
    const { repository, calls } = setup(() => {
      throw failure;
    });
    await assert.rejects(
      repository.detail(contractRef, contractLocator),
      (error) => readFailure(error).kind === "restricted",
    );
    assert.equal(calls.length, 1);
  }
  const { repository, calls } = setup(() => {
    throw new TypeError("Synthetic offline transport");
  });
  await assert.rejects(
    repository.ipPage(),
    (error) => readFailure(error).kind === "offline",
  );
  assert.equal(calls.length, 1);
  const wrong = setup(() => contract({ company_id: "other-tenant" }));
  await assert.rejects(
    wrong.repository.detail(contractRef, contractLocator),
    (error) => readFailure(error).kind === "contract",
  );
  const crossType = setup(() => ip());
  await assert.rejects(
    crossType.repository.detail(contractRef, contractLocator),
    ContractError,
  );
});

test("generic IP summary preserves recorded type and rejects tenant/identity/inactive/type drift", () => {
  for (const record_type of ["trademark", "patent", "design"]) {
    const value = decodeIpDocketSource(
      docket({ record_type }),
      company,
      "synthetic-docket",
    );
    assert.deepEqual(value, { kind: "ip_docket", ...docket({ record_type }) });
  }
  for (const changed of [
    { id: "wrong" },
    { company_id: "foreign" },
    { is_active: false },
    { is_active: "true" },
    { lifecycle_version: -1 },
    { access_policy_version: 0.5 },
    { current_version: 0 },
    { record_type: "" },
    { matter_id: 42 },
    { updated_at: "yesterday" },
    { updated_at: "2026-10-27T01:02:03" },
  ])
    assert.throws(
      () => decodeIpDocketSource(docket(changed), company, "synthetic-docket"),
      ContractError,
    );
  for (const field of Object.keys(docket())) {
    assert.throws(
      () =>
        decodeIpDocketSource(
          { ...docket(), [field]: undefined },
          company,
          "synthetic-docket",
        ),
      ContractError,
    );
  }
});

test("generic IP deep link refuses a changed gate before summary and propagates exact transport/schema failure without retry", async () => {
  let available = true;
  const { repository, calls } = setup((path) =>
    path === "/api/ip/readiness"
      ? readiness(
          available
            ? {}
            : {
                workspace_available: false,
                features: [
                  feature({
                    available: false,
                    entitled: false,
                    reason: "missing_entitlement",
                  }),
                ],
              },
        )
      : docket(),
  );
  assert.equal((await repository.detail(ipRef)).state, "ready");
  available = false;
  assert.equal((await repository.detail(ipRef)).state, "unavailable");
  assert.deepEqual(
    calls.map((call) => call.path),
    [
      "/api/ip/readiness",
      "/api/ip/dockets/synthetic-docket/summary",
      "/api/ip/readiness",
    ],
  );
  for (const value of [
    docket({ id: "wrong" }),
    docket({ company_id: "foreign" }),
    docket({ is_active: false }),
  ]) {
    const invalid = setup((path) =>
      path === "/api/ip/readiness" ? readiness() : value,
    );
    await assert.rejects(invalid.repository.detail(ipRef), ContractError);
    assert.equal(invalid.calls.length, 2);
  }
  const original = new TypeError("Synthetic summary transport failure");
  const failed = setup((path) => {
    if (path === "/api/ip/readiness") return readiness();
    throw original;
  });
  await assert.rejects(
    failed.repository.detail(ipRef),
    (error) => error === original,
  );
  assert.equal(failed.calls.length, 2);
});

// Source composition contracts; actual scroll/back/device rendering remain in
// the separately expanded native plan, not in these source tests.
test("Calendar source callback composes into the originating tab stack and generic IP view without fabricated application IDs", () => {
  const file = ts.createSourceFile(
    "MobileApplication.tsx",
    readFileSync(
      new URL("../application/MobileApplication.tsx", import.meta.url),
      "utf8",
    ),
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TSX,
  );
  let calendar: ts.JsxSelfClosingElement | undefined;
  const visit = (node: ts.Node) => {
    if (
      ts.isJsxSelfClosingElement(node) &&
      node.tagName.getText(file) === "CalendarScreen"
    )
      calendar = node;
    ts.forEachChild(node, visit);
  };
  visit(file);
  assert.ok(calendar);
  const attribute = calendar.attributes.properties.find(
    (value) =>
      ts.isJsxAttribute(value) && value.name.getText(file) === "openSource",
  );
  assert.ok(
    attribute &&
      ts.isJsxAttribute(attribute) &&
      attribute.initializer &&
      ts.isJsxExpression(attribute.initializer),
  );
  assert.equal(
    attribute.initializer.expression?.getText(file),
    '(source) => push({ type: "source", source })',
  );
  let list: ts.JsxSelfClosingElement | undefined;
  const findList = (node: ts.Node) => {
    if (
      ts.isJsxSelfClosingElement(node) &&
      node.tagName.getText(file) === "SourceRecordsScreen"
    )
      list = node;
    ts.forEachChild(node, findList);
  };
  findList(file);
  assert.ok(list);
  const attrs = Object.fromEntries(
    list.attributes.properties
      .filter(ts.isJsxAttribute)
      .map((node) => [
        node.name.getText(file),
        node.initializer?.getText(file),
      ]),
  );
  assert.equal(attrs.kind, "{sourceKind}");
  assert.equal(attrs.onKindChange, "{setSourceKind}");
  const screen = readFileSync(
    new URL("../application/screens/SourceRecordsScreen.tsx", import.meta.url),
    "utf8",
  );
  assert.match(screen, /repository\.contracts\(cursor, signal\)/);
  assert.match(screen, /"record_type" in result\.record/);
  assert.match(screen, /<IpDocketDetail record=\{result\.record\}/);
  assert.match(
    screen.replace(/\s+/g, " "),
    /no dates are inferred from the Calendar event/,
  );
});
