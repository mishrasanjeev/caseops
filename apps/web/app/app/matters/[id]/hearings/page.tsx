"use client";

import { Calendar, Gavel, ScrollText } from "lucide-react";
import { useParams } from "next/navigation";

import { HearingPackDialog } from "@/components/app/HearingPackDialog";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { formatLegalDate } from "@/lib/dates";
import { useMatterWorkspace } from "@/lib/use-matter-workspace";

function formatDateTime(value: string | null | undefined): string {
  // scheduled_for is a SQL Date — no time component is meaningful.
  // Render as a calendar day in the local zone without the spurious
  // "12:00 AM" that toLocaleString would otherwise attach.
  return formatLegalDate(value, {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

export default function MatterHearingsPage() {
  const params = useParams<{ id: string }>();
  const { data } = useMatterWorkspace(params.id);
  if (!data) return null;

  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle>Scheduled hearings</CardTitle>
          <CardDescription>All hearings tracked on this matter.</CardDescription>
        </CardHeader>
        <CardContent>
          {data.hearings.length === 0 ? (
            <EmptyState
              icon={Gavel}
              title="No hearings yet"
              description="Schedule a hearing to unlock the hearing pack workflow — CaseOps drafts a brief from the matter facts for every listed date."
            />
          ) : (
            <ul className="flex flex-col gap-3">
              {data.hearings.map((h) => (
                <li
                  key={h.id}
                  className="flex items-start justify-between gap-3 rounded-xl border border-[var(--color-line)] bg-white p-4"
                >
                  <div>
                    <div className="text-sm font-semibold text-[var(--color-ink)]">
                      {h.hearing_type ?? "Hearing"}
                    </div>
                    <div className="mt-1 text-xs text-[var(--color-mute)]">
                      Scheduled: {formatDateTime(h.scheduled_for)}
                    </div>
                    {h.outcome_notes ? (
                      <p className="mt-2 line-clamp-3 text-sm text-[var(--color-ink-2)]">
                        {h.outcome_notes}
                      </p>
                    ) : null}
                    <div className="mt-3">
                      <HearingPackDialog matterId={params.id} hearingId={h.id} />
                    </div>
                  </div>
                  <StatusBadge status={h.status ?? "pending"} />
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Cause-list imports</CardTitle>
          <CardDescription>Entries pulled from the court feed.</CardDescription>
        </CardHeader>
        <CardContent>
          {data.cause_list_entries.length === 0 ? (
            <EmptyState
              icon={Calendar}
              title="No cause list yet"
              description="Run a court-sync from the legacy console to populate this feed."
            />
          ) : (
            <ul className="flex flex-col gap-2.5">
              {data.cause_list_entries.slice(0, 10).map((entry) => (
                <li
                  key={entry.id}
                  className="flex items-center justify-between gap-3 rounded-lg border border-[var(--color-line)] bg-[var(--color-bg)] px-3 py-2"
                >
                  <div>
                    <div className="text-sm font-medium text-[var(--color-ink)]">
                      Item {entry.item_number ?? "—"}
                    </div>
                    <div className="text-xs text-[var(--color-mute)]">
                      {entry.bench_name ?? "—"} · {entry.listing_date ?? "—"}
                    </div>
                  </div>
                  <StatusBadge status={entry.stage ?? "unknown"} />
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card className="lg:col-span-2">
        <CardHeader>
          <CardTitle>Orders on file</CardTitle>
          <CardDescription>Most recent orders first.</CardDescription>
        </CardHeader>
        <CardContent>
          {data.court_orders.length === 0 ? (
            <EmptyState
              icon={ScrollText}
              title="No orders attached"
              description="Upload or sync orders to build a tight chronology for hearing prep."
            />
          ) : (
            <ul className="flex flex-col gap-3">
              {data.court_orders.map((order) => (
                <li
                  key={order.id}
                  className="rounded-xl border border-[var(--color-line)] bg-white p-4"
                >
                  <div className="flex items-baseline justify-between gap-3">
                    <h3 className="text-sm font-semibold text-[var(--color-ink)]">
                      {order.title ?? "Order"}
                    </h3>
                    <span className="text-xs text-[var(--color-mute-2)]">
                      {order.order_date ?? "—"}
                    </span>
                  </div>
                  {order.summary ? (
                    <p className="mt-1.5 text-sm leading-relaxed text-[var(--color-mute)]">
                      {order.summary}
                    </p>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
