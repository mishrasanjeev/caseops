"use client";

import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Pencil, RefreshCw, Search } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/Dialog";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/Select";
import { Skeleton } from "@/components/ui/Skeleton";
import { Textarea } from "@/components/ui/Textarea";
import { apiErrorMessage } from "@/lib/api/config";
import {
  fetchIpRenewalTracker,
  updateIpPortfolioDates,
  type IpPortfolioDatesRecord,
  type IpPortfolioDatesUpdate,
  type IpPortfolioDateState,
  type IpRenewalTrackerCategory,
  type IpRenewalTrackerRow,
  type IpPortfolioFilters,
} from "@/lib/api/endpoints";
import { useCapability } from "@/lib/capabilities";

export type EditablePortfolioDates = IpPortfolioDatesRecord & { docket_title: string };
const DATE_STATES: Record<IpPortfolioDateState, string> = {
  missing: "Missing",
  manual: "Manual, unverified",
  imported_unverified: "Imported, unverified",
  verified: "Verified",
};
const CATEGORIES: ReadonlyArray<readonly [IpRenewalTrackerCategory, string]> = [
  ["upcoming", "Upcoming Renewals"],
  ["active", "Reminders Active"],
  ["due_today", "Due Today"],
  ["overdue", "Overdue"],
  ["missing", "Missing Renewal Date"],
  ["failed", "Failed Alerts"],
];

export function PortfolioDateValue({ value, state }: { value?: string | null; state?: IpPortfolioDateState }) {
  if (!value) return <span className="text-[var(--color-mute)]">Not set</span>;
  const parsed = new Date(`${value}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== value) {
    return <span className="text-[var(--color-warning-700)]">Invalid date</span>;
  }
  return (
    <span className="flex min-w-0 flex-col gap-1">
      <time dateTime={value} className="tabular-nums">
        {new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" }).format(parsed)}
      </time>
      {state ? <span className="text-xs text-[var(--color-mute)]">{DATE_STATES[state]}</span> : null}
    </span>
  );
}

export function PortfolioDateEditButton({ row, onEdit, disabled = false }: {
  row: EditablePortfolioDates;
  onEdit: (row: EditablePortfolioDates) => void;
  disabled?: boolean;
}) {
  const canWrite = useCapability("ip:write");
  if (!canWrite) return null;
  return (
    <Button size="sm" variant="ghost" aria-label={`Edit dates for ${row.docket_title}`} title="Edit dates"
      disabled={disabled} onClick={() => onEdit(row)}>
      <Pencil className="h-4 w-4" aria-hidden />
    </Button>
  );
}

export function PortfolioDateEditor({ row, onClose }: { row: EditablePortfolioDates; onClose: () => void }) {
  const client = useQueryClient();
  const [applicationDate, setApplicationDate] = useState(row.source_application_on ?? "");
  const [renewalDate, setRenewalDate] = useState(row.source_renewal_due_on ?? "");
  const [reason, setReason] = useState("");
  const applicationChanged = applicationDate !== (row.source_application_on ?? "");
  const renewalChanged = renewalDate !== (row.source_renewal_due_on ?? "");
  const save = useMutation({
    mutationFn: () => {
      const payload: IpPortfolioDatesUpdate = { expected_current_version: row.current_version, reason: reason.trim() };
      if (applicationChanged) payload.application_date = applicationDate || null;
      if (renewalChanged) payload.renewal_due_date = renewalDate || null;
      return updateIpPortfolioDates(row.docket_id, payload);
    },
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["ip", "portfolio"] });
      await client.invalidateQueries({ queryKey: ["ip", "docket", row.docket_id] });
      toast.success("Portfolio dates saved.");
      onClose();
    },
  });
  return (
    <Dialog open onOpenChange={(open) => { if (!open && !save.isPending) onClose(); }}>
      <DialogContent className="max-w-lg">
        <DialogHeader><DialogTitle>Edit portfolio dates</DialogTitle></DialogHeader>
        <DialogDescription className="break-words text-sm font-medium">{row.docket_title}</DialogDescription>
        <form className="grid min-w-0 gap-4" onSubmit={(event) => { event.preventDefault(); if (!save.isPending) save.mutate(); }}>
          <div className="grid min-w-0 gap-4 sm:grid-cols-2">
            <div className="min-w-0 space-y-1.5">
              <Label htmlFor="ip-application-date">Application Date</Label>
              <Input id="ip-application-date" type="date" value={applicationDate} disabled={save.isPending}
                onChange={(event) => setApplicationDate(event.target.value)} />
            </div>
            <div className="min-w-0 space-y-1.5">
              <Label htmlFor="ip-renewal-date">Renewal Due Date</Label>
              <Input id="ip-renewal-date" type="date" value={renewalDate} disabled={save.isPending}
                onChange={(event) => setRenewalDate(event.target.value)} />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="ip-date-change-reason">Reason for change</Label>
            <Textarea id="ip-date-change-reason" value={reason} minLength={5} maxLength={500} required disabled={save.isPending}
              onChange={(event) => setReason(event.target.value)} />
          </div>
          {save.isError ? <p role="alert" className="text-sm text-[var(--color-danger-700)]">
            {apiErrorMessage(save.error, "Could not save the dates. Refresh the record and try again.")}
          </p> : null}
          <DialogFooter>
            <Button type="button" variant="outline" disabled={save.isPending} onClick={onClose}>Cancel</Button>
            <Button type="submit" disabled={save.isPending || reason.trim().length < 5 || (!applicationChanged && !renewalChanged)}>
              {save.isPending ? "Saving" : "Save dates"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function Timestamp({ value, timezone }: { value: string | null; timezone: string }) {
  return value ? <time dateTime={value} className="tabular-nums">{new Intl.DateTimeFormat("en-GB", {
    day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", timeZone: timezone,
  }).format(new Date(value))}</time> : <span className="text-[var(--color-mute)]">Not recorded</span>;
}

function ReminderState({ row }: { row: IpRenewalTrackerRow }) {
  const status = { scheduled: "Scheduled", active: "Active", sent: "Sent", failed: "Failed", missing_date: "Missing Date", overdue: "Overdue", cancelled: "Cancelled" }[row.status];
  return (
    <div className="min-w-0 space-y-1 text-xs">
      <Badge tone={row.status === "failed" || row.status === "overdue" ? "warning" : "neutral"}>{status}</Badge>
      {row.days_remaining !== null ? <p>{row.days_remaining < 0 ? `${-row.days_remaining} days overdue`
        : row.days_remaining === 0 ? "Due today" : `${row.days_remaining} days remaining`}</p> : null}
      {row.last_attempt_at ? <p>Last attempt: <Timestamp value={row.last_attempt_at} timezone={row.timezone} /></p> : null}
      {row.delivered_at ? <p>Delivered: <Timestamp value={row.delivered_at} timezone={row.timezone} /></p> : null}
      {row.last_error ? <p role="status" className="break-words text-[var(--color-danger-700)]">{row.last_error}</p> : null}
    </div>
  );
}

type TrackerDateFilters = Pick<IpPortfolioFilters,
  "application_date_from" | "application_date_to" | "renewal_due_from" | "renewal_due_to">;

export function IpPortfolioRenewalTracker({ category, query = null, dateFilters = {}, onDateFiltersChange,
  onQueryChange, onCategoryChange, onEdit }: {
  category?: IpRenewalTrackerCategory;
  query?: string | null;
  dateFilters?: TrackerDateFilters;
  onDateFiltersChange?: (filters: TrackerDateFilters) => void;
  onQueryChange: (query: string | null) => void;
  onCategoryChange: (category?: IpRenewalTrackerCategory) => void;
  onEdit: (row: EditablePortfolioDates) => void;
}) {
  const [searchDraft, setSearchDraft] = useState(query ?? "");
  useEffect(() => setSearchDraft(query ?? ""), [query]);
  const listing = useInfiniteQuery({
    queryKey: ["ip", "portfolio", "renewal-tracker", category ?? "all", query, dateFilters],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) => fetchIpRenewalTracker(
      { category, query, ...dateFilters, limit: 50, cursor: pageParam }, { signal }),
    getNextPageParam: (page) => page.next_cursor,
  });
  const rows = listing.data?.pages.flatMap((page) => page.rows) ?? [];
  const counts = listing.data?.pages[0]?.counts;
  return (
    <section aria-labelledby="renewal-tracker-heading" className="flex min-w-0 flex-col gap-4">
      <div className="flex min-w-0 flex-wrap items-center justify-between gap-3">
        <h2 id="renewal-tracker-heading" className="text-lg font-semibold">Deadline tracker</h2>
        <div className="flex w-full min-w-0 gap-2 sm:w-auto">
          <Select value={category ?? "all"} onValueChange={(value) => onCategoryChange(value === "all" ? undefined : value as IpRenewalTrackerCategory)}>
            <SelectTrigger aria-label="Renewal tracker category" className="w-full min-w-0 sm:w-60"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All renewal records</SelectItem>
              {CATEGORIES.map(([key, title]) => <SelectItem key={key} value={key}>{title}</SelectItem>)}
            </SelectContent>
          </Select>
          <Button size="sm" className="h-9 w-9 shrink-0 p-0" variant="outline" aria-label="Refresh deadline tracker" title="Refresh deadline tracker"
            disabled={listing.isFetching} onClick={() => listing.refetch()}><RefreshCw className="h-4 w-4" aria-hidden /></Button>
        </div>
      </div>
      <form className="flex w-full min-w-0 gap-2" onSubmit={(event) => { event.preventDefault(); onQueryChange(searchDraft.trim() || null); }}>
        <div className="min-w-0 flex-1"><Label htmlFor="ip-renewal-tracker-search" className="sr-only">Search renewal tracker</Label>
          <Input id="ip-renewal-tracker-search" maxLength={200} value={searchDraft} onChange={(event) => setSearchDraft(event.target.value)} />
        </div>
        <Button type="submit" variant="outline" aria-label="Search renewal tracker"><Search className="h-4 w-4" aria-hidden /></Button>
      </form>
      {onDateFiltersChange ? <div className="grid min-w-0 grid-cols-[repeat(auto-fit,minmax(min(100%,12rem),1fr))] gap-3">
        {([
          ["application_date_from", "Application Date from"], ["application_date_to", "Application Date to"],
          ["renewal_due_from", "Renewal Due Date from"], ["renewal_due_to", "Renewal Due Date to"],
        ] as const).map(([key, label]) => <div key={key} className="min-w-0 space-y-1.5">
          <Label htmlFor={`tracker-${key}`}>{label}</Label>
          <Input id={`tracker-${key}`} type="date" value={dateFilters[key] ?? ""}
            onChange={(event) => onDateFiltersChange({ ...dateFilters, [key]: event.target.value || null })} />
        </div>)}
      </div> : null}
      {counts ? <dl className="flex min-w-0 flex-wrap gap-x-6 gap-y-3 border-y border-[var(--color-line)] py-3 text-sm">
        {CATEGORIES.map(([key, title]) => <div key={key}><dt className="text-xs text-[var(--color-mute)]">{title}</dt><dd className="font-semibold tabular-nums">{counts[key]}</dd></div>)}
      </dl> : null}
      {listing.isPending ? <div aria-label="Loading deadline tracker" role="status"><Skeleton className="h-48 w-full" /></div>
        : listing.isError ? <QueryErrorState error={listing.error} title="Could not load the deadline tracker" onRetry={() => listing.refetch()} />
          : rows.length === 0 ? <EmptyState title="No matching renewal records" description="No authorized trademark records match this renewal category." />
            : <div className="relative min-w-0 overflow-x-auto border-y border-[var(--color-line)]">
              <table className="w-full min-w-[1000px] table-fixed text-left text-sm">
                <caption className="sr-only">Persisted trademark renewal dates and reminder delivery</caption>
                <thead className="bg-[var(--color-bg-2)] text-xs text-[var(--color-mute)]"><tr>
                  <th scope="col" className="w-56 px-3 py-3">Trademark</th>
                  <th scope="col" className="w-40 px-3 py-3">Application Date</th>
                  <th scope="col" className="w-40 px-3 py-3">Renewal Due Date</th>
                  <th scope="col" className="w-40 px-3 py-3">Reminder Start Date</th>
                  <th scope="col" className="w-52 px-3 py-3">Next reminder</th>
                  <th scope="col" className="w-64 px-3 py-3">Reminder status</th>
                  <th scope="col" className="w-16 px-3 py-3"><span className="sr-only">Actions</span></th>
                </tr></thead>
                <tbody className="divide-y divide-[var(--color-line)]">{rows.map((row) => <tr key={row.docket_id} className="align-top">
                  <td className="break-words px-3 py-3"><Link href={`/app/ip?docket=${encodeURIComponent(row.docket_id)}`} className="font-semibold text-[var(--color-brand-700)] hover:underline">{row.docket_title}</Link>
                    <div className="mt-1 text-xs text-[var(--color-mute)]">{row.application_numbers.join(", ") || "Application number not set"}</div>
                    <div className="text-xs text-[var(--color-mute)]">Classes: {row.nice_classes.join(", ") || "Not set"}</div>
                  </td>
                  <td className="px-3 py-3"><PortfolioDateValue value={row.source_application_on} state={row.source_application_state} /></td>
                  <td className="px-3 py-3"><PortfolioDateValue value={row.source_renewal_due_on} state={row.source_renewal_state} /></td>
                  <td className="px-3 py-3"><PortfolioDateValue value={row.reminder_start_on} /></td>
                  <td className="px-3 py-3"><Timestamp value={row.next_reminder_at} timezone={row.timezone} />
                    <p className="mt-1 break-words text-xs text-[var(--color-mute)]">{row.timezone} · {row.delivery_time} · {row.cadence_days === 1 ? "Daily" : `Every ${row.cadence_days} days`}</p>
                  </td>
                  <td className="px-3 py-3"><ReminderState row={row} /></td>
                  <td className="px-3 py-3"><PortfolioDateEditButton row={row} onEdit={onEdit} disabled={!row.docket_operational} /></td>
                </tr>)}</tbody>
              </table>
            </div>}
      {listing.hasNextPage ? <div className="flex justify-center"><Button variant="outline" disabled={listing.isFetchingNextPage} onClick={() => listing.fetchNextPage()}>
        {listing.isFetchingNextPage ? "Loading" : "Load more renewal records"}
      </Button></div> : null}
    </section>
  );
}
