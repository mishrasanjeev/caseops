import { z } from "zod";

const integer = z.number().int().safe();
export const activityMetrics = z.object({
  users_added: integer, matters_created: integer, tasks_created: integer, tasks_completed: integer,
  hearings_created: integer, documents_uploaded: integer, notices_received: integer, notices_sent: integer,
  time_entries: integer, billable_hours: z.number().finite(), invoices_issued: integer,
  invoiced_amount_minor: integer, payments_received: integer, collections_minor: integer,
  audit_events: integer, failed_or_denied_events: integer,
}).strict();
export const activitySnapshot = z.object({
  active_users: integer, active_matters: integer, open_tasks: integer, overdue_tasks: integer,
  upcoming_hearings_30d: integer, documents_total: integer, storage_bytes: integer, open_notices: integer,
  overdue_notice_replies: integer, open_invoices: integer, outstanding_amount_minor: integer,
}).strict();
export const activityPeriods = z.object({ day: activityMetrics, week: activityMetrics, month: activityMetrics, till_date: activityMetrics }).strict();
export const activityAccount = z.object({
  company_id: z.string().min(1).max(36), name: z.string(), company_type: z.string(), is_active: z.boolean(),
  last_meaningful_activity_at: z.string().datetime({ offset: true }).nullable(),
  usage_status: z.enum(["recent", "inactive", "unknown"]), current: activitySnapshot, periods: activityPeriods,
}).strict().refine((account) => account.usage_status === "unknown" || account.last_meaningful_activity_at !== null,
  { message: "Known engagement requires timestamp evidence.", path: ["last_meaningful_activity_at"] });
const segment = z.object({ company_count: integer.nonnegative(), company_names: z.array(z.string()), periods: activityPeriods, accounts: z.array(activityAccount) }).strict();
const bounds = z.object({ start_date: z.string().date().nullable(), end_date: z.string().date() }).strict();
export const activityReport = z.object({
  generated_at: z.string().datetime({ offset: true }), account_scope: z.enum(["all_registered_accounts", "operational_email"]),
  excluded_account_count: integer.nonnegative(),
  activity_window: z.object({ days: z.literal(30), cutoff: z.string().datetime({ offset: true }),
    as_of: z.string().datetime({ offset: true }), time_zone: z.literal("Asia/Kolkata"),
    basis: z.literal("successful_human_audit_events"), limitations: z.string() }).strict(),
  reporting_periods: z.object({ day: bounds, week: bounds, month: bounds, till_date: bounds }).strict(),
  segments: z.object({ law_firms: segment, general_counsels: segment, solo_lawyers: segment, other: segment }).strict(),
}).strict().superRefine((report, context) => {
  const ids = new Set<string>();
  const cutoff = Date.parse(report.activity_window.cutoff);
  const asOf = Date.parse(report.activity_window.as_of);
  if (asOf - cutoff !== 30 * 24 * 60 * 60 * 1000) {
    context.addIssue({ code: "custom", message: "Activity window is not 30 elapsed days.", path: ["activity_window"] });
  }
  if (Date.parse(report.generated_at) !== asOf) {
    context.addIssue({ code: "custom", message: "Activity window must end at report generation.", path: ["activity_window", "as_of"] });
  }
  if (report.account_scope === "all_registered_accounts" && report.excluded_account_count !== 0) {
    context.addIssue({ code: "custom", message: "All-account scope cannot exclude registered accounts.", path: ["excluded_account_count"] });
  }
  for (const [name, bounds] of Object.entries(report.reporting_periods)) {
    if (bounds.start_date !== null && bounds.start_date > bounds.end_date) {
      context.addIssue({ code: "custom", message: "Reporting period is reversed.", path: ["reporting_periods", name] });
    }
  }
  for (const [name, item] of Object.entries(report.segments)) {
    if (item.company_count !== item.accounts.length || item.company_names.length !== item.accounts.length ||
        JSON.stringify([...item.company_names].sort()) !== JSON.stringify(item.accounts.map((account) => account.name).sort())) {
      context.addIssue({ code: "custom", message: "Account inventory does not reconcile.", path: ["segments", name] });
    }
    for (const account of item.accounts) {
      if (ids.has(account.company_id)) context.addIssue({ code: "custom", message: "Duplicate account identity.", path: ["segments", name, "accounts"] });
      ids.add(account.company_id);
      if (account.last_meaningful_activity_at !== null) {
        const last = Date.parse(account.last_meaningful_activity_at);
        if (last > asOf || (account.usage_status === "recent" && last < cutoff) ||
            (account.usage_status === "inactive" && last >= cutoff)) {
          context.addIssue({ code: "custom", message: "Engagement classification contradicts timestamp evidence.", path: ["segments", name, "accounts"] });
        }
      }
    }
  }
});
export type ActivityReport = z.infer<typeof activityReport>;
export type ActivityAccount = z.infer<typeof activityAccount>;
export type ActivityPeriod = keyof z.infer<typeof activityPeriods>;
