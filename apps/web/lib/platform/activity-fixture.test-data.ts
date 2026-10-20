import type { ActivityReport } from "./activity-schema";

const metrics = {
  users_added: 1, matters_created: 2, tasks_created: 3, tasks_completed: 1, hearings_created: 1,
  documents_uploaded: 4, notices_received: 1, notices_sent: 1, time_entries: 2, billable_hours: 1.5,
  invoices_issued: 1, invoiced_amount_minor: 12000, payments_received: 1, collections_minor: 5000,
  audit_events: 5, failed_or_denied_events: 1,
};
const current = {
  active_users: 2, active_matters: 3, open_tasks: 4, overdue_tasks: 1, upcoming_hearings_30d: 2,
  documents_total: 7, storage_bytes: 1024, open_notices: 1, overdue_notice_replies: 0,
  open_invoices: 1, outstanding_amount_minor: 7000,
};
const periods = { day: { ...metrics }, week: { ...metrics, documents_uploaded: 8 }, month: { ...metrics, documents_uploaded: 12 }, till_date: { ...metrics, documents_uploaded: 24 } };
function segment(company_id: string, name: string, company_type: string, usage_status: "recent" | "inactive" | "unknown", last: string | null) {
  return { company_count: 1, company_names: [name], periods: structuredClone(periods), accounts: [{
    company_id, name, company_type, is_active: company_type !== "law_firm", usage_status,
    last_meaningful_activity_at: last, current: { ...current }, periods: structuredClone(periods),
  }] };
}

// Complete canonical response shape, not a production account inventory.
export function activityFixture(): ActivityReport {
  return {
    generated_at: "2026-10-20T07:30:00+05:30", account_scope: "all_registered_accounts", excluded_account_count: 0,
    activity_window: { days: 30, cutoff: "2026-09-20T07:30:00+05:30", as_of: "2026-10-20T07:30:00+05:30", time_zone: "Asia/Kolkata", basis: "successful_human_audit_events", limitations: "Successful human audit events only. Missing or future-only evidence remains unknown." },
    reporting_periods: { day: { start_date: "2026-10-19", end_date: "2026-10-19" }, week: { start_date: "2026-10-12", end_date: "2026-10-18" }, month: { start_date: "2026-09-01", end_date: "2026-09-30" }, till_date: { start_date: null, end_date: "2026-10-20" } },
    segments: {
      law_firms: segment("company-law", "Test-legal law firm", "law_firm", "recent", "2026-10-20T07:00:00+05:30"),
      general_counsels: segment("company-corp", "Corporate unknown evidence", "corporate_legal", "unknown", null),
      solo_lawyers: segment("company-solo", "Dormant solo advocate", "solo", "inactive", "2026-09-19T07:00:00+05:30"),
      other: segment("company-other", "Unknown-category account", "unrecognized_source_value", "unknown", null),
    },
  };
}
