"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Calendar, Gavel, Loader2, RefreshCw, ScrollText } from "lucide-react";
import { useParams } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { HearingPackDialog } from "@/components/app/HearingPackDialog";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { ApiError } from "@/lib/api/config";
import { pullMatterCourtSync, type MatterCourtSyncJob } from "@/lib/api/endpoints";
import { useCapability } from "@/lib/capabilities";
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
  const matterId = params.id;
  const queryClient = useQueryClient();
  const canRunSync = useCapability("court_sync:run");
  const [lastJob, setLastJob] = useState<MatterCourtSyncJob | null>(null);
  const { data } = useMatterWorkspace(matterId);

  const syncMutation = useMutation({
    mutationFn: () => pullMatterCourtSync({ matterId }),
    onSuccess: async (job) => {
      setLastJob(job);
      await queryClient.invalidateQueries({
        queryKey: ["matters", matterId, "workspace"],
      });
      toast.success(
        job.status === "completed"
          ? `Sync complete — ${job.imported_cause_list_entries} cause-list + ${job.imported_court_orders} order(s) imported.`
          : "Court sync queued — refresh to see imports.",
      );
    },
    onError: (err) => {
      toast.error(err instanceof ApiError ? err.detail : "Could not run court sync.");
    },
  });

  if (!data) return null;

  return (
    <div className="grid gap-5 lg:grid-cols-2">
      {canRunSync ? (
        <Card className="lg:col-span-2">
          <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
            <div>
              <CardTitle>Court sync</CardTitle>
              <CardDescription>
                Pull the latest cause-list entries and orders from the court
                portal for this matter.
              </CardDescription>
            </div>
            <Button
              type="button"
              size="sm"
              disabled={syncMutation.isPending}
              onClick={() => syncMutation.mutate()}
              data-testid="matter-court-sync-run"
            >
              {syncMutation.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Running…
                </>
              ) : (
                <>
                  <RefreshCw className="h-4 w-4" aria-hidden /> Run sync
                </>
              )}
            </Button>
          </CardHeader>
          {lastJob ? (
            <CardContent>
              <dl className="grid grid-cols-2 gap-4 text-sm md:grid-cols-4">
                <div>
                  <dt className="text-xs uppercase tracking-[0.06em] text-[var(--color-mute)]">
                    Status
                  </dt>
                  <dd className="mt-1">
                    <StatusBadge status={lastJob.status} />
                  </dd>
                </div>
                <div>
                  <dt className="text-xs uppercase tracking-[0.06em] text-[var(--color-mute)]">
                    Started
                  </dt>
                  <dd className="mt-1 text-[var(--color-ink-2)]">
                    {lastJob.started_at
                      ? new Date(lastJob.started_at).toLocaleString()
                      : "—"}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs uppercase tracking-[0.06em] text-[var(--color-mute)]">
                    Cause-list imports
                  </dt>
                  <dd className="mt-1 text-[var(--color-ink-2)]">
                    {lastJob.imported_cause_list_entries}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs uppercase tracking-[0.06em] text-[var(--color-mute)]">
                    Orders imported
                  </dt>
                  <dd className="mt-1 text-[var(--color-ink-2)]">
                    {lastJob.imported_court_orders}
                  </dd>
                </div>
              </dl>
              {lastJob.error_message ? (
                <p className="mt-3 text-xs text-[var(--color-danger-500,#c53030)]">
                  {lastJob.error_message}
                </p>
              ) : null}
            </CardContent>
          ) : null}
        </Card>
      ) : null}

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
                      <HearingPackDialog matterId={matterId} hearingId={h.id} />
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
              description={
                canRunSync
                  ? "Click ‘Run sync’ above to pull the latest cause list from the court portal."
                  : "A team member with court-sync access can pull the latest entries from the court portal."
              }
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
