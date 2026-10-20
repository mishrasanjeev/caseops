"use client";

import { useCallback, useMemo, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { formatMoneyMinor } from "@/lib/billing-format";
import type { ActivityAccount, ActivityPeriod, ActivityReport } from "@/lib/platform/activity-schema";
import { platformApi } from "@/lib/platform/client";
import { usePlatformLoad } from "@/lib/platform/use-load";

import { PlatformPagination } from "./PlatformPagination";

const categories = { law_firms: "Law firms", general_counsels: "Corporate legal", solo_lawyers: "Solo lawyers", other: "Other / unknown category" };
const periods: Record<ActivityPeriod, string> = { day: "Day", week: "Week", month: "Month", till_date: "All recorded" };
const metricLabels = {
  users_added: "Users added", matters_created: "Matters created", tasks_created: "Tasks created", tasks_completed: "Tasks completed",
  hearings_created: "Hearings added", documents_uploaded: "Documents uploaded", notices_received: "Notices received", notices_sent: "Notices sent",
  time_entries: "Time entries", billable_hours: "Billable hours", invoices_issued: "Invoices issued", invoiced_amount_minor: "Invoiced value",
  payments_received: "Payments received", collections_minor: "Collections", audit_events: "Audited actions", failed_or_denied_events: "Failed / denied actions",
};
const snapshotLabels = { active_users: "Active users", active_matters: "Active matters", open_tasks: "Open tasks", overdue_tasks: "Overdue tasks", upcoming_hearings_30d: "Hearings in next 30 days", documents_total: "Documents", storage_bytes: "Document storage (bytes)", open_notices: "Open notices", overdue_notice_replies: "Overdue notice replies", open_invoices: "Open invoices", outstanding_amount_minor: "Outstanding value" };
const timestamp = (value: string) => new Intl.DateTimeFormat("en-IN", { timeZone: "Asia/Kolkata", dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
const metric = (key: string, value: number) => key.endsWith("_minor") ? formatMoneyMinor(value, "INR", 2) : value.toLocaleString("en-IN", { maximumFractionDigits: 1 });

function AccountGroup({ accounts, period, label }: { accounts: (ActivityAccount & { categoryLabel: string })[]; period: ActivityPeriod; label: string }) {
  const [page, setPage] = useState(0);
  const pageSize = 25;
  const rows = accounts.slice(page * pageSize, (page + 1) * pageSize);
  return <div className="min-w-0 space-y-3">
    <div className="relative min-w-0 overflow-x-auto" tabIndex={0} role="region" aria-label={`${label} accounts`}>
      <table className="w-full min-w-[50rem] text-left text-sm">
        <caption className="sr-only">{label} accounts; {periods[period]} metrics</caption>
        <thead className="border-y border-[var(--color-line)]"><tr>{["Account", "Category", "Account status", "Last human activity (IST)", "Users", "Matters", "Documents", "Details"].map((name) => <th key={name} scope="col" className="p-3">{name}</th>)}</tr></thead>
        <tbody>{rows.map((account) => <tr key={account.company_id} className="border-b border-[var(--color-line)] align-top">
          <td className="max-w-56 break-words p-3">{account.name}</td><td className="p-3">{account.categoryLabel}{account.categoryLabel === categories.other ? <span className="block text-xs">{account.company_type || "Not recorded"}</span> : null}</td>
          <td className="p-3">{account.is_active ? "Enabled" : "Disabled"}</td><td className="p-3">{account.last_meaningful_activity_at ? timestamp(account.last_meaningful_activity_at) : "Not evidenced"}</td>
          <td className="p-3 tabular-nums">{account.current.active_users}</td><td className="p-3 tabular-nums">{account.current.active_matters}</td><td className="p-3 tabular-nums">{account.current.documents_total}</td>
          <td className="min-w-72 p-3"><details><summary className="cursor-pointer font-medium">Activity and current totals</summary>
            <h3 className="mb-3 mt-4 font-bold">{periods[period]}</h3><dl className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-4 gap-y-2">
              {Object.entries(metricLabels).map(([key, title]) => <div className="contents" key={key}><dt>{title}</dt><dd className="text-right tabular-nums">{metric(key, account.periods[period][key as keyof typeof metricLabels])}</dd></div>)}
            </dl><h3 className="mb-3 mt-5 font-bold">Current snapshot</h3><dl className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-4 gap-y-2">
              {Object.entries(snapshotLabels).map(([key, title]) => <div className="contents" key={key}><dt>{title}</dt><dd className="text-right tabular-nums">{metric(key, account.current[key as keyof typeof snapshotLabels])}</dd></div>)}
            </dl>
          </details></td>
        </tr>)}</tbody>
      </table>
    </div>
    <PlatformPagination page={page} pending={false} hasNext={(page + 1) * pageSize < accounts.length} onPrevious={() => setPage((old) => Math.max(0, old - 1))} onNext={() => setPage((old) => old + 1)} />
  </div>;
}

export function ActivityReportView({ report }: { report: ActivityReport }) {
  const [category, setCategory] = useState("all");
  const [search, setSearch] = useState("");
  const [period, setPeriod] = useState<ActivityPeriod>("day");
  const accounts = useMemo(() => Object.entries(report.segments).flatMap(([key, segment]) => segment.accounts.map((account) => ({ ...account, categoryKey: key, categoryLabel: categories[key as keyof typeof categories] }))), [report]);
  const filtered = accounts.filter((account) => (category === "all" || account.categoryKey === category) && account.name.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()));
  const recent = filtered.filter((account) => account.usage_status === "recent");
  const inactive = filtered.filter((account) => account.usage_status === "inactive");
  const unknown = filtered.filter((account) => account.usage_status === "unknown");
  const bounds = report.reporting_periods[period];
  const resetKey = `${category}:${search}:${period}`;
  const controlClass = "h-10 w-full min-w-0 rounded-md border border-[var(--color-line)] bg-white px-3 text-sm focus-visible:outline-2 focus-visible:outline-[var(--color-brand-500)]";
  return <section className="min-w-0 space-y-6" aria-label="Canonical account activity report">
    <div className="space-y-2 text-sm">
      <p className="font-bold">{report.account_scope === "all_registered_accounts" ? "All registered accounts" : "Operational email account scope"}</p>
      <p>{accounts.length} accounts in this report; {report.excluded_account_count} excluded by the server.</p>
      <p className="text-[var(--color-mute)]">Generated {timestamp(report.generated_at)} IST. Engagement window: {timestamp(report.activity_window.cutoff)} - {timestamp(report.activity_window.as_of)} IST.</p>
      <p className="text-[var(--color-mute)]">{report.activity_window.limitations}</p>
    </div>
    <dl className="grid grid-cols-2 gap-x-6 gap-y-3 border-y border-[var(--color-line)] py-4 lg:grid-cols-4">{Object.entries(categories).map(([key, label]) => <div key={key}><dt className="text-sm text-[var(--color-mute)]">{label}</dt><dd className="mt-1 text-lg font-bold tabular-nums">{report.segments[key as keyof typeof categories].company_count}</dd></div>)}</dl>
    <div className="grid min-w-0 gap-4 md:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)]">
      <div className="space-y-2"><Label htmlFor="activity-account-search">Account name</Label><Input id="activity-account-search" type="search" value={search} onChange={(event) => setSearch(event.target.value)} /></div>
      <div className="space-y-2"><Label htmlFor="activity-category">Category</Label><select id="activity-category" className={controlClass} value={category} onChange={(event) => setCategory(event.target.value)}><option value="all">All categories</option>{Object.entries(categories).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></div>
      <div className="space-y-2"><Label htmlFor="activity-period">Metric period</Label><select id="activity-period" className={controlClass} value={period} onChange={(event) => setPeriod(event.target.value as ActivityPeriod)}>{Object.entries(periods).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></div>
    </div>
    <p className="text-sm text-[var(--color-mute)]" role="status">{filtered.length} matching accounts. Metric dates: {bounds.start_date ?? "Beginning of recorded history"} - {bounds.end_date} (IST).</p>
    {!filtered.length ? <p className="py-6 text-sm">No accounts match these filters.</p> : null}
    {recent.length ? <section className="space-y-3" aria-label="Recent engagement"><h2 className="text-lg font-bold">Recent engagement ({recent.length})</h2><AccountGroup key={`recent:${resetKey}`} accounts={recent} period={period} label="Recent engagement" /></section> : null}
    {unknown.length ? <section className="space-y-3" aria-label="Unknown engagement"><h2 className="text-lg font-bold">Engagement unknown ({unknown.length})</h2><p className="text-sm text-[var(--color-mute)]">No conclusive successful-human-activity evidence. These accounts are not classified as inactive.</p><AccountGroup key={`unknown:${resetKey}`} accounts={unknown} period={period} label="Unknown engagement" /></section> : null}
    {inactive.length ? <details className="min-w-0 border-y border-[var(--color-line)] py-4"><summary className="cursor-pointer text-lg font-bold">No recorded activity for 30 days ({inactive.length})</summary><div className="mt-4"><AccountGroup key={`inactive:${resetKey}`} accounts={inactive} period={period} label="No recorded activity" /></div></details> : null}
    <details className="border-y border-[var(--color-line)] py-4"><summary className="cursor-pointer font-bold">Canonical category totals</summary><div className="relative mt-4 min-w-0 overflow-x-auto" role="region" tabIndex={0} aria-label="Category metric totals"><table className="w-full min-w-[42rem] text-left text-sm"><thead><tr><th scope="col" className="p-3">{periods[period]} metric</th>{Object.values(categories).map((label) => <th key={label} scope="col" className="p-3">{label}</th>)}</tr></thead><tbody>{Object.entries(metricLabels).map(([key, title]) => <tr key={key} className="border-t border-[var(--color-line)]"><th scope="row" className="p-3 font-medium">{title}</th>{Object.keys(categories).map((segment) => <td key={segment} className="p-3 tabular-nums">{metric(key, report.segments[segment as keyof typeof categories].periods[period][key as keyof typeof metricLabels])}</td>)}</tr>)}</tbody></table></div></details>
  </section>;
}

export function PlatformActivity() {
  const load = useCallback((signal: AbortSignal) => platformApi.activity(signal), []);
  const result = usePlatformLoad(load);
  if (result.pending) return <p role="status">Loading account activity...</p>;
  if (result.error) return <div className="space-y-3"><p role="alert">{result.error}</p><Button variant="outline" onClick={result.reload}>Load activity again</Button></div>;
  return result.data ? <ActivityReportView report={result.data} /> : null;
}
