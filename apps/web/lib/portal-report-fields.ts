/**
 * What a client sees of a published IP report: an explicit allowlist per
 * report kind, with each value in words.
 *
 * Published rows also carry `docket_id` (the server uses it to scope rows to
 * the client's grants), and the summary carries the stored `report_kind`
 * code. Rendering every key printed "Docket id: <uuid>" and
 * "portfolio_register" to the client (B4-ADJ-02). Only the fields below are
 * shown; anything the server adds later stays hidden until it is listed here.
 */
import { displayValue, fieldLabel, readableCode } from "@/lib/display-value";

type FieldKind = "text" | "code" | "list" | "count" | "date" | "datetime";
type PortalField = { key: string; label: string; kind: FieldKind };

const PORTFOLIO_FIELDS: readonly PortalField[] = [
  { key: "docket_title", label: "Record", kind: "text" },
  { key: "asset_title", label: "Mark", kind: "text" },
  { key: "primary_identifier", label: "Primary number", kind: "text" },
  { key: "docket_status", label: "Status", kind: "code" },
  { key: "application_numbers", label: "Application numbers", kind: "list" },
  { key: "opposition_numbers", label: "Opposition numbers", kind: "list" },
  { key: "nice_classes", label: "Classes", kind: "list" },
  { key: "goods_services", label: "Goods and services", kind: "list" },
  { key: "office", label: "Office", kind: "text" },
  { key: "jurisdiction", label: "Jurisdiction", kind: "text" },
  { key: "filing_phase", label: "Filing stage", kind: "code" },
  { key: "open_deadline_count", label: "Open deadlines", kind: "count" },
  { key: "overdue_deadline_count", label: "Overdue deadlines", kind: "count" },
  { key: "registry_sync_state", label: "Registry check", kind: "code" },
  { key: "registry_last_success_at", label: "Registry last checked", kind: "datetime" },
  { key: "updated_at", label: "Last updated", kind: "datetime" },
];

const RENEWAL_FIELDS: readonly PortalField[] = [
  { key: "docket_title", label: "Record", kind: "text" },
  { key: "primary_identifier", label: "Primary number", kind: "text" },
  { key: "record_type", label: "Right", kind: "code" },
  { key: "reporting_state", label: "Renewal status", kind: "code" },
  { key: "renewal_due_on", label: "Renewal due", kind: "date" },
  { key: "grace_due_on", label: "Grace period ends", kind: "date" },
  { key: "calendar_phase", label: "Renewal period", kind: "code" },
  { key: "action_required", label: "Next step", kind: "code" },
];

const REPORT_KIND_LABEL: Record<string, string> = {
  portfolio_register: "Portfolio register",
  application_status: "Application status",
  opposition_status: "Opposition status",
  renewal: "Renewal",
};

const CODE_LABEL: Record<string, string> = { none: "No action needed" };

const DATE = new Intl.DateTimeFormat("en-IN", { dateStyle: "medium", timeZone: "UTC" });
const DATE_TIME = new Intl.DateTimeFormat("en-IN", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Kolkata" });

function formatField(field: PortalField, value: unknown): string {
  if (field.kind === "code" && typeof value === "string") return CODE_LABEL[value] ?? fieldLabel(value);
  if ((field.kind === "date" || field.kind === "datetime") && typeof value === "string") {
    const parsed = new Date(field.kind === "date" ? `${value.slice(0, 10)}T00:00:00Z` : value);
    if (!Number.isNaN(parsed.getTime())) return field.kind === "date" ? DATE.format(parsed) : `${DATE_TIME.format(parsed)} IST`;
  }
  return displayValue(value);
}

function present(value: unknown): boolean {
  return value !== null && value !== undefined && value !== "" && !(Array.isArray(value) && value.length === 0);
}

export type PortalEntry = { key: string; label: string; value: string };

/** One published row as labelled values, in a fixed order, internal ids never included. */
export function portalRowEntries(reportKind: string | null | undefined, row: Record<string, unknown>): PortalEntry[] {
  const fields = reportKind === "renewal" ? RENEWAL_FIELDS : PORTFOLIO_FIELDS;
  return fields
    .filter((field) => present(row[field.key]))
    // The mark usually repeats the record title; show it only when it adds something.
    .filter((field) => field.key !== "asset_title" || row.asset_title !== row.docket_title)
    .map((field) => ({ key: field.key, label: field.label, value: formatField(field, row[field.key]) }));
}

/** The publication summary in words: the report it is and how many records it shares. */
export function portalSummaryEntries(summary: Record<string, unknown> | null | undefined): PortalEntry[] {
  if (!summary) return [];
  const entries: PortalEntry[] = [];
  if (typeof summary.report_kind === "string") {
    entries.push({ key: "report_kind", label: "Report", value: REPORT_KIND_LABEL[summary.report_kind] ?? readableCode(summary.report_kind) });
  }
  if (typeof summary.published_record_count === "number") {
    entries.push({ key: "published_record_count", label: "Records shared", value: String(summary.published_record_count) });
  }
  return entries;
}
