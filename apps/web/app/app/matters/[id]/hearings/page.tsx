"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BarChart3,
  Bookmark,
  Calendar,
  CalendarCheck,
  CheckCircle2,
  ClipboardList,
  Eye,
  Gavel,
  HelpCircle,
  Loader2,
  PlayCircle,
  RefreshCw,
  ScrollText,
  Send,
  XCircle,
} from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { HearingPackDialog } from "@/components/app/HearingPackDialog";
import { OrderBadges } from "@/components/matters/OrderBadges";
import { AddCourtOrderDialog } from "@/components/matters/AddCourtOrderDialog";
import { ScheduleHearingDialog } from "@/components/matters/ScheduleHearingDialog";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { Textarea } from "@/components/ui/Textarea";
import { apiErrorMessage, isApiErrorShape } from "@/lib/api/config";
import {
  completeMockHearing,
  fetchCalendarSyncStatus,
  fetchMatterCompliance,
  fetchHearingCoach,
  fetchMockHearings,
  fetchNextHearingHistory,
  fetchProceedingIntelligence,
  generateHearingCoach,
  listMatterReminders,
  type MatterCourtSyncJob,
  type MatterReminderRecord,
  pullMatterCourtSync,
  decideNextHearingSuggestion,
  retryMatterAttachment,
  startMockHearing,
  submitMockHearingResponse,
  syncHearingToOutlook,
  updateMatterComplianceItem,
  updateMatterHearing,
} from "@/lib/api/endpoints";
import type {
  CalendarEventSyncRecord,
  HearingCoachFeedbackItem,
  HearingCoachReportResponse,
  HearingCoachStatusResponse,
  MatterComplianceExtractionRun,
  MatterComplianceListResponse,
  MockHearingListResponse,
  MockHearingQuestion,
  MockHearingSession,
  NextHearingHistoryResponse,
  ProceedingIntelligenceResponse,
  ProceedingOrderIntelligence,
  ProceedingSignal,
} from "@/lib/api/schemas";
import type { WorkspaceCourtOrder, WorkspaceHearing } from "@/lib/api/workspace-types";
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

function hearingTitle(hearing: WorkspaceHearing): string {
  return hearing.purpose ?? hearing.hearing_type ?? "Hearing";
}

function hearingOutcome(hearing: WorkspaceHearing): string | null | undefined {
  return hearing.outcome_note ?? hearing.outcome_notes;
}

function hearingDate(hearing: WorkspaceHearing): string | null | undefined {
  return hearing.hearing_on ?? hearing.scheduled_for ?? hearing.listing_date;
}

function sortOrders(
  orders: WorkspaceCourtOrder[],
  orderSort: "latest" | "oldest",
): WorkspaceCourtOrder[] {
  return [...orders].sort((a, b) => {
    const aDate = a.order_date ?? "";
    const bDate = b.order_date ?? "";
    return orderSort === "latest"
      ? bDate.localeCompare(aDate)
      : aDate.localeCompare(bDate);
  });
}

export default function MatterHearingsPage() {
  const params = useParams<{ id: string }>();
  const matterId = params.id;
  const queryClient = useQueryClient();
  const canRunSync = useCapability("court_sync:run");
  const canSyncOutlook = useCapability("calendar:sync");
  const canRunMockHearing = useCapability("hearing_packs:generate");
  const canManageDocuments = useCapability("documents:manage");
  const canManageHearings = useCapability("matters:write");
  const [lastJob, setLastJob] = useState<MatterCourtSyncJob | null>(null);
  const [orderSort, setOrderSort] = useState<"latest" | "oldest">("latest");
  const [mockResponseDraft, setMockResponseDraft] = useState("");
  const [coachAcknowledged, setCoachAcknowledged] = useState(false);
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
  const proceedingQuery = useQuery({
    queryKey: ["matters", matterId, "proceeding-intelligence"],
    queryFn: () => fetchProceedingIntelligence({ matterId }),
    enabled: Boolean(matterId),
  });
  const complianceQuery = useQuery({
    queryKey: ["matters", matterId, "compliance"],
    queryFn: () => fetchMatterCompliance(matterId),
    enabled: Boolean(matterId),
  });
  const nextHearingHistoryQuery = useQuery({
    queryKey: ["matters", matterId, "next-hearing-history"],
    queryFn: () => fetchNextHearingHistory(matterId),
    enabled: Boolean(matterId),
  });
  const mockHearingQuery = useQuery({
    queryKey: ["matters", matterId, "mock-hearings"],
    queryFn: () => fetchMockHearings({ matterId }),
    enabled: Boolean(matterId),
  });
  const hearingCoachQuery = useQuery({
    queryKey: ["matters", matterId, "hearing-coach"],
    queryFn: () => fetchHearingCoach({ matterId }),
    enabled: Boolean(matterId),
  });
  const outlookStatusQuery = useQuery({
    queryKey: ["calendar", "sync-status"],
    queryFn: fetchCalendarSyncStatus,
    enabled: canSyncOutlook,
  });
  const outlookSyncsByHearing = new Map<string, CalendarEventSyncRecord>();
  for (const sync of outlookStatusQuery.data?.syncs ?? []) {
    if (sync.source_type === "matter_hearing") {
      outlookSyncsByHearing.set(sync.source_id, sync);
    }
  }
  // BUG-044 (Hari 2026-05-11): pre-emptively detect "no Outlook
  // connection at all" so we render a Connect-Outlook link instead of
  // a Sync button that we know will 409. Disable the action, not just
  // the error (per feedback_root_cause_patterns_2026_04_22 rule #5).
  const hasOutlookConnection =
    (outlookStatusQuery.data?.connections.length ?? 0) > 0;
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
      toast.error(apiErrorMessage(err, "Could not run court sync."));
    },
  });
  const outlookSyncMutation = useMutation({
    mutationFn: syncHearingToOutlook,
    onSuccess: async (result) => {
      await queryClient.invalidateQueries({ queryKey: ["calendar", "sync-status"] });
      if (result.sync.sync_status === "failed") {
        toast.error(result.sync.last_error ?? "Outlook sync failed.");
      } else {
        toast.success("Hearing synced to Outlook.");
      }
    },
    onError: (err) => {
      // BUG-044 (Hari 2026-05-11): the backend returns 409 with
      // detail "Outlook calendar is not connected." when the user has
      // no Outlook connection. The raw toast tells them what's wrong
      // but not what to do (memory: feedback_error_copy_principle).
      // Catch the 409 and render an actionable toast that takes the
      // user straight to /app/calendar to connect.
      if (isApiErrorShape(err) && err.status === 409) {
        toast.error("Outlook calendar isn't connected yet.", {
          description: "Connect Outlook from the Calendar page, then retry the sync.",
          action: {
            label: "Connect Outlook",
            onClick: () => {
              window.location.assign("/app/calendar");
            },
          },
        });
        return;
      }
      toast.error(apiErrorMessage(err, "Could not sync hearing to Outlook."));
    },
  });
  const upsertMockSession = (session: MockHearingSession) => {
    queryClient.setQueryData<MockHearingListResponse>(
      ["matters", matterId, "mock-hearings"],
      (current) => {
        const existing = current?.sessions ?? [];
        return {
          matter_id: matterId,
          generated_at: new Date().toISOString(),
          disclaimer: session.disclaimer,
          sessions: [session, ...existing.filter((item) => item.id !== session.id)],
          latest_session: session,
        };
      },
    );
  };
  const startMockMutation = useMutation({
    mutationFn: () => startMockHearing({ matterId }),
    onSuccess: (session) => {
      upsertMockSession(session);
      setMockResponseDraft("");
      toast.success("Mock hearing session started.");
    },
    onError: (err) => {
      toast.error(apiErrorMessage(err, "Could not start mock hearing."));
    },
  });
  const submitMockResponseMutation = useMutation({
    mutationFn: ({
      sessionId,
      questionId,
      responseText,
    }: {
      sessionId: string;
      questionId: string | null;
      responseText: string;
    }) =>
      submitMockHearingResponse({
        matterId,
        sessionId,
        questionId,
        responseText,
      }),
    onSuccess: (session) => {
      upsertMockSession(session);
      setMockResponseDraft("");
      void queryClient.invalidateQueries({
        queryKey: ["matters", matterId, "hearing-coach"],
      });
    },
    onError: (err) => {
      toast.error(apiErrorMessage(err, "Could not record response."));
    },
  });
  const completeMockMutation = useMutation({
    mutationFn: (sessionId: string) => completeMockHearing({ matterId, sessionId }),
    onSuccess: (session) => {
      upsertMockSession(session);
      toast.success("Mock hearing session completed.");
    },
    onError: (err) => {
      toast.error(apiErrorMessage(err, "Could not complete mock hearing."));
    },
  });
  const generateCoachMutation = useMutation({
    mutationFn: (sessionId: string) =>
      generateHearingCoach({
        matterId,
        sessionId,
        acknowledged: coachAcknowledged,
      }),
    onSuccess: () => {
      toast.success("Hearing coach report generated.");
    },
    onError: (err) => {
      toast.error(apiErrorMessage(err, "Could not generate hearing coach report."));
    },
  });
  const complianceMutation = useMutation({
    mutationFn: ({
      itemId,
      action,
    }: {
      itemId: string;
      action: "confirm" | "reject" | "waive" | "complete";
    }) => updateMatterComplianceItem({ matterId, itemId, action }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["matters", matterId, "compliance"] });
      await queryClient.invalidateQueries({ queryKey: ["matters", matterId, "workspace"] });
      toast.success("Compliance item updated.");
    },
    onError: (err) => {
      toast.error(apiErrorMessage(err, "Could not update compliance item."));
    },
  });
  const retryOrderAttachmentMutation = useMutation({
    mutationFn: (attachmentId: string) =>
      retryMatterAttachment({ matterId, attachmentId }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["matters", matterId, "workspace"] });
      await queryClient.invalidateQueries({ queryKey: ["matters", matterId, "compliance"] });
      toast.success("Order document processing queued.");
    },
    onError: (err) => {
      toast.error(apiErrorMessage(err, "Could not process order document."));
    },
  });
  const nextHearingSuggestionMutation = useMutation({
    mutationFn: ({
      suggestionId,
      action,
    }: {
      suggestionId: string;
      action: "accept" | "reject";
    }) => decideNextHearingSuggestion({ matterId, suggestionId, action }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["matters", matterId, "next-hearing-history"],
      });
      await queryClient.invalidateQueries({ queryKey: ["matters", matterId, "workspace"] });
      toast.success("Next hearing suggestion updated.");
    },
    onError: (err) => {
      toast.error(apiErrorMessage(err, "Could not update next hearing suggestion."));
    },
  });
  const cancelHearingMutation = useMutation({
    mutationFn: (hearingId: string) =>
      updateMatterHearing({
        matterId,
        hearingId,
        status: "cancelled",
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["matters", matterId, "workspace"],
      });
      await queryClient.invalidateQueries({
        queryKey: ["matters", matterId, "reminders"],
      });
      await queryClient.invalidateQueries({ queryKey: ["calendar", "sync-status"] });
      toast.success("Hearing cancelled. Queued reminders and provider calendar events were removed where connected.");
    },
    onError: (err) => {
      toast.error(apiErrorMessage(err, "Could not cancel hearing."));
    },
  });

  if (!data) return null;
  const isDisposedMatter = data.matter.status === "disposed";
  const completedHearings = data.hearings.filter((hearing) => hearing.status === "completed");
  const cancelledHearings = data.hearings.filter((hearing) => hearing.status === "cancelled");
  const upcomingHearings = data.hearings.filter(
    (hearing) => hearing.status !== "completed" && hearing.status !== "cancelled",
  );
  const sortedOrders = sortOrders(data.court_orders, orderSort);

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
  const syncDisabledReason = isDisposedMatter
    ? "Disposed matters cannot run court sync. Reopen to Intake first."
    : !matterCourt
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

      {!isDisposedMatter ? (
      <Card className="lg:col-span-2" data-testid="matter-case-tracking-panel">
        <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
          <div>
            <CardTitle>Track this court case</CardTitle>
            <CardDescription>
              Search by CNR or case number and bookmark updates for in-app notifications.
            </CardDescription>
          </div>
          <Button
            type="button"
            size="sm"
            variant="outline"
            href={`/app/case-tracking?matterId=${encodeURIComponent(matterId)}`}
          >
            <Bookmark className="h-4 w-4" aria-hidden />
            Track case
          </Button>
        </CardHeader>
      </Card>
      ) : null}

      <NextHearingProvenanceSection
        response={nextHearingHistoryQuery.data}
        isLoading={nextHearingHistoryQuery.isPending}
        onDecide={(suggestionId, action) =>
          nextHearingSuggestionMutation.mutate({ suggestionId, action })
        }
        isPending={nextHearingSuggestionMutation.isPending || isDisposedMatter}
      />

      <ComplianceReviewSection
        response={complianceQuery.data}
        isLoading={complianceQuery.isPending}
        onAction={(itemId, action) => complianceMutation.mutate({ itemId, action })}
        isPending={complianceMutation.isPending}
        canRetryAttachmentProcessing={canManageDocuments && !isDisposedMatter}
        retryingAttachmentId={
          retryOrderAttachmentMutation.variables ?? null
        }
        onRetryAttachment={(attachmentId) =>
          retryOrderAttachmentMutation.mutate(attachmentId)
        }
      />

      <Card>
        <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
          <div>
            <CardTitle>Upcoming hearings</CardTitle>
            <CardDescription>
              All hearings tracked on this matter — imported from the
              court sync above, or added here manually.
            </CardDescription>
          </div>
          {!isDisposedMatter ? <ScheduleHearingDialog matterId={matterId} /> : null}
        </CardHeader>
        <CardContent>
          {upcomingHearings.length === 0 ? (
            <EmptyState
              icon={Gavel}
              title="No hearings yet"
              description="Schedule a hearing to unlock the hearing pack workflow — CaseOps drafts a brief from the matter facts for every listed date."
            />
          ) : (
            <ul className="flex flex-col gap-3">
              {upcomingHearings.map((h) => (
                <li
                  key={h.id}
                  className="flex items-start justify-between gap-3 rounded-xl border border-[var(--color-line)] bg-white p-4"
                >
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-semibold text-[var(--color-ink)]">
                      {hearingTitle(h)}
                    </div>
                    <div className="mt-1 text-xs text-[var(--color-mute)]">
                      Scheduled: {formatDateTime(hearingDate(h))}
                    </div>
                    {hearingOutcome(h) ? (
                      <p className="mt-2 line-clamp-3 text-sm text-[var(--color-ink-2)]">
                        {hearingOutcome(h)}
                      </p>
                    ) : null}
                    <HearingReminderStrip
                      reminders={remindersByHearing.get(h.id) ?? []}
                    />
                    {canSyncOutlook ? (
                      <HearingOutlookSync
                        hearing={h}
                        sync={outlookSyncsByHearing.get(h.id)}
                        hasConnection={hasOutlookConnection}
                        isPending={
                          outlookSyncMutation.isPending &&
                          outlookSyncMutation.variables === h.id
                        }
                        onSync={() => outlookSyncMutation.mutate(h.id)}
                      />
                    ) : null}
                    <div className="mt-3 flex flex-wrap items-center gap-2">
                      <HearingPackDialog matterId={matterId} hearingId={h.id} />
                      {canManageHearings ? (
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          disabled={
                            cancelHearingMutation.isPending &&
                            cancelHearingMutation.variables === h.id
                          }
                          onClick={() => cancelHearingMutation.mutate(h.id)}
                          data-testid={`hearing-cancel-${h.id}`}
                        >
                          {cancelHearingMutation.isPending &&
                          cancelHearingMutation.variables === h.id ? (
                            <>
                              <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Cancelling
                            </>
                          ) : (
                            <>
                              <XCircle className="h-4 w-4" aria-hidden /> Cancel hearing
                            </>
                          )}
                        </Button>
                      ) : null}
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
          <CardTitle>Completed hearings</CardTitle>
          <CardDescription>Closed listings and recorded outcomes.</CardDescription>
        </CardHeader>
        <CardContent>
          {completedHearings.length === 0 ? (
            <p className="text-sm text-[var(--color-mute)]">
              No completed hearings yet.
            </p>
          ) : (
            <ul className="flex flex-col gap-3">
              {completedHearings.map((h) => (
                <li
                  key={h.id}
                  className="flex items-start justify-between gap-3 rounded-xl border border-[var(--color-line)] bg-[var(--color-bg)] p-4"
                >
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-semibold text-[var(--color-ink)]">
                      {hearingTitle(h)}
                    </div>
                    <div className="mt-1 text-xs text-[var(--color-mute)]">
                      Heard: {formatDateTime(hearingDate(h))}
                    </div>
                    {hearingOutcome(h) ? (
                      <p className="mt-2 line-clamp-3 text-sm text-[var(--color-ink-2)]">
                        {hearingOutcome(h)}
                      </p>
                    ) : null}
                    {canSyncOutlook ? (
                      <HearingOutlookSync
                        hearing={h}
                        sync={outlookSyncsByHearing.get(h.id)}
                        hasConnection={hasOutlookConnection}
                        isPending={
                          outlookSyncMutation.isPending &&
                          outlookSyncMutation.variables === h.id
                        }
                        onSync={() => outlookSyncMutation.mutate(h.id)}
                      />
                    ) : null}
                  </div>
                  <StatusBadge status={h.status ?? "completed"} />
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Cancelled hearings</CardTitle>
          <CardDescription>
            Listings removed from active calendars and reminder queues.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {cancelledHearings.length === 0 ? (
            <p className="text-sm text-[var(--color-mute)]">
              No cancelled hearings.
            </p>
          ) : (
            <ul className="flex flex-col gap-3">
              {cancelledHearings.map((h) => (
                <li
                  key={h.id}
                  className="flex items-start justify-between gap-3 rounded-xl border border-[var(--color-line)] bg-[var(--color-bg)] p-4"
                  data-testid={`cancelled-hearing-${h.id}`}
                >
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-semibold text-[var(--color-ink)]">
                      {hearingTitle(h)}
                    </div>
                    <div className="mt-1 text-xs text-[var(--color-mute)]">
                      Cancelled listing date: {formatDateTime(hearingDate(h))}
                    </div>
                    {hearingOutcome(h) ? (
                      <p className="mt-2 line-clamp-3 text-sm text-[var(--color-ink-2)]">
                        {hearingOutcome(h)}
                      </p>
                    ) : null}
                  </div>
                  <StatusBadge status={h.status ?? "cancelled"} />
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
                  data-testid={`cause-list-entry-${entry.id}`}
                >
                  <div>
                    <div className="text-sm font-medium text-[var(--color-ink)]">
                      Item {entry.item_number ?? "—"}
                    </div>
                    <div className="text-xs text-[var(--color-mute)]">
                      {/* Slice B (MOD-TS-001-C, 2026-04-25). Render
                          resolved_bench as clickable per-judge links
                          when populated; fall back to the free-text
                          bench_name otherwise. */}
                      {entry.resolved_bench && entry.resolved_bench.length > 0 ? (
                        <span data-testid="cause-list-bench-resolved">
                          {entry.resolved_bench.map((m, i) => (
                            <span key={m.judge_id}>
                              {i > 0 ? " · " : ""}
                              <Link
                                href={`/app/courts/judges/${m.judge_id}`}
                                className="text-[var(--color-brand-600)] hover:underline"
                                title={
                                  m.confidence === "initial_surname"
                                    ? "Resolved via initial+surname match"
                                    : "Exact alias match"
                                }
                              >
                                {m.matched_alias || "judge"}
                              </Link>
                            </span>
                          ))}
                        </span>
                      ) : (
                        <span>{entry.bench_name ?? "—"}</span>
                      )}
                      {" · "}
                      {entry.listing_date ?? "—"}
                    </div>
                  </div>
                  <StatusBadge status={entry.stage ?? "unknown"} />
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <ProceedingIntelligenceSection
        matterId={matterId}
        response={proceedingQuery.data}
        isLoading={proceedingQuery.isPending}
        isError={proceedingQuery.isError}
      />

      <MockHearingSection
        matterId={matterId}
        response={mockHearingQuery.data}
        isLoading={mockHearingQuery.isPending}
        isError={mockHearingQuery.isError}
        canRun={canRunMockHearing}
        responseDraft={mockResponseDraft}
        isStarting={startMockMutation.isPending}
        isSubmitting={submitMockResponseMutation.isPending}
        isCompleting={completeMockMutation.isPending}
        onStart={() => startMockMutation.mutate()}
        onResponseDraftChange={setMockResponseDraft}
        onSubmit={(sessionId, questionId) => {
          const text = mockResponseDraft.trim();
          if (!text) return;
          submitMockResponseMutation.mutate({
            sessionId,
            questionId,
            responseText: text,
          });
        }}
        onComplete={(sessionId) => completeMockMutation.mutate(sessionId)}
      />

      <HearingCoachSection
        matterId={matterId}
        mockHearings={mockHearingQuery.data}
        status={hearingCoachQuery.data}
        report={generateCoachMutation.data}
        isLoading={hearingCoachQuery.isPending}
        isError={hearingCoachQuery.isError}
        canRun={canRunMockHearing}
        acknowledged={coachAcknowledged}
        isGenerating={generateCoachMutation.isPending}
        onAcknowledgedChange={setCoachAcknowledged}
        onGenerate={(sessionId) => generateCoachMutation.mutate(sessionId)}
      />

      <Card className="lg:col-span-2">
        <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
          <div>
            <CardTitle>Orders on file</CardTitle>
            <CardDescription>
              Order sheet metadata, interim flags, and stay status.
            </CardDescription>
          </div>
          <div className="flex gap-2">
            {/* BUG-032 (Hari 2026-05-09): Add-order affordance.
                Available in the card header AND in the empty state
                below so a fresh matter has a clear path to its first
                order without a court-sync. */}
            <AddCourtOrderDialog matterId={matterId} />
            <Button
              type="button"
              size="sm"
              variant={orderSort === "latest" ? "secondary" : "outline"}
              onClick={() => setOrderSort("latest")}
            >
              Latest
            </Button>
            <Button
              type="button"
              size="sm"
              variant={orderSort === "oldest" ? "secondary" : "outline"}
              onClick={() => setOrderSort("oldest")}
            >
              Oldest
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {data.court_orders.length === 0 ? (
            <EmptyState
              icon={ScrollText}
              title="No orders attached"
              description="Add an order manually, or run court sync to import them. Orders here also show up in the documents page Linked-order selector."
              action={<AddCourtOrderDialog matterId={matterId} triggerLabel="Add the first order" />}
            />
          ) : (
            <ul className="flex flex-col gap-3">
              {sortedOrders.map((order) => (
                <li
                  key={order.id}
                  className="rounded-xl border border-[var(--color-line)] bg-white p-4"
                  data-testid={`matter-court-order-${order.id}`}
                >
                  <div className="flex items-baseline justify-between gap-3">
                    <h3 className="text-sm font-semibold text-[var(--color-ink)]">
                      {order.title ?? "Order"}
                    </h3>
                    <span className="text-xs text-[var(--color-mute-2)]">
                      {order.order_date ?? "—"}
                    </span>
                  </div>
                  <div className="mt-2">
                    <OrderBadges order={order} />
                  </div>
                  {order.bench_name || order.judge_names?.length ? (
                    <p className="mt-1.5 text-xs text-[var(--color-mute-2)]">
                      {[order.bench_name, ...(order.judge_names ?? [])]
                        .filter(Boolean)
                        .join(" - ")}
                    </p>
                  ) : null}
                  {order.summary ? (
                    <p className="mt-1.5 text-sm leading-relaxed text-[var(--color-mute)]">
                      {order.summary}
                    </p>
                  ) : null}
                  {/* BUG-042 (Hari 2026-05-11): when an order has an
                      attached document (uploaded via AddCourtOrderDialog
                      or the Documents tab's linked-order selector),
                      surface a View affordance on the hearings page
                      itself. The order card is the natural place users
                      look after upload — sending them to the Documents
                      tab to find their own file is the upload-but-no-
                      view anti-pattern (memory:
                      feedback_root_cause_patterns_2026_04_22 #5,
                      feedback_brutal_bug_fixing_2026_04_26 #2). */}
                  {order.order_attachment_id ? (
                    <div className="mt-3">
                      <Button
                        variant="ghost"
                        size="sm"
                        href={`/app/matters/${matterId}/documents/${order.order_attachment_id}/view`}
                        data-testid={`matter-court-order-view-${order.id}`}
                      >
                        <Eye className="h-4 w-4" aria-hidden /> View order document
                      </Button>
                    </div>
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


// ScheduleHearingDialog moved to apps/web/components/matters/ScheduleHearingDialog.tsx
// (2026-04-30) so the matter cockpit empty-state can mount the same
// affordance — BUG-019/025 durable closure.


// Strict Ledger #5 (BUG-013 in-app visibility, 2026-04-22): renders
// the queued / sent / delivered / failed reminders for a single
// hearing as an inline strip under the hearing summary. Hari's bug
// asked for "in-platform + email notifications" — email lands in
// the inbox; this strip is the in-platform half. The text shows
// the offset relative to the hearing date so the user can verify
// at a glance that T-24h and T-1h are queued for tomorrow's 4pm
// listing without opening the admin dashboard.
const PROCEEDING_SIGNAL_LABELS: Record<string, string> = {
  next_hearing: "Next hearing",
  filing_defect: "Filing defect",
  compliance_direction: "Compliance direction",
  reply_affidavit_deadline: "Reply / affidavit deadline",
  counsel_appearance: "Counsel appearance",
  interim_observation: "Interim observation",
  order_kind: "Order kind",
  action_required: "Action required",
};

function sourceHref(matterId: string, order: ProceedingOrderIntelligence): string {
  if (order.order_attachment_id) {
    return `/app/matters/${matterId}/documents/${order.order_attachment_id}/view`;
  }
  return `/app/matters/${matterId}/timeline`;
}

function signalDueText(signal: ProceedingSignal): string | null {
  if (signal.due_on) return `Due ${formatDateTime(signal.due_on)}`;
  if (signal.hearing_on) return `Hearing ${formatDateTime(signal.hearing_on)}`;
  return null;
}

export function NextHearingProvenanceSection({
  response,
  isLoading,
  onDecide,
  isPending,
}: {
  response: NextHearingHistoryResponse | undefined;
  isLoading: boolean;
  onDecide: (suggestionId: string, action: "accept" | "reject") => void;
  isPending: boolean;
}) {
  const pending = response?.suggestions.filter((item) => item.status === "pending") ?? [];
  const history = response?.history ?? [];
  return (
    <Card className="lg:col-span-2" data-testid="next-hearing-provenance">
      <CardHeader>
        <CardTitle>Next hearing provenance</CardTitle>
        <CardDescription>Review automatic hearing-date suggestions and source history.</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4 lg:grid-cols-2">
        <div>
          <div className="mb-2 text-sm font-medium text-[var(--color-ink)]">Suggestions</div>
          {isLoading ? (
            <p className="text-sm text-[var(--color-mute)]">Loading suggestions...</p>
          ) : pending.length === 0 ? (
            <p className="text-sm text-[var(--color-mute)]">No pending suggestions.</p>
          ) : (
            <ul className="flex flex-col gap-2">
              {pending.map((suggestion) => (
                <li key={suggestion.id} className="rounded-lg border border-[var(--color-line)] p-3">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="font-medium text-[var(--color-ink)]">
                        {formatDateTime(suggestion.suggested_date)}
                      </div>
                      <div className="text-xs text-[var(--color-mute)]">
                        {suggestion.source} - {suggestion.reason ?? "review required"}
                      </div>
                    </div>
                    <StatusBadge status={suggestion.confidence_label} />
                  </div>
                  <div className="mt-3 flex gap-2">
                    <Button size="sm" onClick={() => onDecide(suggestion.id, "accept")} disabled={isPending}>
                      Accept
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => onDecide(suggestion.id, "reject")} disabled={isPending}>
                      Reject
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div>
          <div className="mb-2 text-sm font-medium text-[var(--color-ink)]">History</div>
          {history.length === 0 ? (
            <p className="text-sm text-[var(--color-mute)]">No history recorded yet.</p>
          ) : (
            <ul className="flex max-h-64 flex-col gap-2 overflow-auto">
              {history.slice(0, 8).map((row) => (
                <li key={row.id} className="rounded-lg bg-[var(--color-bg)] px-3 py-2 text-sm">
                  <div className="font-medium text-[var(--color-ink)]">
                    {row.old_date ? formatDateTime(row.old_date) : "Not set"}
                    {" -> "}
                    {row.new_date ? formatDateTime(row.new_date) : "Not set"}
                  </div>
                  <div className="text-xs text-[var(--color-mute)]">
                    {row.source} - {row.change_reason ?? "updated"} {row.manual_lock ? "- manual lock" : ""}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

export function ComplianceReviewSection({
  response,
  isLoading,
  onAction,
  isPending,
  canRetryAttachmentProcessing,
  retryingAttachmentId,
  onRetryAttachment,
}: {
  response: MatterComplianceListResponse | undefined;
  isLoading: boolean;
  onAction: (itemId: string, action: "confirm" | "reject" | "waive" | "complete") => void;
  isPending: boolean;
  canRetryAttachmentProcessing: boolean;
  retryingAttachmentId: string | null;
  onRetryAttachment: (attachmentId: string) => void;
}) {
  const activeItems =
    response?.items.filter((item) => item.review_status !== "rejected") ?? [];
  const recentRuns = response?.runs.slice(0, 4) ?? [];
  return (
    <Card className="lg:col-span-2" data-testid="matter-compliance-panel">
      <CardHeader>
        <CardTitle>Compliance review</CardTitle>
        <CardDescription>
          Court-order directions are source-backed and stay review-required until confirmed.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <p className="text-sm text-[var(--color-mute)]">Loading compliance items...</p>
        ) : (
          <div className="flex flex-col gap-4">
            <ComplianceExtractionRuns
              runs={recentRuns}
              canRetryAttachmentProcessing={canRetryAttachmentProcessing}
              retryingAttachmentId={retryingAttachmentId}
              onRetryAttachment={onRetryAttachment}
            />
            {activeItems.length === 0 ? (
              <EmptyState
                icon={ClipboardList}
                title="No compliance items"
                description="Create or upload a court order with extractable text to populate review items."
              />
            ) : (
              <ul className="flex flex-col gap-3">
                {activeItems.map((item) => (
                  <li key={item.id} className="rounded-xl border border-[var(--color-line)] bg-white p-4">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="text-sm font-semibold text-[var(--color-ink)]">{item.description}</div>
                        <div className="mt-1 text-xs text-[var(--color-mute)]">
                          {item.due_on ? `Due ${formatDateTime(item.due_on)}` : "Due date not available"} - {item.responsible_party ?? "Responsible party not available"}
                        </div>
                      </div>
                      <StatusBadge status={item.review_status} />
                    </div>
                    <p className="mt-2 line-clamp-3 text-sm text-[var(--color-ink-2)]">
                      {item.source_snippet}
                    </p>
                    <div className="mt-3 flex flex-wrap gap-2">
                      {item.review_status === "review_required" || item.review_status === "edited" ? (
                        <>
                          <Button size="sm" onClick={() => onAction(item.id, "confirm")} disabled={isPending}>
                            Confirm
                          </Button>
                          <Button size="sm" variant="outline" onClick={() => onAction(item.id, "reject")} disabled={isPending}>
                            Reject
                          </Button>
                          <Button size="sm" variant="ghost" onClick={() => onAction(item.id, "waive")} disabled={isPending}>
                            Waive
                          </Button>
                        </>
                      ) : null}
                      {item.review_status === "confirmed" && item.status !== "completed" ? (
                        <Button size="sm" variant="outline" onClick={() => onAction(item.id, "complete")} disabled={isPending}>
                          Complete
                        </Button>
                      ) : null}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function ComplianceExtractionRuns({
  runs,
  canRetryAttachmentProcessing,
  retryingAttachmentId,
  onRetryAttachment,
}: {
  runs: MatterComplianceExtractionRun[];
  canRetryAttachmentProcessing: boolean;
  retryingAttachmentId: string | null;
  onRetryAttachment: (attachmentId: string) => void;
}) {
  if (runs.length === 0) return null;
  return (
    <div className="rounded-lg border border-[var(--color-line)] bg-[var(--color-bg)] p-3">
      <div className="mb-2 text-sm font-medium text-[var(--color-ink)]">
        Extraction status
      </div>
      <ul className="flex flex-col gap-2" data-testid="matter-compliance-run-list">
        {runs.map((run) => {
          const canProcessAttachment =
            Boolean(run.attachment_id) &&
            canRetryAttachmentProcessing &&
            (run.status === "skipped" || run.status === "failed") &&
            (
              run.skip_reason === "text_extraction_pending" ||
              run.skip_reason === "text_extraction_failed"
            );
          return (
            <li
              key={run.id}
              className="flex flex-wrap items-center justify-between gap-2 rounded-md bg-white px-3 py-2 text-xs"
              data-testid={`matter-compliance-run-${run.id}`}
            >
              <div className="min-w-0">
                <div className="font-medium text-[var(--color-ink)]">
                  {run.attachment_id ? "Uploaded order document" : "Court order"} - {run.status}
                </div>
                <div className="text-[var(--color-mute)]">
                  {run.skip_reason ?? run.error_message_redacted ?? "Source text reviewed"}
                </div>
              </div>
              {canProcessAttachment && run.attachment_id ? (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={retryingAttachmentId === run.attachment_id}
                  onClick={() => onRetryAttachment(run.attachment_id as string)}
                  data-testid={`matter-compliance-process-${run.attachment_id}`}
                >
                  {retryingAttachmentId === run.attachment_id ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                  ) : (
                    <RefreshCw className="h-3.5 w-3.5" aria-hidden />
                  )}
                  Process order document
                </Button>
              ) : null}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function ProceedingIntelligenceSection({
  matterId,
  response,
  isLoading,
  isError,
}: {
  matterId: string;
  response: ProceedingIntelligenceResponse | undefined;
  isLoading: boolean;
  isError: boolean;
}) {
  const orders = response?.orders ?? [];
  const supportedOrders = orders.filter((order) => order.signals.length > 0);
  const pending = response?.pending_compliance_items ?? [];

  return (
    <Card className="lg:col-span-2">
      <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
        <div>
          <CardTitle>Proceeding intelligence</CardTitle>
          <CardDescription>
            Source-backed directions, hearing dates, defects, and compliance items
            extracted from recent order sheets.
          </CardDescription>
        </div>
        {pending.length > 0 ? <StatusBadge status={`${pending.length} pending`} /> : null}
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="grid gap-2 md:grid-cols-3" data-testid="proceeding-loading">
            <div className="h-16 rounded-lg bg-[var(--color-bg-2)]" />
            <div className="h-16 rounded-lg bg-[var(--color-bg-2)]" />
            <div className="h-16 rounded-lg bg-[var(--color-bg-2)]" />
          </div>
        ) : isError ? (
          <p className="text-sm text-[var(--color-danger-500,#c53030)]">
            Proceeding intelligence could not be loaded.
          </p>
        ) : orders.length === 0 ? (
          <EmptyState
            icon={ClipboardList}
            title="No proceeding sheets yet"
            description="Order-sheet intelligence appears after a court sync or manual order import with raw source text."
          />
        ) : supportedOrders.length === 0 ? (
          <div className="rounded-lg border border-[var(--color-line)] bg-[var(--color-bg)] p-3">
            <div className="text-sm font-medium text-[var(--color-ink)]">
              Insufficient source text
            </div>
            <p className="mt-1 text-sm text-[var(--color-mute)]">
              Raw order text is required before CaseOps can extract proceeding
              directions. Summaries are not used for task or deadline creation.
            </p>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="grid gap-2 md:grid-cols-3">
              <ProceedingMetric label="Orders with signals" value={supportedOrders.length} />
              <ProceedingMetric label="Pending compliance" value={pending.length} />
              <ProceedingMetric label="Review state" value="Human review" />
            </div>
            <p className="text-xs leading-relaxed text-[var(--color-mute)]">
              {response?.disclaimer}
            </p>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[760px] border-separate border-spacing-0 text-left text-sm">
                <thead className="text-xs uppercase tracking-[0.06em] text-[var(--color-mute)]">
                  <tr>
                    <th className="border-b border-[var(--color-line)] py-2 pr-3 font-medium">
                      Order
                    </th>
                    <th className="border-b border-[var(--color-line)] px-3 py-2 font-medium">
                      Direction
                    </th>
                    <th className="border-b border-[var(--color-line)] px-3 py-2 font-medium">
                      Due / hearing
                    </th>
                    <th className="border-b border-[var(--color-line)] px-3 py-2 font-medium">
                      Review
                    </th>
                    <th className="border-b border-[var(--color-line)] py-2 pl-3 font-medium">
                      Source
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {supportedOrders.flatMap((order) =>
                    order.signals.slice(0, 4).map((signal) => (
                      <ProceedingSignalRow
                        key={signal.id}
                        matterId={matterId}
                        order={order}
                        signal={signal}
                      />
                    )),
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function ProceedingMetric({
  label,
  value,
}: {
  label: string;
  value: string | number;
}) {
  return (
    <div className="rounded-lg border border-[var(--color-line)] bg-[var(--color-bg)] px-3 py-2">
      <div className="text-xs uppercase tracking-[0.06em] text-[var(--color-mute)]">
        {label}
      </div>
      <div className="mt-1 text-sm font-semibold text-[var(--color-ink)]">
        {value}
      </div>
    </div>
  );
}

function ProceedingSignalRow({
  matterId,
  order,
  signal,
}: {
  matterId: string;
  order: ProceedingOrderIntelligence;
  signal: ProceedingSignal;
}) {
  const dueText = signalDueText(signal);
  return (
    <tr data-testid={`proceeding-signal-${signal.id}`}>
      <td className="border-b border-[var(--color-line)] py-3 pr-3 align-top">
        <div className="font-medium text-[var(--color-ink)]">{order.title}</div>
        <div className="mt-0.5 text-xs text-[var(--color-mute)]">
          {formatDateTime(order.order_date)}
        </div>
      </td>
      <td className="border-b border-[var(--color-line)] px-3 py-3 align-top">
        <div className="font-medium text-[var(--color-ink)]">
          {PROCEEDING_SIGNAL_LABELS[signal.signal_type] ?? signal.signal_type}
        </div>
        <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-[var(--color-mute)]">
          {signal.source_snippet}
        </p>
      </td>
      <td className="border-b border-[var(--color-line)] px-3 py-3 align-top text-sm text-[var(--color-ink-2)]">
        {dueText ?? "Not dated"}
      </td>
      <td className="border-b border-[var(--color-line)] px-3 py-3 align-top">
        <div className="flex flex-col gap-1">
          <StatusBadge status={signal.review_status.replaceAll("_", " ")} />
          <span className="text-xs text-[var(--color-mute)]">
            Confidence {signal.confidence_label}
          </span>
        </div>
      </td>
      <td className="border-b border-[var(--color-line)] py-3 pl-3 align-top">
        <Link
          href={sourceHref(matterId, order)}
          className="text-sm font-medium text-[var(--color-brand-700)] hover:underline"
        >
          View source
        </Link>
        {signal.generated_task_id || signal.generated_deadline_id ? (
          <div className="mt-1 text-xs text-[var(--color-mute)]">
            Linked task/deadline
          </div>
        ) : null}
      </td>
    </tr>
  );
}

function mockSourceHref(matterId: string, question: MockHearingQuestion): string {
  if (question.source_attachment_id) {
    return `/app/matters/${matterId}/documents/${question.source_attachment_id}/view`;
  }
  return `/app/matters/${matterId}/documents`;
}

function coachSourceHref(matterId: string, item: HearingCoachFeedbackItem): string {
  if (item.source_attachment_id) {
    return `/app/matters/${matterId}/documents/${item.source_attachment_id}/view`;
  }
  return `/app/matters/${matterId}/documents`;
}

function activeMockSession(
  response: MockHearingListResponse | undefined,
): MockHearingSession | null {
  const sessions = response?.sessions ?? [];
  return sessions.find((session) => session.status === "active") ?? response?.latest_session ?? null;
}

function currentMockQuestion(session: MockHearingSession | null): MockHearingQuestion | null {
  if (!session || session.status !== "active") return null;
  return (
    session.questions.find((question) => question.id === session.current_question_id) ??
    session.questions.find((question) => question.status === "pending") ??
    null
  );
}

function latestMockResponse(session: MockHearingSession | null) {
  const responses = (session?.questions ?? []).flatMap((question) => question.responses);
  return responses.sort((a, b) => b.created_at.localeCompare(a.created_at))[0] ?? null;
}

function HearingCoachSection({
  matterId,
  mockHearings,
  status,
  report,
  isLoading,
  isError,
  canRun,
  acknowledged,
  isGenerating,
  onAcknowledgedChange,
  onGenerate,
}: {
  matterId: string;
  mockHearings: MockHearingListResponse | undefined;
  status: HearingCoachStatusResponse | undefined;
  report: HearingCoachReportResponse | undefined;
  isLoading: boolean;
  isError: boolean;
  canRun: boolean;
  acknowledged: boolean;
  isGenerating: boolean;
  onAcknowledgedChange: (value: boolean) => void;
  onGenerate: (sessionId: string) => void;
}) {
  const sessionId = status?.latest_session_id ?? activeMockSession(mockHearings)?.id ?? null;
  const responseCount = status?.response_count ?? 0;
  const canGenerate = Boolean(sessionId && acknowledged && canRun && responseCount > 0);
  return (
    <Card className="lg:col-span-2" data-testid="hearing-coach-section">
      <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
        <div>
          <CardTitle>Hearing coach</CardTitle>
          <CardDescription>
            Transcript-first training aid from typed mock-hearing responses; not legal advice.
          </CardDescription>
        </div>
        {responseCount > 0 ? (
          <Button
            type="button"
            size="sm"
            disabled={!canGenerate || isGenerating}
            onClick={() => sessionId && onGenerate(sessionId)}
            data-testid="hearing-coach-generate"
          >
            {isGenerating ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            ) : (
              <BarChart3 className="h-4 w-4" aria-hidden />
            )}
            Generate coach report
          </Button>
        ) : null}
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="grid gap-2 md:grid-cols-3" data-testid="hearing-coach-loading">
            <div className="h-20 rounded-lg bg-[var(--color-bg-2)]" />
            <div className="h-20 rounded-lg bg-[var(--color-bg-2)]" />
            <div className="h-20 rounded-lg bg-[var(--color-bg-2)]" />
          </div>
        ) : isError ? (
          <p className="text-sm text-[var(--color-danger-500,#c53030)]">
            Hearing coach status could not be loaded.
          </p>
        ) : responseCount === 0 ? (
          <EmptyState
            icon={BarChart3}
            title="No typed responses yet"
            description="Start a mock hearing and submit at least one typed response before running the hearing coach."
          />
        ) : (
          <div className="grid gap-4 xl:grid-cols-[0.85fr_1.15fr]">
            <div className="rounded-lg border border-[var(--color-line)] bg-[var(--color-bg)] p-4">
              <div className="flex flex-wrap items-center gap-2">
                <StatusBadge status={status?.status ?? "consent_required"} />
                <span className="text-xs text-[var(--color-mute)]">
                  {responseCount} typed response{responseCount === 1 ? "" : "s"}
                </span>
              </div>
              <p className="mt-3 text-xs leading-relaxed text-[var(--color-mute)]">
                {status?.disclaimer ??
                  "Hearing coach is a transcript-first training aid; not legal advice."}
              </p>
              <label className="mt-4 flex items-start gap-2 text-sm text-[var(--color-ink-2)]">
                <input
                  type="checkbox"
                  className="mt-1 h-4 w-4 rounded border-[var(--color-line)]"
                  checked={acknowledged}
                  onChange={(event) => onAcknowledgedChange(event.target.checked)}
                  data-testid="hearing-coach-consent"
                />
                <span>
                  I acknowledge this report uses typed practice responses and source-linked
                  mock hearing material as a preparation aid for counsel review.
                </span>
              </label>
              {!canRun ? (
                <p className="mt-3 text-xs text-[var(--color-mute)]">
                  A team member with hearing preparation access can generate the report.
                </p>
              ) : null}
              {status?.limitation_notes?.length ? (
                <ul className="mt-4 list-disc space-y-1 pl-5 text-xs text-[var(--color-mute)]">
                  {status.limitation_notes.map((note) => (
                    <li key={note}>{note}</li>
                  ))}
                </ul>
              ) : null}
            </div>

            {report ? (
              <div className="space-y-4" data-testid="hearing-coach-report">
                <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
                  <MockMetric
                    label="Clarity"
                    value={report.metrics.average_clarity_score}
                  />
                  <MockMetric
                    label="Completeness"
                    value={report.metrics.average_completeness_score}
                  />
                  <MockMetric
                    label="Source refs"
                    value={report.metrics.source_reference_used_count}
                  />
                  <MockMetric
                    label="Review flags"
                    value={report.metrics.review_required_count}
                  />
                </div>
                <div className="grid gap-3">
                  {report.feedback_items.map((item) => (
                    <HearingCoachFeedbackRow
                      key={item.response_id}
                      matterId={matterId}
                      item={item}
                    />
                  ))}
                </div>
              </div>
            ) : (
              <div className="rounded-lg border border-[var(--color-line)] bg-white p-4 text-sm text-[var(--color-mute)]">
                A coach report appears here after acknowledgement and generation.
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function HearingCoachFeedbackRow({
  matterId,
  item,
}: {
  matterId: string;
  item: HearingCoachFeedbackItem;
}) {
  return (
    <div
      className="rounded-lg border border-[var(--color-line)] bg-white p-4"
      data-testid="hearing-coach-feedback-item"
    >
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge status={item.review_required ? "review_required" : "supported"} />
        <span className="text-xs text-[var(--color-mute)]">
          Clarity {item.clarity_score} / Completeness {item.completeness_score}
        </span>
      </div>
      <p className="mt-2 text-sm font-medium text-[var(--color-ink)]">
        {item.question_text}
      </p>
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <div>
          <div className="text-xs font-semibold uppercase tracking-[0.06em] text-[var(--color-mute)]">
            Typed response
          </div>
          <p className="mt-1 text-sm text-[var(--color-ink-2)]">
            {item.transcript_excerpt}
          </p>
        </div>
        <div>
          <div className="text-xs font-semibold uppercase tracking-[0.06em] text-[var(--color-mute)]">
            Source quote
          </div>
          <p className="mt-1 text-sm text-[var(--color-ink-2)]">{item.source_quote}</p>
          <Button href={coachSourceHref(matterId, item)} variant="ghost" size="sm" className="mt-2">
            View source
          </Button>
        </div>
      </div>
      <dl className="mt-3 grid gap-2 text-xs text-[var(--color-mute)] md:grid-cols-2">
        <MockFact
          label="Answered question"
          value={item.answered_question ? "Yes" : "Needs direct answer"}
        />
        <MockFact
          label="Source reference"
          value={item.source_reference_used ? "Present" : "Missing"}
        />
        <MockFact
          label="Unsupported assertions"
          value={String(item.unsupported_assertion_count)}
        />
        <MockFact label="Contradictions" value={String(item.contradiction_count)} />
        <MockFact
          label="Exhibit reference"
          value={item.missing_exhibit_reference ? "Missing" : "Present"}
        />
        <MockFact
          label="Response length"
          value={item.overlong_response_marker ? "Condense" : "Within range"}
        />
      </dl>
      <ul className="mt-3 list-disc space-y-1 pl-5 text-xs text-[var(--color-mute)]">
        {item.improvement_checklist.map((note) => (
          <li key={note}>{note}</li>
        ))}
      </ul>
    </div>
  );
}

function MockHearingSection({
  matterId,
  response,
  isLoading,
  isError,
  canRun,
  responseDraft,
  isStarting,
  isSubmitting,
  isCompleting,
  onStart,
  onResponseDraftChange,
  onSubmit,
  onComplete,
}: {
  matterId: string;
  response: MockHearingListResponse | undefined;
  isLoading: boolean;
  isError: boolean;
  canRun: boolean;
  responseDraft: string;
  isStarting: boolean;
  isSubmitting: boolean;
  isCompleting: boolean;
  onStart: () => void;
  onResponseDraftChange: (value: string) => void;
  onSubmit: (sessionId: string, questionId: string | null) => void;
  onComplete: (sessionId: string) => void;
}) {
  const session = activeMockSession(response);
  const question = currentMockQuestion(session);
  const latestResponse = latestMockResponse(session);
  const scorecard = session?.scorecard;
  return (
    <Card className="lg:col-span-2" data-testid="mock-hearing-section">
      <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
        <div>
          <CardTitle>Mock hearing</CardTitle>
          <CardDescription>
            Text practice from affidavit question banks with source-linked feedback; not
            legal advice.
          </CardDescription>
        </div>
        {canRun ? (
          <Button
            type="button"
            size="sm"
            disabled={isStarting}
            onClick={onStart}
            data-testid="mock-hearing-start"
          >
            {isStarting ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            ) : (
              <PlayCircle className="h-4 w-4" aria-hidden />
            )}
            Start session
          </Button>
        ) : null}
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="grid gap-2 md:grid-cols-3" data-testid="mock-hearing-loading">
            <div className="h-20 rounded-lg bg-[var(--color-bg-2)]" />
            <div className="h-20 rounded-lg bg-[var(--color-bg-2)]" />
            <div className="h-20 rounded-lg bg-[var(--color-bg-2)]" />
          </div>
        ) : isError ? (
          <p className="text-sm text-[var(--color-danger-500,#c53030)]">
            Mock hearing sessions could not be loaded.
          </p>
        ) : !session ? (
          <EmptyState
            icon={HelpCircle}
            title="No mock hearing sessions"
            description="Generate affidavit intelligence first, then start a text practice session from the source-backed question bank."
          />
        ) : (
          <div className="grid gap-4 xl:grid-cols-[1fr_0.8fr]">
            <div className="rounded-lg border border-[var(--color-line)] bg-[var(--color-bg)] p-4">
              <div className="flex flex-wrap items-center gap-2">
                <StatusBadge status={session.status} />
                <StatusBadge status={session.review_status} />
                <span className="text-xs text-[var(--color-mute)]">
                  {session.questions.length} source-backed questions
                </span>
              </div>
              <p className="mt-3 text-xs leading-relaxed text-[var(--color-mute)]">
                {session.disclaimer}
              </p>
              {question ? (
                <div className="mt-4" data-testid="mock-hearing-current-question">
                  <div className="text-xs uppercase tracking-[0.06em] text-[var(--color-mute)]">
                    Question {question.turn_index + 1}
                  </div>
                  <p className="mt-1 text-base font-semibold text-[var(--color-ink)]">
                    {question.question_text}
                  </p>
                  <p className="mt-2 text-sm text-[var(--color-mute)]">{question.reason}</p>
                  <div className="mt-3 rounded-md border border-[var(--color-line)] bg-white p-3">
                    <div className="text-xs font-semibold uppercase tracking-[0.06em] text-[var(--color-mute)]">
                      Source quote
                    </div>
                    <p className="mt-1 text-sm text-[var(--color-ink-2)]">
                      {question.source_quote}
                    </p>
                    <Button
                      href={mockSourceHref(matterId, question)}
                      variant="ghost"
                      size="sm"
                      className="mt-2"
                    >
                      View source
                    </Button>
                  </div>
                  <label className="mt-4 block text-sm font-medium text-[var(--color-ink)]">
                    Typed response
                  </label>
                  <Textarea
                    className="mt-1 min-h-28"
                    value={responseDraft}
                    onChange={(event) => onResponseDraftChange(event.target.value)}
                    placeholder="Record the answer exactly as prepared."
                    data-testid="mock-hearing-response-input"
                  />
                  <div className="mt-3 flex flex-wrap gap-2">
                    <Button
                      type="button"
                      size="sm"
                      disabled={isSubmitting || responseDraft.trim().length === 0}
                      onClick={() => onSubmit(session.id, question.id)}
                      data-testid="mock-hearing-submit-response"
                    >
                      {isSubmitting ? (
                        <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                      ) : (
                        <Send className="h-4 w-4" aria-hidden />
                      )}
                      Submit response
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      disabled={isCompleting}
                      onClick={() => onComplete(session.id)}
                      data-testid="mock-hearing-complete"
                    >
                      <CheckCircle2 className="h-4 w-4" aria-hidden />
                      Complete
                    </Button>
                  </div>
                </div>
              ) : (
                <div className="mt-4 rounded-md border border-[var(--color-line)] bg-white p-3">
                  <div className="text-sm font-medium text-[var(--color-ink)]">
                    All questions answered
                  </div>
                  <p className="mt-1 text-sm text-[var(--color-mute)]">
                    Complete the session to freeze the preparation report.
                  </p>
                  {session.status === "active" ? (
                    <Button
                      type="button"
                      size="sm"
                      className="mt-3"
                      disabled={isCompleting}
                      onClick={() => onComplete(session.id)}
                      data-testid="mock-hearing-complete"
                    >
                      <CheckCircle2 className="h-4 w-4" aria-hidden />
                      Complete
                    </Button>
                  ) : null}
                </div>
              )}
            </div>

            <div className="space-y-4">
              {scorecard ? (
                <div
                  className="grid grid-cols-2 gap-2"
                  data-testid="mock-hearing-scorecard"
                >
                  <MockMetric label="Answered" value={scorecard.answered_questions} />
                  <MockMetric label="Review flags" value={scorecard.review_required_count} />
                  <MockMetric label="New assertions" value={scorecard.unsupported_assertion_count} />
                  <MockMetric
                    label="Document gaps"
                    value={scorecard.missing_document_reference_count}
                  />
                </div>
              ) : null}
              {latestResponse ? (
                <div
                  className="rounded-lg border border-[var(--color-line)] bg-white p-4"
                  data-testid="mock-hearing-feedback"
                >
                  <div className="mb-2 flex flex-wrap items-center gap-2">
                    <StatusBadge status={latestResponse.confidence_label} />
                    {latestResponse.review_required ? (
                      <StatusBadge status="review_required" />
                    ) : null}
                  </div>
                  <p className="text-sm font-medium text-[var(--color-ink)]">
                    {latestResponse.feedback_text}
                  </p>
                  <dl className="mt-3 grid gap-2 text-xs text-[var(--color-mute)]">
                    <MockFact
                      label="Answered question"
                      value={latestResponse.answered_question ? "Yes" : "Needs work"}
                    />
                    <MockFact
                      label="Consistent with affidavit"
                      value={latestResponse.consistency_with_affidavit ? "Yes" : "Review"}
                    />
                    <MockFact
                      label="Unsupported assertion"
                      value={latestResponse.unsupported_assertion_added ? "Flagged" : "None"}
                    />
                    <MockFact
                      label="Document reference"
                      value={
                        latestResponse.missing_document_reference ? "Missing" : "Present"
                      }
                    />
                  </dl>
                </div>
              ) : (
                <div className="rounded-lg border border-[var(--color-line)] bg-white p-4 text-sm text-[var(--color-mute)]">
                  Feedback appears after the first typed response.
                </div>
              )}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function MockMetric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-lg border border-[var(--color-line)] bg-white px-3 py-2">
      <div className="text-xs uppercase tracking-[0.06em] text-[var(--color-mute)]">
        {label}
      </div>
      <div className="mt-1 text-sm font-semibold text-[var(--color-ink)]">{value}</div>
    </div>
  );
}

function MockFact({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt>{label}</dt>
      <dd className="font-medium text-[var(--color-ink-2)]">{value}</dd>
    </div>
  );
}

function HearingOutlookSync({
  hearing,
  sync,
  hasConnection,
  isPending,
  onSync,
}: {
  hearing: WorkspaceHearing;
  sync: CalendarEventSyncRecord | undefined;
  hasConnection: boolean;
  isPending: boolean;
  onSync: () => void;
}) {
  const lastSynced = sync?.last_synced_at
    ? new Date(sync.last_synced_at).toLocaleString(undefined, {
        day: "2-digit",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      })
    : null;
  // BUG-044 (Hari 2026-05-11): if the user has no Outlook connection,
  // the Sync button always 409s. Render a Connect-Outlook link
  // instead — the action the user actually needs. Disable the broken
  // action; do not rely on toast copy alone.
  if (!hasConnection) {
    return (
      <div
        className="mt-3 flex flex-wrap items-center gap-2 text-xs"
        data-testid={`hearing-outlook-status-${hearing.id}`}
      >
        <Button
          type="button"
          size="sm"
          variant="outline"
          href="/app/calendar"
          data-testid={`hearing-outlook-connect-${hearing.id}`}
        >
          <CalendarCheck className="h-3.5 w-3.5" aria-hidden /> Connect Outlook
        </Button>
        <span className="text-[var(--color-mute)]">
          Connect Outlook to sync this hearing.
        </span>
      </div>
    );
  }
  return (
    <div
      className="mt-3 flex flex-wrap items-center gap-2 text-xs"
      data-testid={`hearing-outlook-status-${hearing.id}`}
    >
      <Button
        type="button"
        size="sm"
        variant="outline"
        disabled={isPending}
        onClick={onSync}
        data-testid={`hearing-outlook-sync-${hearing.id}`}
      >
        {isPending ? (
          <>
            <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> Syncing
          </>
        ) : (
          <>
            <CalendarCheck className="h-3.5 w-3.5" aria-hidden /> Sync to Outlook
          </>
        )}
      </Button>
      {sync ? (
        <span className="text-[var(--color-mute)]">
          {sync.sync_status}
          {lastSynced ? ` · ${lastSynced}` : ""}
          {sync.last_error ? ` · ${sync.last_error}` : ""}
        </span>
      ) : (
        <span className="text-[var(--color-mute)]">Not synced</span>
      )}
    </div>
  );
}

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
