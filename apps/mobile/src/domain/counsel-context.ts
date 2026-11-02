import { array, ContractError, dateOnly, object, string } from "./contracts.ts";
import type { AuthorizedRequest } from "./repository.ts";

export const COUNSEL_PAGE_LIMITS = Object.freeze({
  assignments: 10,
  spend: 25,
});
export const COUNSEL_PAGE_HISTORY = 25;
export type CounselCursors = Readonly<{
  assignment: string | null;
  spend: string | null;
}>;
type SharedRecord = {
  id: string;
  company_id: string;
  matter_id: string;
  matter_title: string;
  matter_code: string;
  counsel_id: string;
  counsel_name: string;
  currency: string;
  created_at: string;
  updated_at: string;
};
export type CounselAssignment = SharedRecord & {
  assigned_by_membership_id: string | null;
  assigned_by_name: string | null;
  role_summary: string | null;
  budget_amount_minor: number | null;
  fee_agreed_minor: number | null;
  status: "proposed" | "approved" | "active" | "closed";
  internal_notes: string | null;
};
export type CounselSpend = SharedRecord & {
  assignment_id: string | null;
  recorded_by_membership_id: string | null;
  recorded_by_name: string | null;
  invoice_reference: string | null;
  stage_label: string | null;
  description: string;
  amount_minor: number;
  approved_amount_minor: number;
  paid_amount_minor: number;
  pending_amount_minor: number;
  status: "submitted" | "approved" | "partially_approved" | "disputed" | "paid";
  payment_status: CounselSpend["status"];
  payment_tracking_status: "unpaid" | "partially_paid" | "paid";
  billed_on: string | null;
  due_on: string | null;
  paid_on: string | null;
  notes: string | null;
};
export type CounselCurrencyPage = {
  currency: string;
  recorded_budget_minor: number;
  unpriced_assignment_count: number;
  amount_minor: number;
  approved_amount_minor: number;
  paid_amount_minor: number;
  pending_amount_minor: number;
};
export type CounselContext = {
  matter_id: string;
  matter_title: string;
  matter_code: string;
  matter_status: string;
  matter_is_active: boolean;
  lifecycle_version: number;
  totals_scope: "page";
  assignments: CounselAssignment[];
  spend_records: CounselSpend[];
  assignment_limit: number;
  spend_limit: number;
  assignment_next_after: string | null;
  spend_next_after: string | null;
  currencies: CounselCurrencyPage[];
};
const uuid = (value: unknown, label = "counsel identity") => {
  const result = string(value, label, 36);
  if (!/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(result))
    throw new ContractError(label);
  return result;
};
const nullable = (value: unknown, label: string, max = 4000) =>
  value === null ? null : string(value, label, max);
const nullableId = (value: unknown) => (value === null ? null : uuid(value));
function units(value: unknown): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0)
    throw new ContractError("recorded minor units");
  return value;
}
function currency(value: unknown): string {
  const result = string(value, "recorded currency", 8);
  if (!result.trim() || /[\x00-\x1f\x7f]/.test(result))
    throw new ContractError("recorded currency");
  return result;
}
function aware(value: unknown): string {
  const result = string(value, "counsel timestamp", 64);
  const match =
    /^(\d{4}-\d{2}-\d{2})T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d{1,6})?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$/.exec(
      result,
    );
  if (!match || !Number.isFinite(Date.parse(result)))
    throw new ContractError("counsel timestamp");
  dateOnly(match[1]);
  return result;
}
function legalDate(value: unknown): string | null {
  return value === null ? null : dateOnly(value);
}
function choice<T extends string>(
  value: unknown,
  allowed: readonly T[],
  label: string,
): T {
  if (typeof value !== "string" || !allowed.includes(value as T))
    throw new ContractError(label);
  return value as T;
}
function shared(
  row: Record<string, unknown>,
  companyId: string,
  matterId: string,
): SharedRecord {
  if (row.company_id !== companyId || row.matter_id !== matterId)
    throw new ContractError("counsel target scope");
  return {
    id: uuid(row.id),
    company_id: companyId,
    matter_id: matterId,
    matter_title: string(row.matter_title, "Matter title", 255),
    matter_code: string(row.matter_code, "Matter code", 100),
    counsel_id: uuid(row.counsel_id),
    counsel_name: string(row.counsel_name, "counsel name", 255),
    currency: currency(row.currency),
    created_at: aware(row.created_at),
    updated_at: aware(row.updated_at),
  };
}
const spendStates = [
  "submitted",
  "approved",
  "partially_approved",
  "disputed",
  "paid",
] as const;
function assignment(
  value: unknown,
  company: string,
  matter: string,
): CounselAssignment {
  const row = object(value, "counsel assignment");
  return {
    ...shared(row, company, matter),
    assigned_by_membership_id: nullableId(row.assigned_by_membership_id),
    assigned_by_name: nullable(row.assigned_by_name, "recorded assigner", 255),
    role_summary: nullable(row.role_summary, "counsel role", 255),
    budget_amount_minor:
      row.budget_amount_minor === null ? null : units(row.budget_amount_minor),
    fee_agreed_minor:
      row.fee_agreed_minor === null ? null : units(row.fee_agreed_minor),
    status: choice(
      row.status,
      ["proposed", "approved", "active", "closed"],
      "assignment status",
    ),
    internal_notes: nullable(row.internal_notes, "assignment notes"),
  };
}
function spend(value: unknown, company: string, matter: string): CounselSpend {
  const row = object(value, "counsel spend");
  return {
    ...shared(row, company, matter),
    assignment_id: nullableId(row.assignment_id),
    recorded_by_membership_id: nullableId(row.recorded_by_membership_id),
    recorded_by_name: nullable(row.recorded_by_name, "recorded author", 255),
    invoice_reference: nullable(
      row.invoice_reference,
      "invoice reference",
      120,
    ),
    stage_label: nullable(row.stage_label, "spend stage", 120),
    description: string(row.description, "spend description", 500),
    amount_minor: units(row.amount_minor),
    approved_amount_minor: units(row.approved_amount_minor),
    paid_amount_minor: units(row.paid_amount_minor),
    pending_amount_minor: units(row.pending_amount_minor),
    status: choice(row.status, spendStates, "spend status"),
    payment_status: choice(
      row.payment_status,
      spendStates,
      "reported payment status",
    ),
    payment_tracking_status: choice(
      row.payment_tracking_status,
      ["unpaid", "partially_paid", "paid"],
      "payment tracking status",
    ),
    billed_on: legalDate(row.billed_on),
    due_on: legalDate(row.due_on),
    paid_on: legalDate(row.paid_on),
    notes: nullable(row.notes, "spend notes"),
  };
}
function next(
  value: unknown,
  rows: { id: string }[],
  limit: number,
  previous: string | null,
): string | null {
  if (value === null) return null;
  const result = uuid(value, "counsel continuation");
  if (
    rows.length !== limit ||
    result !== rows.at(-1)?.id ||
    result === previous
  )
    throw new ContractError("counsel continuation");
  return result;
}
export function decodeCounselContext(
  value: unknown,
  companyId: string,
  matterId: string,
  after: CounselCursors,
): CounselContext {
  uuid(companyId);
  uuid(matterId);
  const row = object(value, "Matter counsel context");
  if (
    row.matter_id !== matterId ||
    row.totals_scope !== "page" ||
    typeof row.matter_is_active !== "boolean" ||
    row.assignment_limit !== COUNSEL_PAGE_LIMITS.assignments ||
    row.spend_limit !== COUNSEL_PAGE_LIMITS.spend
  )
    throw new ContractError("Matter counsel context scope");
  const assignments = array(
    row.assignments,
    "counsel assignment page",
    (item) => assignment(item, companyId, matterId),
    COUNSEL_PAGE_LIMITS.assignments,
  );
  const spending = array(
    row.spend_records,
    "counsel spend page",
    (item) => spend(item, companyId, matterId),
    COUNSEL_PAGE_LIMITS.spend,
  );
  for (const rows of [assignments, spending])
    if (new Set(rows.map((item) => item.id)).size !== rows.length)
      throw new ContractError("duplicate counsel record");
  const totals = new Map<string, CounselCurrencyPage>();
  const group = (code: string) => {
    if (!totals.has(code))
      totals.set(code, {
        currency: code,
        recorded_budget_minor: 0,
        unpriced_assignment_count: 0,
        amount_minor: 0,
        approved_amount_minor: 0,
        paid_amount_minor: 0,
        pending_amount_minor: 0,
      });
    return totals.get(code)!;
  };
  for (const record of assignments) {
    const total = group(record.currency);
    if (record.budget_amount_minor === null) total.unpriced_assignment_count++;
    else
      total.recorded_budget_minor = units(
        total.recorded_budget_minor + record.budget_amount_minor,
      );
  }
  for (const record of spending) {
    const total = group(record.currency);
    for (const key of [
      "amount_minor",
      "approved_amount_minor",
      "paid_amount_minor",
      "pending_amount_minor",
    ] as const)
      total[key] = units(total[key] + record[key]);
  }
  const currencies = array(
    row.currencies,
    "page currency totals",
    (item) => {
      const itemRow = object(item, "page currency total");
      const result: CounselCurrencyPage = {
        currency: currency(itemRow.currency),
        recorded_budget_minor: units(itemRow.recorded_budget_minor),
        unpriced_assignment_count: units(itemRow.unpriced_assignment_count),
        amount_minor: units(itemRow.amount_minor),
        approved_amount_minor: units(itemRow.approved_amount_minor),
        paid_amount_minor: units(itemRow.paid_amount_minor),
        pending_amount_minor: units(itemRow.pending_amount_minor),
      };
      if (
        !totals.has(result.currency) ||
        JSON.stringify(result) !== JSON.stringify(totals.get(result.currency))
      )
        throw new ContractError("page currency total mismatch");
      return result;
    },
    COUNSEL_PAGE_LIMITS.assignments + COUNSEL_PAGE_LIMITS.spend,
  );
  if (
    currencies.length !== totals.size ||
    new Set(currencies.map((item) => item.currency)).size !== currencies.length
  )
    throw new ContractError("complete page currency totals");
  return {
    matter_id: matterId,
    matter_title: string(row.matter_title, "Matter title", 255),
    matter_code: string(row.matter_code, "Matter code", 100),
    matter_status: string(row.matter_status, "Matter status", 80),
    matter_is_active: row.matter_is_active,
    lifecycle_version: units(row.lifecycle_version),
    totals_scope: "page",
    assignments,
    spend_records: spending,
    assignment_limit: COUNSEL_PAGE_LIMITS.assignments,
    spend_limit: COUNSEL_PAGE_LIMITS.spend,
    assignment_next_after: next(
      row.assignment_next_after,
      assignments,
      COUNSEL_PAGE_LIMITS.assignments,
      after.assignment,
    ),
    spend_next_after: next(
      row.spend_next_after,
      spending,
      COUNSEL_PAGE_LIMITS.spend,
      after.spend,
    ),
    currencies,
  };
}
export function formatCounselMoney(
  code: string,
  amount: number | null,
): string {
  currency(code);
  if (amount === null) return "Not recorded";
  units(amount);
  if (code !== "INR")
    return `${code} ${amount} minor ${amount === 1 ? "unit" : "units"}`;
  const digits = String(amount).padStart(3, "0");
  return `INR ${digits.slice(0, -2)}.${digits.slice(-2)} (${amount} ${amount === 1 ? "paisa" : "paise"})`;
}
export function advanceCounselPage(
  history: readonly (string | null)[],
  cursor: string | null,
): (string | null)[] {
  if (
    history[0] !== null ||
    history.length >= COUNSEL_PAGE_HISTORY ||
    cursor === null ||
    history.includes(cursor)
  )
    throw new ContractError("counsel page navigation");
  uuid(cursor, "counsel continuation");
  return [...history, cursor];
}
export function createCounselContextRepository(
  request: AuthorizedRequest,
  companyId: string,
) {
  uuid(companyId);
  return {
    async load(
      matterId: string,
      after: CounselCursors,
      signal?: AbortSignal,
    ): Promise<CounselContext> {
      uuid(matterId);
      for (const cursor of Object.values(after))
        if (cursor !== null) uuid(cursor, "counsel continuation");
      const query = new URLSearchParams({
        assignment_limit: String(COUNSEL_PAGE_LIMITS.assignments),
        spend_limit: String(COUNSEL_PAGE_LIMITS.spend),
      });
      if (after.assignment !== null)
        query.set("assignment_after", after.assignment);
      if (after.spend !== null) query.set("spend_after", after.spend);
      return decodeCounselContext(
        await request(
          `/api/outside-counsel/matters/${encodeURIComponent(matterId)}/context?${query}`,
          { method: "GET", signal },
        ),
        companyId,
        matterId,
        after,
      );
    },
  };
}
export function createCounselPageLease() {
  let active = true,
    current: Readonly<{ key: string; data: unknown }> | null = null;
  return {
    bind(key: string, data: unknown) {
      if (!active) return Object.freeze({ key, data: null });
      if (!current || current.key !== key || current.data !== data)
        current = Object.freeze({ key, data });
      return current;
    },
    navigate(
      frame: Readonly<{ key: string; data: unknown }>,
      action: () => void,
      requireReady = true,
    ) {
      if (!active || frame !== current || (requireReady && frame.data === null))
        return false;
      current = null;
      action();
      return true;
    },
    isActive: () => active,
    dispose() {
      active = false;
      current = null;
    },
  };
}
