import { array, ContractError, dateOnly, object, string } from "./contracts.ts";
import type { AuthorizedRequest } from "./repository.ts";
import { createContractObligationsRepository } from "./contract-obligations.ts";

export const SOURCE_PAGE_SIZE = 25;
export type SourceKind = "contract" | "ip_docket";
export type SourceRef =
  | { kind: "contract"; id: string }
  | { kind: "ip_docket"; id: string };
type Row = Record<string, unknown>;

function identity(value: unknown, field = "source identity"): string {
  const result = string(value, field, 200);
  if (!result.trim() || /[\x00-\x1f\x7f]/.test(result))
    throw new ContractError(field);
  return result;
}
function nullable<T>(value: unknown, decode: (value: unknown) => T): T | null {
  return value === null ? null : decode(value);
}
function text(value: unknown): string {
  return string(value, "source text");
}
function bool(value: unknown): boolean {
  if (typeof value !== "boolean") throw new ContractError("source flag");
  return value;
}
function integer(value: unknown, minimum = 0): number {
  if (
    typeof value !== "number" ||
    !Number.isSafeInteger(value) ||
    value < minimum
  )
    throw new ContractError("source integer");
  return value;
}
function oneOf<T extends string>(value: unknown, choices: readonly T[]): T {
  if (typeof value !== "string" || !choices.includes(value as T))
    throw new ContractError("source state");
  return value as T;
}
function timestamp(value: unknown): string {
  const result = string(value, "source timestamp", 64);
  const match =
    /^(\d{4}-\d{2}-\d{2})T([01]\d|2[0-3]):([0-5]\d):([0-5]\d)(?:\.\d{1,6})?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)?$/.exec(
      result,
    );
  if (!match) throw new ContractError("source timestamp");
  dateOnly(match[1]);
  return result; // Retained naive timestamps stay naive; never assign a timezone.
}
function continuation(value: unknown): string | null {
  return nullable(value, (item) => identityCursor(item));
}
function identityCursor(value: unknown): string {
  const result = string(value, "source continuation", 8000);
  if (!result.trim() || /[\x00-\x1f\x7f]/.test(result))
    throw new ContractError("source continuation");
  return result;
}
function unique<T>(rows: T[], key: (row: T) => string): T[] {
  if (new Set(rows.map(key)).size !== rows.length)
    throw new ContractError("duplicate source identity");
  return rows;
}
function nextCursor(
  row: Row,
  cursor: string | null,
  length: number,
): string | null {
  const next = continuation(row.next_cursor);
  if (next !== null && (next === cursor || length === 0))
    throw new ContractError("source continuation");
  return next;
}
export function decodeSourceRef(value: unknown): SourceRef {
  const row = object(value, "source reference");
  return {
    kind: oneOf(row.kind, ["contract", "ip_docket"]),
    id: identity(row.id),
  };
}
export function sourceKey(source: SourceRef): string {
  const ref = decodeSourceRef(source);
  return `${ref.kind}:${ref.id}`;
}
export function advanceSourcePage(
  history: readonly (string | null)[],
  next: string,
): (string | null)[] {
  identityCursor(next);
  if (
    !history.length ||
    history[0] !== null ||
    history.includes(next) ||
    history.length >= 100
  )
    throw new ContractError("source continuation; return to the first page");
  return [...history, next];
}

export type ContractSource = {
  kind: "contract";
  id: string;
  company_id: string;
  linked_matter_id: string | null;
  owner_membership_id: string | null;
  title: string;
  contract_code: string;
  counterparty_name: string | null;
  contract_type: string;
  status:
    | "draft"
    | "under_review"
    | "negotiation"
    | "executed"
    | "expired"
    | "terminated";
  jurisdiction: string | null;
  effective_on: string | null;
  expires_on: string | null;
  renewal_on: string | null;
  auto_renewal: boolean;
  currency: string;
  total_value_minor: number | null;
  summary: string | null;
  created_at: string;
  updated_at: string;
};
// Projection of schemas/contracts.py ContractRecord from bounded reads.
export function decodeContractSource(
  value: unknown,
  companyId: string,
  expectedId?: string,
): ContractSource {
  const row = object(value, "contract source");
  const id = identity(row.id);
  if (
    identity(row.company_id) !== identity(companyId) ||
    (expectedId !== undefined && id !== expectedId)
  )
    throw new ContractError("contract source identity");
  const currency = string(row.currency, "source currency", 8);
  if (currency.length < 3 || !currency.trim())
    throw new ContractError("source currency");
  return {
    kind: "contract",
    id,
    company_id: companyId,
    linked_matter_id: nullable(row.linked_matter_id, identity),
    owner_membership_id: nullable(row.owner_membership_id, identity),
    title: text(row.title),
    contract_code: text(row.contract_code),
    counterparty_name: nullable(row.counterparty_name, text),
    contract_type: text(row.contract_type),
    status: oneOf(row.status, [
      "draft",
      "under_review",
      "negotiation",
      "executed",
      "expired",
      "terminated",
    ]),
    jurisdiction: nullable(row.jurisdiction, text),
    effective_on: nullable(row.effective_on, dateOnly),
    expires_on: nullable(row.expires_on, dateOnly),
    renewal_on: nullable(row.renewal_on, dateOnly),
    auto_renewal: bool(row.auto_renewal),
    currency,
    total_value_minor: nullable(row.total_value_minor, integer),
    summary: nullable(row.summary, text),
    created_at: timestamp(row.created_at),
    updated_at: timestamp(row.updated_at),
  };
}
export type ContractSourcePage = {
  contracts: ContractSource[];
  next_cursor: string | null;
};
export function decodeContractSourcePage(
  value: unknown,
  companyId: string,
  cursor: string | null = null,
): ContractSourcePage {
  const row = object(value, "contract source page");
  if (identity(row.company_id) !== identity(companyId))
    throw new ContractError("contract page tenant");
  const contracts = unique(
    array(
      row.contracts,
      "contract sources",
      (item) => decodeContractSource(item, companyId),
      SOURCE_PAGE_SIZE,
    ),
    (item) => item.id,
  );
  return { contracts, next_cursor: nextCursor(row, cursor, contracts.length) };
}
export function formatSourceValue(
  minor: number | null,
  currency: string,
): string {
  if (minor === null) return "Not recorded";
  integer(minor);
  // The read contract does not supply a currency exponent. Preserve exact units.
  return `${currency} ${minor.toString()} minor ${minor === 1 ? "unit" : "units"}`;
}

// The exact-ID summary is generic: Calendar dockets can be patents, designs,
// trademarks or another server record type. It contains no inferred dates.
export type IpDocketSource = {
  kind: "ip_docket";
  id: string;
  company_id: string;
  matter_id: string | null;
  record_type: string;
  title: string;
  primary_identifier: string | null;
  status: string;
  is_active: true;
  lifecycle_version: number;
  access_policy_version: number;
  current_version: number;
  updated_at: string;
};
export function decodeIpDocketSource(
  value: unknown,
  companyId: string,
  expectedId: string,
): IpDocketSource {
  const row = object(value, "IP docket summary");
  const id = identity(row.id);
  if (
    id !== identity(expectedId) ||
    identity(row.company_id) !== identity(companyId) ||
    row.is_active !== true
  )
    throw new ContractError("IP docket source identity or lifecycle");
  return {
    kind: "ip_docket",
    id,
    company_id: companyId,
    matter_id: nullable(row.matter_id, identity),
    record_type: identity(row.record_type, "IP record type"),
    title: text(row.title),
    primary_identifier: nullable(row.primary_identifier, text),
    status: identity(row.status, "IP status"),
    is_active: true,
    lifecycle_version: integer(row.lifecycle_version),
    access_policy_version: integer(row.access_policy_version),
    current_version: integer(row.current_version, 1),
    updated_at: (() => {
      const value = timestamp(row.updated_at);
      if (!/(?:Z|[+-]\d{2}:\d{2})$/.test(value))
        throw new ContractError("IP summary UTC timestamp");
      return value;
    })(),
  };
}

export type SourceDateState =
  | "missing"
  | "manual"
  | "imported_unverified"
  | "verified";
export function sourceDateStateLabel(state: SourceDateState): string {
  switch (state) {
    case "missing":
      return "Not recorded";
    case "manual":
      return "Manual date; not verified";
    case "imported_unverified":
      return "Imported; not verified";
    case "verified":
      return "Server reports verified; verification evidence not supplied";
  }
}
export type IpPortfolioSource = {
  kind: "ip_docket";
  id: string;
  application_id: string;
  asset_id: string | null;
  matter_id: string | null;
  docket_title: string;
  docket_status: string;
  primary_identifier: string | null;
  application_numbers: string[];
  opposition_numbers: string[];
  office: string | null;
  jurisdiction: string | null;
  filing_phase: string;
  is_active: boolean;
  lifecycle_version: number;
  current_version: number;
  pending_identifier_allocation: boolean;
  record_complete: boolean;
  incomplete_reasons: string[];
  source_application_on: string | null;
  source_application_state: SourceDateState;
  source_renewal_due_on: string | null;
  source_renewal_state: SourceDateState;
  source_renewal_alert_at: string | null;
  source_renewal_alert_status: string | null;
  client_name: string | null;
  responsible_lawyer: string | null;
  responsible_membership_id: string | null;
  team_name: string | null;
  team_id: string | null;
  registry_sync_state: "current" | "stale" | "failed" | "unavailable";
  registry_last_success_at: string | null;
  provenance: string[];
  updated_at: string;
};
export function decodeIpPortfolioSource(value: unknown): IpPortfolioSource {
  const row = object(value, "IP portfolio source");
  const applicationDate = nullable(row.source_application_on, dateOnly);
  const renewalDate = nullable(row.source_renewal_due_on, dateOnly);
  const applicationState = oneOf(row.source_application_state, [
    "missing",
    "manual",
    "imported_unverified",
    "verified",
  ]);
  const renewalState = oneOf(row.source_renewal_state, [
    "missing",
    "manual",
    "imported_unverified",
    "verified",
  ]);
  if (
    (applicationDate === null) !== (applicationState === "missing") ||
    (renewalDate === null) !== (renewalState === "missing")
  )
    throw new ContractError("IP source date/state mismatch");
  const strings = (value: unknown) =>
    array(value, "IP source facts", text, 200);
  return {
    kind: "ip_docket",
    id: identity(row.docket_id),
    application_id: identity(row.application_id),
    asset_id: nullable(row.asset_id, identity),
    matter_id: nullable(row.matter_id, identity),
    docket_title: text(row.docket_title),
    docket_status: text(row.docket_status),
    primary_identifier: nullable(row.primary_identifier, text),
    application_numbers: strings(row.application_numbers),
    opposition_numbers: strings(row.opposition_numbers),
    office: nullable(row.office, text),
    jurisdiction: nullable(row.jurisdiction, text),
    filing_phase: text(row.filing_phase),
    is_active: bool(row.is_active),
    lifecycle_version: integer(row.lifecycle_version),
    current_version: integer(row.current_version, 1),
    pending_identifier_allocation: bool(row.pending_identifier_allocation),
    record_complete: bool(row.record_complete),
    incomplete_reasons: strings(row.incomplete_reasons),
    source_application_on: applicationDate,
    source_application_state: applicationState,
    source_renewal_due_on: renewalDate,
    source_renewal_state: renewalState,
    source_renewal_alert_at: nullable(row.source_renewal_alert_at, timestamp),
    source_renewal_alert_status: nullable(
      row.source_renewal_alert_status,
      text,
    ),
    client_name: nullable(row.client_name, text),
    responsible_lawyer: nullable(row.responsible_lawyer, text),
    responsible_membership_id: nullable(
      row.responsible_membership_id,
      identity,
    ),
    team_name: nullable(row.team_name, text),
    team_id: nullable(row.team_id, identity),
    registry_sync_state: oneOf(row.registry_sync_state, [
      "current",
      "stale",
      "failed",
      "unavailable",
    ]),
    registry_last_success_at: nullable(row.registry_last_success_at, timestamp),
    provenance: strings(row.provenance),
    updated_at: timestamp(row.updated_at),
  };
}
export type IpSourcePage = {
  rows: IpPortfolioSource[];
  next_cursor: string | null;
};
export function decodeIpSourcePage(
  value: unknown,
  cursor: string | null = null,
): IpSourcePage {
  const row = object(value, "IP portfolio page");
  if (integer(row.limit, 1) !== SOURCE_PAGE_SIZE)
    throw new ContractError("IP page limit");
  const rows = unique(
    array(row.rows, "IP sources", decodeIpPortfolioSource, SOURCE_PAGE_SIZE),
    (item) => item.application_id,
  );
  const filters = object(row.filters, "IP page scope");
  // Only the unfiltered, active portfolio is requested here. Do not silently
  // accept a different filter/ownership scope returned by an incompatible API.
  const emptyArrays = [
    "client",
    "proprietor",
    "nice_class",
    "responsible_membership_id",
    "team_id",
    "asset_kind",
    "jurisdiction",
    "office",
    "filing_phase",
    "docket_status",
    "deadline_state",
    "registry_sync_state",
    "renewal_tracker_state",
  ];
  if (
    emptyArrays.some(
      (key) => array(filters[key], "IP filter", (item) => item, 0).length !== 0,
    ) ||
    filters.query !== null ||
    filters.matter_id !== null ||
    filters.include_inactive !== false ||
    filters.opposition_only !== false ||
    [
      "application_date_from",
      "application_date_to",
      "renewal_due_from",
      "renewal_due_to",
    ].some((key) => filters[key] !== null) ||
    rows.some((item) => !item.is_active)
  )
    throw new ContractError("IP page scope");
  return { rows, next_cursor: nextCursor(row, cursor, rows.length) };
}

export type SourceUnavailable = {
  state: "unavailable";
  reason: string;
  message: string;
};
export type SourceAvailability = { state: "available" } | SourceUnavailable;
export const SOURCE_GAPS = {
  counsel:
    "Counsel assignments and budgets are unavailable in this source view.",
  ipMoved: {
    state: "unavailable",
    reason: "ip_source_not_on_page",
    message:
      "This application is no longer on its original page or is no longer visible. Return to the IP portfolio and select it again.",
  },
} as const;
export type SourceModuleAvailability = Record<SourceKind, SourceAvailability>;

export function decodeIpAvailability(value: unknown): SourceAvailability {
  const row = object(value, "IP readiness");
  const available = bool(row.workspace_available);
  const configurationStatus = object(
    row.configuration_status,
    "IP workspace configuration",
  );
  const configuration = nullable(configurationStatus.configuration, (value) =>
    object(value, "IP configuration"),
  );
  const workspaceEnabled =
    configuration === null ? false : bool(configuration.workspace_enabled);
  const features = unique(
    array(
      row.features,
      "IP readiness features",
      (value) => {
        const feature = object(value, "IP feature");
        return {
          id: identity(feature.feature_id),
          available: bool(feature.available),
          reason: oneOf(feature.reason, [
            "available",
            "unknown_feature",
            "missing_capability",
            "missing_entitlement",
            "rollout_disabled",
            "rollout_expired",
            "workspace_not_configured",
            "tenant_disabled",
            "readiness_test_failed",
            "incident_kill_switch",
          ]),
          entitled: bool(feature.entitled),
          rollout: bool(feature.rollout_enabled),
          entitlement: nullable(feature.entitlement_key, text),
          required: array(
            feature.required_capabilities,
            "required capabilities",
            identity,
            100,
          ),
          missing: array(
            feature.missing_capabilities,
            "missing capabilities",
            identity,
            100,
          ),
          incident: nullable(feature.blocked_by_incident_id ?? null, identity),
        };
      },
      100,
    ),
    (feature) => feature.id,
  );
  const core = features.find((feature) => feature.id === "workspace_core");
  if (
    !core ||
    available !== core.available ||
    core.available !== (core.reason === "available") ||
    (available &&
      (!workspaceEnabled ||
        !core.entitled ||
        !core.rollout ||
        core.entitlement !== "ip_workspace" ||
        !core.required.includes("ip:read") ||
        core.missing.length ||
        core.incident))
  )
    throw new ContractError("IP readiness decision");
  return available
    ? { state: "available" }
    : {
        state: "unavailable",
        reason: core.reason,
        message: `IP records are unavailable (${core.reason.replaceAll("_", " ")}). Reload to check current access and workspace readiness.`,
      };
}

// The locator re-reads exactly one authorized server page. It is not a saved
// record or an authority token; a moved/revoked source is never recovered by scan.
export type IpSourceLocator = {
  kind: "ip_docket";
  docketId: string;
  applicationId: string;
  cursor: string | null;
};
export type ContractSourceLocator = {
  kind: "contract";
  contractId: string;
  cursor: string | null;
};
export type SourceLocator = IpSourceLocator | ContractSourceLocator;
export type SourceDetail =
  | {
      state: "ready";
      record: ContractSource | IpPortfolioSource | IpDocketSource;
    }
  | SourceUnavailable;
export function createSourceRecordsRepository(
  request: AuthorizedRequest,
  companyId: string,
  capabilities: readonly string[],
) {
  identity(companyId, "workspace identity");
  const canReadIp = capabilities.includes("ip:read");
  const get = (path: string, signal?: AbortSignal) =>
    request<unknown>(path, { signal });
  const ipAvailability = async (
    signal?: AbortSignal,
  ): Promise<SourceAvailability> =>
    canReadIp
      ? decodeIpAvailability(await get("/api/ip/readiness", signal))
      : {
          state: "unavailable",
          reason: "missing_capability",
          message:
            "IP records are not available to this account. Reload your workspace after access changes.",
        };
  const ipPage = async (
    cursor: string | null = null,
    signal?: AbortSignal,
  ): Promise<{ state: "ready"; page: IpSourcePage } | SourceUnavailable> => {
    if (cursor !== null) identityCursor(cursor);
    const gate = await ipAvailability(signal);
    if (gate.state !== "available") return gate;
    const params = new URLSearchParams({ limit: String(SOURCE_PAGE_SIZE) });
    if (cursor !== null) params.set("cursor", cursor);
    return {
      state: "ready",
      page: decodeIpSourcePage(
        await get(`/api/ip/portfolio?${params}`, signal),
        cursor,
      ),
    };
  };
  const contracts = async (
    cursor: string | null = null,
    signal?: AbortSignal,
  ): Promise<ContractSourcePage> => {
    if (cursor !== null) identityCursor(cursor);
    const params = new URLSearchParams({ limit: String(SOURCE_PAGE_SIZE) });
    if (cursor !== null) params.set("cursor", cursor);
    return decodeContractSourcePage(
      await get(`/api/contracts/?${params}`, signal),
      companyId,
      cursor,
    );
  };
  return {
    companyId,
    obligations: createContractObligationsRepository(request, companyId).load,
    // No role/creator-capability guesses and no billing read with side effects.
    availability: async (
      signal?: AbortSignal,
    ): Promise<SourceModuleAvailability> => ({
      // Contract reads are authorized by CurrentContext, not creator roles or
      // a guessed billing entitlement. Each actual request can still refuse.
      contract: { state: "available" },
      ip_docket: await ipAvailability(signal),
    }),
    ipPage,
    // Existing read routes retain their server-owned authorization.
    contracts,
    detail: async (
      source: SourceRef,
      locator?: SourceLocator,
      signal?: AbortSignal,
    ): Promise<SourceDetail> => {
      const ref = decodeSourceRef(source);
      if (locator) {
        if (locator.kind !== ref.kind)
          throw new ContractError("cross-type source locator");
        continuation(locator.cursor);
      }
      if (ref.kind === "contract") {
        if (
          locator &&
          (locator.kind !== "contract" ||
            identity(locator.contractId) !== ref.id)
        )
          throw new ContractError("contract locator identity");
        return {
          state: "ready",
          record: decodeContractSource(
            await get(`/api/contracts/${encodeURIComponent(ref.id)}`, signal),
            companyId,
            ref.id,
          ),
        };
      }
      if (!locator) {
        const gate = await ipAvailability(signal);
        if (gate.state !== "available") return gate;
        return {
          state: "ready",
          record: decodeIpDocketSource(
            await get(
              `/api/ip/dockets/${encodeURIComponent(ref.id)}/summary`,
              signal,
            ),
            companyId,
            ref.id,
          ),
        };
      }
      if (locator.kind !== "ip_docket")
        throw new ContractError("cross-type source locator");
      if (identity(locator.docketId) !== ref.id)
        throw new ContractError("IP locator docket identity");
      identity(locator.applicationId);
      const result = await ipPage(locator.cursor, signal);
      if (result.state !== "ready") return result;
      const record = result.page.rows.find(
        (item) =>
          item.id === ref.id && item.application_id === locator.applicationId,
      );
      return record ? { state: "ready", record } : { ...SOURCE_GAPS.ipMoved };
    },
  };
}
export type SourceRecordsRepository = ReturnType<
  typeof createSourceRecordsRepository
>;
