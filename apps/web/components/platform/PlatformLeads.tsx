"use client";

import { RefreshCw } from "lucide-react";
import { useCallback, useState } from "react";

import { Button } from "@/components/ui/Button";
import { platformApi } from "@/lib/platform/client";
import { usePlatformLoad } from "@/lib/platform/use-load";

import { PlatformGate } from "./PlatformGate";
import { PlatformPagination } from "./PlatformPagination";
import { PlatformShell } from "./PlatformShell";

const delivery = {
  not_requested: "Not requested", pending: "Pending", sending: "In progress",
  accepted: "Provider accepted", retry_pending: "Retry pending", exhausted: "Not sent",
  outcome_unknown: "Outcome unknown",
};
const deliveryErrors: Record<string, string> = {
  sender_approval_pending: "Enquiry notifications are paused.",
  configuration_unavailable: "Sender configuration is unavailable.",
  provider_rejected: "The email provider rejected the notification.",
  provider_rate_limited: "The email provider applied a rate limit.",
  attempt_limit: "The bounded notification attempt limit was reached.",
  automated_request_blocked: "Automated submissions cannot send real notifications.",
  transport_outcome_unknown: "Provider acceptance could not be confirmed.",
  transport_fence_closed: "Delivery admission changed before completion.",
  claim_expired: "The delivery claim expired without a confirmed outcome.",
  timeout: "A recorded delivery timed out; acceptance is unconfirmed.",
  smtp_failure: "A historical mail transport reported a failure.",
  transport_failure: "A historical transport reported a failure.",
};
const date = (value: string) => new Intl.DateTimeFormat("en-IN", {
  dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Kolkata",
}).format(new Date(value));

function LeadDirectory() {
  const [cursors, setCursors] = useState<(string | null)[]>([null]);
  const cursor = cursors[cursors.length - 1];
  const load = useCallback((signal: AbortSignal) => platformApi.leads(cursor, signal), [cursor]);
  const result = usePlatformLoad(load);
  return <div className="min-w-0 space-y-5">
    <div className="flex min-w-0 flex-wrap items-center justify-between gap-3">
      <h1 className="text-2xl font-bold">Leads</h1>
      <Button type="button" variant="outline" aria-label="Reload leads" title="Reload leads" disabled={result.pending} onClick={result.reload}>
        <RefreshCw className="h-4 w-4" aria-hidden />
      </Button>
    </div>
    {result.pending ? <p role="status">Loading leads...</p> : null}
    {result.error ? <p role="alert">{result.error}</p> : null}
    {result.data ? <div className="relative min-w-0 overflow-x-auto" role="region" aria-label="Public leads" tabIndex={0}>
      <table className="w-full min-w-[44rem] text-left text-sm">
        <caption className="sr-only">Retained public demo pricing and enquiry submissions</caption>
        <thead className="border-b border-[var(--color-line)]"><tr>{["Submitted IST", "Contact", "Request", "Notification", "Details"].map(label => <th key={label} scope="col" className="p-3">{label}</th>)}</tr></thead>
        <tbody>{result.data.items.map(row => <tr key={row.id} className="border-b border-[var(--color-line)] align-top">
          <td className="p-3"><time dateTime={row.submitted_at}>{date(row.submitted_at)}</time></td>
          <td className="max-w-64 break-words p-3"><p className="font-medium">{row.contact_name ?? "Not recorded"}</p><p className="break-all">{row.contact_email ?? "Not recorded"}</p><p>{row.company_name ?? ""}</p></td>
          <td className="max-w-48 break-words p-3"><p>{row.intent ?? "Not recorded"}</p><p>{row.source}</p><p>{row.segment}</p></td>
          <td className="max-w-56 p-3"><p>{delivery[row.notification.status]}</p><p className="mt-1 text-xs text-[var(--color-mute)]">{row.notification.attempts} attempts</p>
            {row.notification.last_error_code && deliveryErrors[row.notification.last_error_code] ? <p className="mt-1 text-xs">Recorded detail: {deliveryErrors[row.notification.last_error_code]}</p> : null}
            {!row.notification.eligible ? <p className="mt-1 text-xs text-[var(--color-mute)]">Not eligible for new-submission notifications</p> : null}
            {row.notification.status === "outcome_unknown" ? <p className="mt-1 text-xs">Inspect delivery evidence before any further send.</p> : null}
          </td>
          <td className="max-w-xl p-3"><details><summary className="cursor-pointer font-medium">View submission</summary>
            <dl className="mt-3 space-y-3 break-words">{[
              ["Reference", row.id], ["Full name", row.contact_name], ["Email", row.contact_email],
              ["Phone", row.contact_mobile], ["Firm or company", row.company_name], ["Practice segment", row.segment],
              ["Role", row.role], ["Intent", row.intent], ["Selected plan", row.selected_plan],
              ["Public entry point", row.source], ["Privacy notice", row.privacy_notice_version], ["Notes", row.notes],
            ].map(([label, value]) => <div key={label}><dt className="text-xs font-medium text-[var(--color-mute)]">{label}</dt><dd className="whitespace-pre-wrap break-words">{value ?? "Not provided"}</dd></div>)}</dl>
          </details></td>
        </tr>)}{!result.data.items.length ? <tr><td colSpan={5} className="p-6 text-[var(--color-mute)]">No public leads on this page.</td></tr> : null}</tbody>
      </table>
    </div> : null}
    <PlatformPagination page={cursors.length - 1} pending={result.pending} hasNext={Boolean(result.data?.has_more)}
      onPrevious={() => setCursors(old => old.slice(0, -1))}
      onNext={() => { if (result.data?.next_cursor) setCursors(old => [...old, result.data!.next_cursor]); }} />
  </div>;
}

export function PlatformLeads() {
  return <PlatformShell><PlatformGate managerOnly managerMessage="Leads require MFA-verified manager access."><LeadDirectory /></PlatformGate></PlatformShell>;
}
