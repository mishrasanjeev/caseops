/**
 * Registry reconciliation helpers (BUG-012, Ram 2026-10-30).
 *
 * A registry identity attaches to exactly one legal record of the selected
 * docket: a national trademark application or an IP proceeding. These
 * helpers turn the docket's core records into choices a lawyer can tell
 * apart (with the numbers the records already carry), and turn the
 * structured "what the register shows" form into the evidence documents the
 * manual snapshot API stores, in the same shape as the accepted state so an
 * unchanged field never shows up as a change.
 */
import type { IpCoreRecords, IpFeatureReadiness, IpIdentifier } from "@/lib/api/endpoints";

export type RegistryIdentifierKind = IpIdentifier["identifier_kind"];

export const IDENTIFIER_KIND_LABELS: Record<RegistryIdentifierKind, string> = {
  application: "Application number",
  registration: "Registration number",
  opposition: "Opposition number",
  rectification: "Rectification number",
  cancellation: "Cancellation number",
  non_use_removal: "Non-use removal number",
  appeal: "Appeal number",
  court: "Court case number",
};

/** Docket record types a registry identity can attach to (national marks). */
export const REGISTRY_DOCKET_RECORD_TYPES = ["trademark"] as const;

const MADRID_RECORD_TYPES = new Set(["international_registration", "international_designation"]);

export function isMadridRecordType(recordType: string | null | undefined): boolean {
  return MADRID_RECORD_TYPES.has(recordType ?? "");
}

export type RegistryTarget = {
  /** `application:<id>` or `proceeding:<id>`. */
  value: string;
  kind: "application" | "proceeding";
  id: string;
  label: string;
  identifierKinds: RegistryIdentifierKind[];
  identifierKind: RegistryIdentifierKind;
  /** The record's current number, or "" while the office has not allotted one. */
  identifier: string;
  office: string;
  jurisdiction: string;
};

function humanize(value: string): string {
  const text = value.replaceAll("_", " ").trim();
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : text;
}

const OPENED = new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", year: "numeric" });

/** Every legal record of one docket that a registry identity can attach to. */
export function registryTargets(records: IpCoreRecords): RegistryTarget[] {
  const active = records.identifiers.filter((row) => row.effective_until === null);
  const byPrimary = (rows: IpIdentifier[]) =>
    [...rows].sort((a, b) => Number(b.is_primary) - Number(a.is_primary));
  const targets: Array<RegistryTarget & { opened: string }> = [];

  for (const application of records.applications) {
    const own = byPrimary(active.filter(
      (row) => row.application_id === application.id && !row.proceeding_id,
    ));
    const applicationNumber = own.find((row) => row.identifier_kind === "application");
    const registrationNumber = own.find((row) => row.identifier_kind === "registration");
    const prefill = applicationNumber ?? registrationNumber;
    targets.push({
      value: `application:${application.id}`,
      kind: "application",
      id: application.id,
      label: [
        `Application ${applicationNumber?.raw_value ?? "number pending"}`,
        registrationNumber ? `Registration ${registrationNumber.raw_value}` : null,
        application.office,
        application.jurisdiction,
        humanize(application.filing_phase),
      ].filter(Boolean).join(" · "),
      identifierKinds: ["application", "registration"],
      identifierKind: prefill?.identifier_kind ?? "application",
      identifier: prefill?.raw_value ?? "",
      office: application.office,
      jurisdiction: application.jurisdiction,
      opened: application.created_at,
    });
  }

  for (const proceeding of records.proceedings) {
    const own = byPrimary(active.filter((row) => row.proceeding_id === proceeding.id));
    const number = own.find((row) => row.identifier_kind === proceeding.proceeding_kind) ?? own[0];
    const kinds: RegistryIdentifierKind[] = [proceeding.proceeding_kind];
    if (number && !kinds.includes(number.identifier_kind)) kinds.push(number.identifier_kind);
    targets.push({
      value: `proceeding:${proceeding.id}`,
      kind: "proceeding",
      id: proceeding.id,
      label: [
        `${humanize(proceeding.proceeding_kind)} ${number?.raw_value ?? "number pending"}`,
        `${proceeding.side} side`,
        proceeding.office,
        humanize(proceeding.stage),
      ].join(" · "),
      identifierKinds: kinds,
      identifierKind: number?.identifier_kind ?? proceeding.proceeding_kind,
      identifier: number?.raw_value ?? "",
      office: proceeding.office,
      jurisdiction: proceeding.jurisdiction,
      opened: proceeding.created_at,
    });
  }

  // Two records can still read alike (two oppositions awaiting numbers):
  // add the opening date, then an ordinal, so no two choices look the same.
  const seen = new Map<string, number>();
  const counts = new Map<string, number>();
  for (const target of targets) counts.set(target.label, (counts.get(target.label) ?? 0) + 1);
  return targets.map(({ opened, ...target }) => {
    if ((counts.get(target.label) ?? 0) < 2) return target;
    const dated = `${target.label} · opened ${OPENED.format(new Date(opened))}`;
    const index = (seen.get(dated) ?? 0) + 1;
    seen.set(dated, index);
    return { ...target, label: index > 1 ? `${dated} (${index})` : dated };
  });
}

/**
 * One sentence for the automated registry-sync gate. The manual path below it
 * never depends on this feature, so the sentence only explains, it never blocks.
 */
export function registrySyncSentence(feature: Pick<IpFeatureReadiness, "reason"> | undefined): string | null {
  switch (feature?.reason) {
    case undefined:
    case "unknown_feature":
      return null;
    case "available":
      return "Automated registry sync is enabled for this workspace; entries made here are still manual evidence.";
    case "rollout_disabled":
    case "rollout_expired":
    case "incident_kill_switch":
      return "Automated registry sync is paused by CaseOps.";
    case "missing_entitlement":
      return "Automated registry sync is not in your plan.";
    case "missing_capability":
      return "Your role cannot run automated registry sync.";
    case "workspace_not_configured":
    case "tenant_disabled":
    case "readiness_test_failed":
      return "Automated registry sync needs setup by an IP workspace admin.";
  }
}

// ---------------------------------------------------------------------------
// Structured register evidence
// ---------------------------------------------------------------------------

type Json = null | boolean | number | string | Json[] | { [key: string]: Json };

export type RegisterParty = { name: string; role: string };

export type RegisterFieldDefinition = {
  path: string;
  label: string;
  input: "text" | "date";
};

/** Optional details a lawyer reads off the register, always offered. */
export const OPTIONAL_REGISTER_FIELDS: readonly RegisterFieldDefinition[] = [
  { path: "/mark_name", label: "Mark as shown on the register", input: "text" },
  { path: "/registration_date", label: "Registration date", input: "date" },
  { path: "/renewal_date", label: "Renewal due date", input: "date" },
  { path: "/journal_number", label: "Trade Marks Journal number", input: "text" },
  { path: "/publication_date", label: "Journal publication date", input: "date" },
  { path: "/hearing_date", label: "Next hearing date", input: "date" },
];

const CORE_LABELS: Record<string, string> = {
  "/status": "Status on the register",
  "/office": "Office on the register",
  "/jurisdiction": "Jurisdiction on the register",
};

const escapeSegment = (value: string) => value.replace(/~/g, "~0").replace(/\//g, "~1");
const unescapeSegment = (value: string) => value.replace(/~1/g, "/").replace(/~0/g, "~");

/** Mirrors the API's diff flattening: objects recurse, everything else is a leaf. */
export function flattenRegisterState(value: unknown, path = ""): Map<string, unknown> {
  const leaves = new Map<string, unknown>();
  if (value && typeof value === "object" && !Array.isArray(value)) {
    const entries = Object.keys(value as Record<string, unknown>).sort();
    if (entries.length === 0) {
      leaves.set(path || "/", {});
      return leaves;
    }
    for (const key of entries) {
      for (const [child, leaf] of flattenRegisterState(
        (value as Record<string, unknown>)[key], `${path}/${escapeSegment(key)}`,
      )) leaves.set(child, leaf);
    }
    return leaves;
  }
  leaves.set(path || "/", value);
  return leaves;
}

export function unflattenRegisterState(leaves: Map<string, unknown>): Record<string, Json> {
  const root: Record<string, Json> = {};
  for (const [path, value] of leaves) {
    const segments = path.split("/").slice(1).map(unescapeSegment);
    if (segments.length === 0 || (segments.length === 1 && segments[0] === "")) continue;
    let cursor: Record<string, Json> = root;
    for (const segment of segments.slice(0, -1)) {
      const next = cursor[segment];
      if (!next || typeof next !== "object" || Array.isArray(next)) cursor[segment] = {};
      cursor = cursor[segment] as Record<string, Json>;
    }
    cursor[segments[segments.length - 1]] = value as Json;
  }
  return root;
}

export function registerFieldLabel(path: string): string {
  if (CORE_LABELS[path]) return CORE_LABELS[path];
  const optional = OPTIONAL_REGISTER_FIELDS.find((field) => field.path === path);
  if (optional) return optional.label;
  const segments = path.split("/").slice(1).map(unescapeSegment);
  if (segments.length === 2 && segments[0] === "identifiers") {
    return IDENTIFIER_KIND_LABELS[segments[1] as RegistryIdentifierKind] ?? `${humanize(segments[1])} number`;
  }
  return segments.map(humanize).join(" › ");
}

const isScalar = (value: unknown) =>
  value === null || ["string", "number", "boolean"].includes(typeof value);

function isPartyList(value: unknown): value is RegisterParty[] {
  return Array.isArray(value) && value.every((row) =>
    row && typeof row === "object" && !Array.isArray(row)
    && typeof (row as RegisterParty).name === "string" && typeof (row as RegisterParty).role === "string"
    && Object.keys(row).every((key) => key === "name" || key === "role"));
}

export type RegisterForm = {
  /** Editable single-value fields, in display order. */
  fields: Array<RegisterFieldDefinition & { value: string; original: unknown }>;
  /** Parties as recorded, edited row by row; null when the state has none. */
  parties: RegisterParty[] | null;
  /** Values the form cannot edit; they are carried over unchanged. */
  carried: Map<string, unknown>;
};

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

/** Prefill the structured form from the identity's accepted legal state. */
export function registerFormFromState(state: Record<string, unknown>): RegisterForm {
  const leaves = flattenRegisterState(state ?? {});
  const fields: RegisterForm["fields"] = [];
  const carried = new Map<string, unknown>();
  let parties: RegisterParty[] | null = null;
  const order = (path: string) => {
    const core = Object.keys(CORE_LABELS).indexOf(path);
    if (core >= 0) return core;
    if (path.startsWith("/identifiers/")) return 10;
    const optional = OPTIONAL_REGISTER_FIELDS.findIndex((field) => field.path === path);
    return optional >= 0 ? 20 + optional : 50;
  };
  for (const [path, value] of leaves) {
    if (path === "/parties" && isPartyList(value)) {
      parties = value.map((row) => ({ ...row }));
    } else if (path !== "/" && isScalar(value)) {
      const text = value === null ? "" : String(value);
      const known = OPTIONAL_REGISTER_FIELDS.find((field) => field.path === path);
      fields.push({
        path,
        label: registerFieldLabel(path),
        input: known?.input === "date" && (text === "" || ISO_DATE.test(text)) ? "date" : "text",
        value: text,
        original: value,
      });
    } else {
      carried.set(path, value);
    }
  }
  for (const optional of OPTIONAL_REGISTER_FIELDS) {
    if (!leaves.has(optional.path)) fields.push({ ...optional, value: "", original: undefined });
  }
  fields.sort((a, b) => order(a.path) - order(b.path) || a.path.localeCompare(b.path));
  return { fields, parties, carried };
}

function typedValue(text: string, original: unknown): Json {
  const trimmed = text.trim();
  if (typeof original === "number" && trimmed !== "" && Number.isFinite(Number(trimmed))) return Number(trimmed);
  if (typeof original === "boolean" && (trimmed === "true" || trimmed === "false")) return trimmed === "true";
  return trimmed;
}

/**
 * The normalized register record: the same shape as the accepted state, with
 * the lawyer's values. A value left as prefilled is sent exactly as accepted
 * (so it is never a change); a field the lawyer clears is left out, which the
 * review queue then shows as removed from the register.
 */
export function normalizedRegisterRecord(form: RegisterForm, values: Record<string, string>, parties: RegisterParty[] | null) {
  const leaves = new Map(form.carried);
  for (const field of form.fields) {
    const text = values[field.path] ?? field.value;
    if (text === field.value && field.original !== undefined) {
      leaves.set(field.path, field.original);
      continue;
    }
    if (text.trim() === "") continue;
    leaves.set(field.path, typedValue(text, field.original));
  }
  if (form.parties && parties) {
    const untouched = JSON.stringify(parties) === JSON.stringify(form.parties);
    // Kept even when empty, so an unchanged empty list is not a change.
    leaves.set("/parties", untouched ? form.parties : parties
      .map((row) => ({ name: row.name.trim(), role: row.role.trim() }))
      .filter((row) => row.name || row.role));
  }
  return unflattenRegisterState(leaves);
}
