"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Calendar,
  CalendarPlus,
  Gavel,
  Loader2,
  RefreshCw,
  ScrollText,
} from "lucide-react";
import { useParams } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { HearingPackDialog } from "@/components/app/HearingPackDialog";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/Card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/Dialog";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { ApiError } from "@/lib/api/config";
import {
  createMatterHearing,
  listMatterReminders,
  type MatterCourtSyncJob,
  type MatterReminderRecord,
  pullMatterCourtSync,
} from "@/lib/api/endpoints";
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
  // Strict Ledger #5 (BUG-013 in-app visibility, 2026-04-22):
  // per-matter reminder rows. Re-fetched on a 30s polling cadence
  // so the user sees the queue → sent → delivered transitions
  // without a hard refresh after the worker fires.
  const remindersQuery = useQuery({
    queryKey: ["matters", matterId, "reminders"],
    queryFn: () => listMatterReminders(matterId),
    refetchInterval: 30_000,
    enabled: Boolean(matterId),
  });
  const remindersByHearing = new Map<string, MatterReminderRecord[]>();
  for (const r of remindersQuery.data?.reminders ?? []) {
    const list = remindersByHearing.get(r.hearing_id) ?? [];
    list.push(r);
    remindersByHearing.set(r.hearing_id, list);
  }

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

  // Courts with a live court-sync adapter wired on the backend. Must
  // stay in sync with `court_sync_sources._COURT_NAME_TO_SOURCE`.
  // If the matter's court isn't in this set, POST /court-sync/pull
  // returns 400 with "no live court-sync adapter for …" — we'd rather
  // disable the button with a clear explanation than let the user hit
  // a raw API error (BUG-014 Hari 2026-04-21).
  const SUPPORTED_COURTS = new Set<string>([
    "Supreme Court of India",
    "Delhi High Court",
    "Bombay High Court",
    "Karnataka High Court",
    "Madras High Court",
    "Telangana High Court",
  ]);
  const matterCourt = data.matter.court_name ?? null;
  const hasLiveAdapter =
    matterCourt !== null && SUPPORTED_COURTS.has(matterCourt);
  const syncDisabledReason = !matterCourt
    ? "Set the matter's court before running sync."
    : !hasLiveAdapter
      ? `Live sync isn't wired for ${matterCourt} yet — supported: Supreme Court of India, Delhi / Bombay / Karnataka / Madras / Telangana High Courts.`
      : null;

  return (
    <div className="grid gap-5 lg:grid-cols-2">
      {canRunSync ? (
        <Card className="lg:col-span-2">
          <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
            <div>
              <CardTitle>Court sync</CardTitle>
              <CardDescription>
                {syncDisabledReason ??
                  "Pull the latest cause-list entries and orders from the court portal for this matter."}
              </CardDescription>
            </div>
            <Button
              type="button"
              size="sm"
              disabled={syncMutation.isPending || syncDisabledReason !== null}
              onClick={() => syncMutation.mutate()}
              title={syncDisabledReason ?? undefined}
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
        <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
          <div>
            <CardTitle>Scheduled hearings</CardTitle>
            <CardDescription>
              All hearings tracked on this matter — imported from the
              court sync above, or added here manually.
            </CardDescription>
          </div>
          <ScheduleHearingDialog matterId={matterId} />
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
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-semibold text-[var(--color-ink)]">
                      {h.hearing_type ?? "Hearing"}
                    </div>
                    <div className="mt-1 text-xs text-[var(--color-mute)]">
                      Scheduled: {formatDateTime(h.hearing_on ?? h.scheduled_for)}
                    </div>
                    {h.outcome_notes ? (
                      <p className="mt-2 line-clamp-3 text-sm text-[var(--color-ink-2)]">
                        {h.outcome_notes}
                      </p>
                    ) : null}
                    <HearingReminderStrip
                      reminders={remindersByHearing.get(h.id) ?? []}
                    />
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


/**
 * ScheduleHearingDialog — manual hearing creation for matters without a
 * third-party court-sync feed. Fix for BUG-004 (2026-04-20): previously
 * the only path to add a hearing was through Run Sync, leaving matters
 * with no live adapter silently stuck. Backend
 * POST /api/matters/{id}/hearings already existed; we just hadn't
 * exposed it on the web.
 */
function ScheduleHearingDialog({ matterId }: { matterId: string }): React.JSX.Element {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [hearingOn, setHearingOn] = useState("");
  const [forumName, setForumName] = useState("");
  const [purpose, setPurpose] = useState("");
  const [judgeName, setJudgeName] = useState("");

  const mutation = useMutation({
    mutationFn: () =>
      createMatterHearing({
        matterId,
        hearing_on: hearingOn,
        forum_name: forumName,
        purpose,
        judge_name: judgeName.trim() || null,
      }),
    onSuccess: async () => {
      setOpen(false);
      setHearingOn("");
      setForumName("");
      setPurpose("");
      setJudgeName("");
      await queryClient.invalidateQueries({
        queryKey: ["matters", matterId, "workspace"],
      });
      toast.success("Hearing scheduled.");
    },
    onError: (err) => {
      toast.error(err instanceof ApiError ? err.detail : "Could not schedule hearing.");
    },
  });

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button
          type="button"
          size="sm"
          variant="secondary"
          data-testid="schedule-hearing-open"
        >
          <CalendarPlus className="h-4 w-4" aria-hidden /> Schedule hearing
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Schedule a hearing</DialogTitle>
          <DialogDescription>
            Add a listing manually. Dates imported by court sync appear
            here alongside manual entries — pick whichever fits the
            matter.
          </DialogDescription>
        </DialogHeader>
        <form
          className="flex flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            mutation.mutate();
          }}
        >
          <div>
            <Label htmlFor="hearing_on">Hearing date</Label>
            <Input
              id="hearing_on"
              type="date"
              required
              value={hearingOn}
              onChange={(e) => setHearingOn(e.target.value)}
              data-testid="schedule-hearing-date"
            />
          </div>
          <div>
            <Label htmlFor="forum_name">Forum / bench</Label>
            <Input
              id="forum_name"
              type="text"
              required
              minLength={2}
              maxLength={255}
              placeholder="e.g. Delhi HC, Bench: Hon'ble Mr. Justice X"
              value={forumName}
              onChange={(e) => setForumName(e.target.value)}
            />
          </div>
          <div>
            <Label htmlFor="purpose">Purpose / stage</Label>
            <Input
              id="purpose"
              type="text"
              required
              minLength={2}
              maxLength={255}
              placeholder="e.g. Arguments on bail, first listing, evidence"
              value={purpose}
              onChange={(e) => setPurpose(e.target.value)}
            />
          </div>
          <div>
            <Label htmlFor="judge_name">Judge name (optional)</Label>
            <Input
              id="judge_name"
              type="text"
              maxLength={255}
              placeholder="Leave blank if the bench is not yet assigned"
              value={judgeName}
              onChange={(e) => setJudgeName(e.target.value)}
            />
          </div>
          {/* BUG-013 — dark-launched on 2026-04-22. When the hearing
              is created, backend persists ``hearing_reminders`` rows
              at T-24h and T-1h per configured offsets. The worker
              drains them when SendGrid credentials are present; until
              then the rows wait at status=queued. This copy is honest
              about that state. */}
          <p
            className="rounded-md border border-[var(--color-line)] bg-[var(--color-bg-2)] px-3 py-2 text-xs text-[var(--color-mute)]"
            role="note"
          >
            <strong className="font-medium text-[var(--color-ink-2)]">Reminders:</strong>{" "}
            the hearing will appear on this page and on the matter overview.
            Email reminders (T-24h and T-1h) are scheduled the moment the
            hearing is saved — they'll be delivered once the workspace's
            email provider is configured.
          </p>
          <DialogFooter>
            <Button
              type="button"
              variant="secondary"
              onClick={() => setOpen(false)}
              disabled={mutation.isPending}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={mutation.isPending || !hearingOn || !forumName || !purpose}
              data-testid="schedule-hearing-submit"
            >
              {mutation.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Saving…
                </>
              ) : (
                "Schedule"
              )}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}


// Strict Ledger #5 (BUG-013 in-app visibility, 2026-04-22): renders
// the queued / sent / delivered / failed reminders for a single
// hearing as an inline strip under the hearing summary. Hari's bug
// asked for "in-platform + email notifications" — email lands in
// the inbox; this strip is the in-platform half. The text shows
// the offset relative to the hearing date so the user can verify
// at a glance that T-24h and T-1h are queued for tomorrow's 4pm
// listing without opening the admin dashboard.
function HearingReminderStrip({
  reminders,
}: {
  reminders: MatterReminderRecord[];
}) {
  if (reminders.length === 0) return null;
  // Sort by scheduled_for so the earliest fire is on the left.
  const ordered = [...reminders].sort((a, b) => {
    const aT = a.scheduled_for ?? "";
    const bT = b.scheduled_for ?? "";
    return aT.localeCompare(bT);
  });
  return (
    <div
      className="mt-3 flex flex-wrap items-center gap-2 text-xs"
      data-testid="hearing-reminder-strip"
    >
      <span className="text-[var(--color-mute)]">Reminders:</span>
      {ordered.map((r) => (
        <span
          key={r.id}
          className={
            "inline-flex items-center gap-1 rounded-md border px-2 py-0.5 " +
            (r.status === "delivered"
              ? "border-[var(--color-brand-600)]/30 bg-[var(--color-brand-50,#eef2ff)] text-[var(--color-brand-700)]"
              : r.status === "sent"
                ? "border-[var(--color-line)] bg-[var(--color-bg)] text-[var(--color-ink-2)]"
                : r.status === "queued"
                  ? "border-[var(--color-line)] bg-white text-[var(--color-mute)]"
                  : "border-[var(--color-warn-600)]/30 bg-[var(--color-warn-50)] text-[var(--color-warn-700)]")
          }
          title={
            r.scheduled_for
              ? `Scheduled for ${new Date(r.scheduled_for).toLocaleString()}` +
                (r.last_error ? ` — ${r.last_error}` : "")
              : ""
          }
        >
          {r.scheduled_for
            ? new Date(r.scheduled_for).toLocaleString(undefined, {
                day: "2-digit",
                month: "short",
                hour: "2-digit",
                minute: "2-digit",
              })
            : "?"}
          {" · "}
          {r.status}
        </span>
      ))}
    </div>
  );
}
