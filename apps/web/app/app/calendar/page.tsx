"use client";

// Phase B / J08 / M08 / US-022 / US-023 / FT-042-043 — unified calendar.
//
// Slice 1 (shipped 2026-04-23): month grid + tenant-scoped event feed
// across hearings + tasks + matter_deadlines.
// Slice 2b (this file): adds Week + Day views and an authenticated .ics export.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CalendarCheck,
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  Download,
  ExternalLink,
  Gavel,
  Inbox,
  ListTodo,
  Mail,
  RefreshCw,
  Timer,
} from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import {
  fetchCalendarEvents,
  fetchCalendarSyncStatus,
  fetchGmailMailboxStatus,
  extractEmailInvitationCandidates,
  importRecentGmailMessages,
  listCalendarConnections,
  listEmailInvitationCandidates,
  revokeGmailMailboxConnection,
  revokeCalendarConnection,
  reviewEmailInvitationCandidate,
  startGmailMailboxConnection,
  startGmailWatch,
  startGoogleCalendarConnection,
  startOutlookCalendarConnection,
  syncGoogleCalendarVisibleRange,
  syncOutlookVisibleRange,
} from "@/lib/api/endpoints";
import type {
  CalendarEventKind,
  CalendarEventRecord,
} from "@/lib/api/schemas";
import type { EmailInvitationCandidateRecord } from "@/lib/api/endpoints";
import { API_BASE_URL } from "@/lib/api/config";
import { useCapability } from "@/lib/capabilities";
import { cn } from "@/lib/cn";

type ViewMode = "month" | "week" | "day";

const KIND_ICON: Record<CalendarEventKind, typeof Gavel> = {
  hearing: Gavel,
  task: ListTodo,
  deadline: Timer,
};

const KIND_DOT: Record<CalendarEventKind, string> = {
  hearing: "bg-[var(--color-accent)]",
  task: "bg-[var(--color-info-500)]",
  deadline: "bg-[var(--color-warning-500)]",
};

function startOfMonth(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), 1);
}

function startOfWeekMonday(d: Date): Date {
  // Indian court week is Mon-Fri so Monday-first matches user mental model.
  const out = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const offsetToMonday = (out.getDay() + 6) % 7;
  out.setDate(out.getDate() - offsetToMonday);
  return out;
}

function isoDate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function formatDateTime(value: string | null): string {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleString(undefined, {
      day: "2-digit",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return value;
  }
}

function candidateStatusLabel(status: EmailInvitationCandidateRecord["status"]): string {
  switch (status) {
    case "needs_review":
      return "Needs review";
    case "approved_created":
      return "Created";
    case "rejected":
      return "Rejected";
    case "duplicate_skipped":
      return "Duplicate skipped";
    default:
      return status;
  }
}

function buildMonthGrid(monthStart: Date): Date[] {
  const firstWeekday = monthStart.getDay();
  const offsetToMonday = (firstWeekday + 6) % 7;
  const gridStart = new Date(monthStart);
  gridStart.setDate(monthStart.getDate() - offsetToMonday);
  return Array.from({ length: 42 }, (_, i) => {
    const d = new Date(gridStart);
    d.setDate(gridStart.getDate() + i);
    return d;
  });
}

const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];
const WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export default function CalendarPage() {
  const [view, setView] = useState<ViewMode>("month");
  const [cursor, setCursor] = useState<Date>(() => new Date());
  const [outlookMessage, setOutlookMessage] = useState<string | null>(null);
  const [googleMessage, setGoogleMessage] = useState<string | null>(null);
  const [gmailMessage, setGmailMessage] = useState<string | null>(null);
  const queryClient = useQueryClient();
  const canSyncCalendar = useCapability("calendar:sync");

  // Compute the [from, to] range for the current view. The same
  // /api/calendar/events endpoint serves all three; only the slice
  // size changes.
  const { rangeFrom, rangeTo, label } = useMemo(() => {
    if (view === "month") {
      const monthStart = startOfMonth(cursor);
      const grid = buildMonthGrid(monthStart);
      return {
        rangeFrom: grid[0],
        rangeTo: grid[grid.length - 1],
        label: `${MONTH_NAMES[monthStart.getMonth()]} ${monthStart.getFullYear()}`,
      };
    }
    if (view === "week") {
      const weekStart = startOfWeekMonday(cursor);
      const weekEnd = new Date(weekStart);
      weekEnd.setDate(weekStart.getDate() + 6);
      const sameMonth = weekStart.getMonth() === weekEnd.getMonth();
      const labelText = sameMonth
        ? `${weekStart.getDate()}–${weekEnd.getDate()} ${MONTH_NAMES[weekEnd.getMonth()]} ${weekEnd.getFullYear()}`
        : `${weekStart.getDate()} ${MONTH_NAMES[weekStart.getMonth()].slice(0, 3)} – ${weekEnd.getDate()} ${MONTH_NAMES[weekEnd.getMonth()].slice(0, 3)} ${weekEnd.getFullYear()}`;
      return { rangeFrom: weekStart, rangeTo: weekEnd, label: labelText };
    }
    // day
    const day = new Date(cursor.getFullYear(), cursor.getMonth(), cursor.getDate());
    return {
      rangeFrom: day,
      rangeTo: day,
      label: `${WEEKDAY_LABELS[(day.getDay() + 6) % 7]}, ${day.getDate()} ${MONTH_NAMES[day.getMonth()]} ${day.getFullYear()}`,
    };
  }, [view, cursor]);

  const query = useQuery({
    queryKey: ["calendar", view, isoDate(rangeFrom), isoDate(rangeTo)],
    queryFn: () =>
      fetchCalendarEvents({ from: isoDate(rangeFrom), to: isoDate(rangeTo) }),
  });
  const connectionsQuery = useQuery({
    queryKey: ["calendar", "connections"],
    queryFn: listCalendarConnections,
  });
  const syncStatusQuery = useQuery({
    queryKey: ["calendar", "sync-status"],
    queryFn: fetchCalendarSyncStatus,
  });
  const emailCandidatesQuery = useQuery({
    queryKey: ["calendar", "email-invitation-candidates"],
    queryFn: () => listEmailInvitationCandidates({ limit: 20 }),
  });
  const gmailStatusQuery = useQuery({
    queryKey: ["mailbox", "gmail", "status"],
    queryFn: fetchGmailMailboxStatus,
  });
  const extractCandidatesMutation = useMutation({
    mutationFn: () => extractEmailInvitationCandidates({ limit: 50 }),
    onSuccess: (result) => {
      setOutlookMessage(
        `Reviewed ${result.examined_count} imported emails; ${result.created_count} candidates added and ${result.duplicate_count} duplicates skipped.`,
      );
      void queryClient.invalidateQueries({
        queryKey: ["calendar", "email-invitation-candidates"],
      });
      void queryClient.invalidateQueries({ queryKey: ["calendar", "sync-status"] });
    },
    onError: (error) => setOutlookMessage(String(error)),
  });
  const reviewCandidateMutation = useMutation({
    mutationFn: reviewEmailInvitationCandidate,
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["calendar", "email-invitation-candidates"],
      });
      void queryClient.invalidateQueries({ queryKey: ["calendar"] });
    },
    onError: (error) => setOutlookMessage(String(error)),
  });
  const startOutlookMutation = useMutation({
    mutationFn: startOutlookCalendarConnection,
    onSuccess: (result) => {
      if (result.auth_url) {
        window.location.assign(result.auth_url);
        return;
      }
      setOutlookMessage(
        result.unavailable_reason ?? "Outlook calendar sync is unavailable.",
      );
    },
    onError: (error) => setOutlookMessage(String(error)),
  });
  const startGoogleMutation = useMutation({
    mutationFn: startGoogleCalendarConnection,
    onSuccess: (result) => {
      if (result.auth_url) {
        window.location.assign(result.auth_url);
        return;
      }
      setGoogleMessage(
        result.unavailable_reason ?? "Google Calendar sync is unavailable.",
      );
    },
    onError: (error) => setGoogleMessage(String(error)),
  });
  const revokeOutlookMutation = useMutation({
    mutationFn: revokeCalendarConnection,
    onSuccess: () => {
      setOutlookMessage("Outlook connection revoked.");
      void queryClient.invalidateQueries({ queryKey: ["calendar", "connections"] });
      void queryClient.invalidateQueries({ queryKey: ["calendar", "sync-status"] });
    },
    onError: (error) => setOutlookMessage(String(error)),
  });
  const revokeGoogleMutation = useMutation({
    mutationFn: revokeCalendarConnection,
    onSuccess: () => {
      setGoogleMessage("Google Calendar connection revoked.");
      void queryClient.invalidateQueries({ queryKey: ["calendar", "connections"] });
      void queryClient.invalidateQueries({ queryKey: ["calendar", "sync-status"] });
    },
    onError: (error) => setGoogleMessage(String(error)),
  });
  const startGmailMutation = useMutation({
    mutationFn: startGmailMailboxConnection,
    onSuccess: (result) => {
      if (result.auth_url) {
        window.location.assign(result.auth_url);
        return;
      }
      setGmailMessage(result.unavailable_reason ?? "Gmail sync is unavailable.");
    },
    onError: (error) => setGmailMessage(String(error)),
  });
  const importGmailMutation = useMutation({
    mutationFn: () => importRecentGmailMessages({ limit: 25 }),
    onSuccess: (result) => {
      setGmailMessage(
        `Imported ${result.summary.imported}, unmatched ${result.summary.unmatched}, duplicates ${result.summary.duplicate}, attachment candidates ${result.summary.attachment_candidates}.`,
      );
      void queryClient.invalidateQueries({ queryKey: ["mailbox", "gmail", "status"] });
      void queryClient.invalidateQueries({
        queryKey: ["calendar", "email-invitation-candidates"],
      });
    },
    onError: (error) => setGmailMessage(String(error)),
  });
  const startGmailWatchMutation = useMutation({
    mutationFn: startGmailWatch,
    onSuccess: (result) => {
      setGmailMessage(
        result.watch_started
          ? "Gmail webhook watch started."
          : `Gmail webhook config missing: ${result.missing_config_names.join(", ")}`,
      );
      void queryClient.invalidateQueries({ queryKey: ["mailbox", "gmail", "status"] });
    },
    onError: (error) => setGmailMessage(String(error)),
  });
  const revokeGmailMutation = useMutation({
    mutationFn: revokeGmailMailboxConnection,
    onSuccess: () => {
      setGmailMessage("Gmail connection revoked.");
      void queryClient.invalidateQueries({ queryKey: ["mailbox", "gmail", "status"] });
    },
    onError: (error) => setGmailMessage(String(error)),
  });

  // BUG-039 (Hari 2026-05-09) — bounded manual bulk sync of the
  // currently-rendered date window to Outlook. Posts the same `from`
  // / `to` dates the events query uses; relies on the backend's
  // 92-day guard + tenant + visibility filters. The button is only
  // rendered for users with `calendar:sync` AND a connected Outlook
  // account (see button branch below); it is not the durable
  // automation track — that remains blocked pending provider approval.
  const syncRangeMutation = useMutation({
    mutationFn: () =>
      syncOutlookVisibleRange({
        from: isoDate(rangeFrom),
        to: isoDate(rangeTo),
      }),
    onSuccess: (result) => {
      const summary = `Synced ${result.created} new, ${result.updated} updated, ${result.failed} failed, ${result.skipped} skipped (${result.examined} examined).`;
      setOutlookMessage(summary);
      void queryClient.invalidateQueries({ queryKey: ["calendar", "sync-status"] });
    },
    onError: (error) => setOutlookMessage(String(error)),
  });
  const syncGoogleRangeMutation = useMutation({
    mutationFn: () =>
      syncGoogleCalendarVisibleRange({
        from: isoDate(rangeFrom),
        to: isoDate(rangeTo),
      }),
    onSuccess: (result) => {
      const summary = `Synced ${result.created} new, ${result.updated} updated, ${result.failed} failed, ${result.skipped} skipped (${result.examined} examined).`;
      setGoogleMessage(summary);
      void queryClient.invalidateQueries({ queryKey: ["calendar", "sync-status"] });
    },
    onError: (error) => setGoogleMessage(String(error)),
  });

  const eventsByDay = useMemo(() => {
    const map = new Map<string, CalendarEventRecord[]>();
    for (const e of query.data?.events ?? []) {
      const list = map.get(e.occurs_on) ?? [];
      list.push(e);
      map.set(e.occurs_on, list);
    }
    return map;
  }, [query.data]);

  const today = new Date();
  const todayKey = isoDate(today);
  const syncStatus = syncStatusQuery.data;
  const durableAutomation = syncStatus?.capabilities.durable_automation;
  const durableAutomationLabel =
    durableAutomation === "caseops_to_outlook_hearings_ready"
      ? "CaseOps-to-Outlook hearing sync ready"
      : "Pending provider approval";
  const providerConfigs = syncStatus?.provider_config ?? [];
  const outlookProviderConfig =
    providerConfigs.find((item) => item.provider === "outlook") ?? null;
  const googleProviderConfig =
    providerConfigs.find((item) => item.provider === "google_calendar") ?? null;
  const missingConfigNames = outlookProviderConfig?.missing_config_names ?? [];
  const googleMissingConfigNames =
    googleProviderConfig?.missing_config_names ?? [
      "GOOGLE_CALENDAR_CLIENT_ID",
      "GOOGLE_CALENDAR_CLIENT_SECRET",
      "GOOGLE_CALENDAR_REDIRECT_URI",
    ];
  const googleConfigured = googleProviderConfig?.configured ?? false;
  const calendarConnections =
    syncStatus?.connections ?? connectionsQuery.data?.connections ?? [];
  const outlookConnections = calendarConnections.filter(
    (connection) => connection.provider === "outlook",
  );
  const googleConnections = calendarConnections.filter(
    (connection) => connection.provider === "google_calendar",
  );
  const gmailStatus = gmailStatusQuery.data;
  const connectedGmailConnection =
    gmailStatus?.connections.find((connection) => connection.status === "connected") ??
    null;
  const gmailConfigured = gmailStatus?.configured ?? false;
  const gmailWebhookConfigured = gmailStatus?.webhook_configured ?? false;
  const gmailMissingConfigNames =
    gmailStatus?.missing_config_names ?? [
      "GMAIL_CLIENT_ID",
      "GMAIL_CLIENT_SECRET",
      "GMAIL_REDIRECT_URI",
    ];
  const gmailMissingWebhookConfigNames =
    gmailStatus?.missing_webhook_config_names ?? [
      "GMAIL_PUBSUB_TOPIC",
      "GMAIL_WEBHOOK_VERIFICATION_TOKEN",
    ];
  const connectedOutlookConnection =
    outlookConnections.find((connection) => connection.status === "connected") ?? null;
  const connectedGoogleConnection =
    googleConnections.find((connection) => connection.status === "connected") ?? null;
  const conflictSummary = syncStatus?.conflict_summary ?? null;
  const conflictCandidates = syncStatus?.conflict_candidates ?? [];
  const emailCandidates = emailCandidatesQuery.data?.candidates ?? [];
  const pendingEmailCandidateCount = emailCandidatesQuery.data?.pending_count ?? 0;
  const duplicateEmailCandidateCount = emailCandidatesQuery.data?.duplicate_count ?? 0;

  const navigate = (delta: 1 | -1) => {
    setCursor((c) => {
      const next = new Date(c);
      if (view === "month") next.setMonth(c.getMonth() + delta);
      else if (view === "week") next.setDate(c.getDate() + delta * 7);
      else next.setDate(c.getDate() + delta);
      return next;
    });
  };

  const icsHref = `${API_BASE_URL}/api/calendar/events.ics?from=${isoDate(rangeFrom)}&to=${isoDate(rangeTo)}`;

  return (
    <div className="flex flex-col gap-5">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-[var(--color-ink)]">
            Calendar
          </h1>
          <p className="mt-1 text-xs text-[var(--color-mute)]">
            Hearings, task due dates, and deadlines across all matters in
            this workspace.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {/* View toggle */}
          <div
            className="inline-flex items-center rounded-md border border-[var(--color-line-2)] p-0.5"
            role="tablist"
            aria-label="Calendar view"
          >
            {(["month", "week", "day"] as const).map((v) => (
              <button
                key={v}
                type="button"
                role="tab"
                aria-selected={view === v}
                onClick={() => setView(v)}
                data-testid={`calendar-view-${v}`}
                className={cn(
                  "h-7 px-3 text-xs font-medium capitalize",
                  view === v
                    ? "rounded-sm bg-[var(--color-ink)] text-white"
                    : "text-[var(--color-mute)] hover:text-[var(--color-ink)]",
                )}
              >
                {v}
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={() => navigate(-1)}
            className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-[var(--color-line-2)] text-[var(--color-mute)] hover:text-[var(--color-ink)]"
            aria-label="Previous"
            data-testid="calendar-prev-month"
          >
            <ChevronLeft className="h-4 w-4" aria-hidden />
          </button>
          <div
            className="min-w-[12rem] text-center text-sm font-medium text-[var(--color-ink)]"
            data-testid="calendar-month-label"
          >
            {label}
          </div>
          <button
            type="button"
            onClick={() => navigate(1)}
            className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-[var(--color-line-2)] text-[var(--color-mute)] hover:text-[var(--color-ink)]"
            aria-label="Next"
            data-testid="calendar-next-month"
          >
            <ChevronRight className="h-4 w-4" aria-hidden />
          </button>
          <button
            type="button"
            onClick={() => setCursor(new Date())}
            className="ml-2 inline-flex h-8 items-center rounded-md border border-[var(--color-line-2)] px-3 text-xs font-medium text-[var(--color-ink)] hover:bg-[var(--color-line-1)]"
            data-testid="calendar-today"
          >
            Today
          </button>
          {/* iCal export: authenticated visible-range download.
              Direct provider subscription needs a public/tokenized feed
              or OAuth connector. */}
          <a
            href={icsHref}
            className="ml-2 inline-flex h-8 items-center gap-1.5 rounded-md border border-[var(--color-line-2)] px-3 text-xs font-medium text-[var(--color-ink)] hover:bg-[var(--color-line-1)]"
            data-testid="calendar-ics-download"
            download="caseops-calendar.ics"
          >
            <Download className="h-3.5 w-3.5" aria-hidden />
            Export .ics
          </a>
        </div>
      </header>

      {/* Legend */}
      <div className="flex items-center gap-4 text-xs text-[var(--color-mute)]">
        {(["hearing", "task", "deadline"] as const).map((kind) => {
          const Icon = KIND_ICON[kind];
          return (
            <span key={kind} className="inline-flex items-center gap-1.5">
              <span className={cn("h-2 w-2 rounded-full", KIND_DOT[kind])} />
              <Icon className="h-3.5 w-3.5" aria-hidden />
              <span className="capitalize">{kind}s</span>
            </span>
          );
        })}
      </div>

      <section
        className="rounded-lg border border-[var(--color-line-2)] bg-white px-4 py-3"
        data-testid="calendar-outlook-panel"
      >
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-sm font-semibold text-[var(--color-ink)]">
              <CalendarCheck className="h-4 w-4" aria-hidden />
              Outlook calendar
            </div>
            <div className="mt-1 text-xs text-[var(--color-mute)]">
              {connectionsQuery.isPending ? (
                "Checking connection..."
              ) : connectionsQuery.data?.provider_available === false ? (
                connectionsQuery.data.unavailable_reason ??
                "Microsoft Graph configuration required."
              ) : connectedOutlookConnection ? (
                <>
                  Connected as{" "}
                  {connectedOutlookConnection.display_email ?? "Outlook account"}
                  {connectedOutlookConnection.last_sync_at
                    ? ` · Last sync ${formatDateTime(
                        connectedOutlookConnection.last_sync_at,
                      )}`
                    : ""}
                </>
              ) : (
                "Manual hearing sync is available after an Outlook connection is added."
              )}
            </div>
            <div className="mt-1 text-xs text-[var(--color-mute)]">
              Durable provider automation: {durableAutomationLabel}.
              {syncStatusQuery.data?.syncs.find((s) => s.sync_status === "failed")?.last_error
                ? ` Latest error: ${
                    syncStatusQuery.data.syncs.find((s) => s.sync_status === "failed")
                      ?.last_error
                  }`
                : ""}
            </div>
            {outlookMessage ? (
              <div className="mt-1 text-xs text-[var(--color-warning-700,#8a5a00)]">
                {outlookMessage}
              </div>
            ) : null}
            {syncStatus ? (
              <div
                className="mt-3 grid gap-2 text-xs text-[var(--color-ink-2)] sm:grid-cols-2 lg:grid-cols-4"
                data-testid="calendar-sync-status-panel"
              >
                <div>
                  <div className="font-medium text-[var(--color-ink)]">Sync mode</div>
                  <div>Manual visible-range sync</div>
                </div>
                <div>
                  <div className="font-medium text-[var(--color-ink)]">Durable sync</div>
                  <div>{durableAutomationLabel}</div>
                </div>
                <div>
                  <div className="font-medium text-[var(--color-ink)]">Reminder delivery</div>
                  <div>
                    {syncStatus.notification_delivery === "wtd_5_3_foundation_available"
                      ? "Durable foundation available"
                      : syncStatus.notification_delivery}
                  </div>
                </div>
                <div>
                  <div className="font-medium text-[var(--color-ink)]">Email invitations</div>
                  <div>
                    {syncStatus.capabilities.email_invitation_candidates ===
                    "review_queue_available"
                      ? "Review queue available"
                      : "Review queue pending"}
                  </div>
                </div>
              </div>
            ) : null}
            {missingConfigNames.length > 0 ? (
              <div
                className="mt-2 text-xs text-[var(--color-mute)]"
                data-testid="calendar-provider-config-status"
              >
                Missing Outlook config: {missingConfigNames.join(", ")}
              </div>
            ) : null}
            {conflictSummary ? (
              <div
                className="mt-3 text-xs text-[var(--color-ink-2)]"
                data-testid="calendar-conflict-status"
              >
                <div className="font-medium text-[var(--color-ink)]">
                  Conflict review:{" "}
                  {conflictSummary.has_conflicts
                    ? `${conflictSummary.candidate_count} candidate${
                        conflictSummary.candidate_count === 1 ? "" : "s"
                      }`
                    : "no candidates"}
                </div>
                {conflictSummary.changed_event_detection ===
                "unsupported_no_provider_snapshot" ? (
                  <div className="text-[var(--color-mute)]">
                    Changed title/time detection needs provider snapshots and is not
                    automated here.
                  </div>
                ) : null}
                {conflictCandidates.length > 0 ? (
                  <ul className="mt-1 space-y-1">
                    {conflictCandidates.slice(0, 3).map((candidate) => (
                      <li key={candidate.id}>
                        {candidate.duplicate_count} CaseOps items reference Outlook
                        event {candidate.provider_event_id}; review before another
                        manual sync.
                      </li>
                    ))}
                  </ul>
                ) : null}
              </div>
            ) : null}
            <div
              className="mt-4 border-t border-[var(--color-line-2)] pt-3 text-xs text-[var(--color-ink-2)]"
              data-testid="calendar-email-candidates-panel"
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <div className="font-medium text-[var(--color-ink)]">
                    Email invitation candidates
                  </div>
                  <div className="text-[var(--color-mute)]">
                    Review imported email candidates before creating internal
                    CaseOps calendar items. External provider sync is not used.
                  </div>
                </div>
                {canSyncCalendar ? (
                  <button
                    type="button"
                    onClick={() => extractCandidatesMutation.mutate()}
                    disabled={extractCandidatesMutation.isPending}
                    className="inline-flex h-8 items-center rounded-md border border-[var(--color-line-2)] px-3 text-xs font-medium text-[var(--color-ink)] hover:bg-[var(--color-line-1)] disabled:opacity-60"
                    data-testid="calendar-email-candidates-extract"
                  >
                    {extractCandidatesMutation.isPending
                      ? "Scanning..."
                      : "Scan imported emails"}
                  </button>
                ) : null}
              </div>
              <div className="mt-2 text-[var(--color-mute)]">
                {emailCandidatesQuery.isPending
                  ? "Loading candidates..."
                  : `${pendingEmailCandidateCount} needs review, ${duplicateEmailCandidateCount} duplicate skipped.`}
              </div>
              {emailCandidates.length > 0 ? (
                <ul className="mt-2 divide-y divide-[var(--color-line-2)]">
                  {emailCandidates.slice(0, 4).map((candidate) => (
                    <li key={candidate.id} className="py-2">
                      <div className="flex flex-wrap items-start justify-between gap-2">
                        <div className="min-w-0">
                          <div className="font-medium text-[var(--color-ink)]">
                            {candidate.detected_title}
                          </div>
                          <div className="text-[var(--color-mute)]">
                            {candidate.matter_code} ·{" "}
                            {formatDateTime(candidate.detected_start_at)}
                            {candidate.detected_location
                              ? ` · ${candidate.detected_location}`
                              : ""}
                          </div>
                          <div className="mt-1">
                            {candidateStatusLabel(candidate.status)} ·{" "}
                            {candidate.confidence_band} confidence
                          </div>
                          {candidate.source_preview ? (
                            <div className="mt-1 text-[var(--color-mute)]">
                              {candidate.source_preview}
                            </div>
                          ) : null}
                        </div>
                        {candidate.status === "needs_review" && canSyncCalendar ? (
                          <div className="flex shrink-0 items-center gap-1.5">
                            <button
                              type="button"
                              onClick={() =>
                                reviewCandidateMutation.mutate({
                                  candidateId: candidate.id,
                                  action: "approve",
                                })
                              }
                              disabled={reviewCandidateMutation.isPending}
                              className="inline-flex h-7 items-center rounded-md bg-[var(--color-ink)] px-2.5 text-xs font-medium text-white hover:bg-[var(--color-ink-2)] disabled:opacity-60"
                              data-testid={`calendar-email-candidate-approve-${candidate.id}`}
                            >
                              Approve
                            </button>
                            <button
                              type="button"
                              onClick={() =>
                                reviewCandidateMutation.mutate({
                                  candidateId: candidate.id,
                                  action: "reject",
                                })
                              }
                              disabled={reviewCandidateMutation.isPending}
                              className="inline-flex h-7 items-center rounded-md border border-[var(--color-line-2)] px-2.5 text-xs font-medium text-[var(--color-ink)] hover:bg-[var(--color-line-1)] disabled:opacity-60"
                              data-testid={`calendar-email-candidate-reject-${candidate.id}`}
                            >
                              Reject
                            </button>
                          </div>
                        ) : null}
                      </div>
                    </li>
                  ))}
                </ul>
              ) : !emailCandidatesQuery.isPending ? (
                <div className="mt-2 text-[var(--color-mute)]">
                  No imported email invitation candidates are waiting.
                </div>
              ) : null}
            </div>
          </div>
          {canSyncCalendar ? (
            <div className="flex items-center gap-2">
              {connectedOutlookConnection ? (
                <>
                  <button
                    type="button"
                    onClick={() => syncRangeMutation.mutate()}
                    disabled={syncRangeMutation.isPending}
                    className="inline-flex h-8 items-center rounded-md bg-[var(--color-ink)] px-3 text-xs font-medium text-white hover:bg-[var(--color-ink-2)] disabled:opacity-60"
                    data-testid="calendar-outlook-sync-range"
                    aria-label={`Sync visible range ${label} to Outlook`}
                  >
                    {syncRangeMutation.isPending
                      ? "Syncing…"
                      : "Sync visible range to Outlook"}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      revokeOutlookMutation.mutate(connectedOutlookConnection.id);
                    }}
                    disabled={revokeOutlookMutation.isPending}
                    className="inline-flex h-8 items-center rounded-md border border-[var(--color-line-2)] px-3 text-xs font-medium text-[var(--color-ink)] hover:bg-[var(--color-line-1)] disabled:opacity-60"
                    data-testid="calendar-outlook-revoke"
                  >
                    Revoke
                  </button>
                </>
              ) : (
                <button
                  type="button"
                  onClick={() => startOutlookMutation.mutate()}
                  disabled={
                    startOutlookMutation.isPending ||
                    connectionsQuery.data?.provider_available === false
                  }
                  className="inline-flex h-8 items-center rounded-md bg-[var(--color-ink)] px-3 text-xs font-medium text-white hover:bg-[var(--color-ink-2)] disabled:opacity-60"
                  data-testid="calendar-outlook-connect"
                >
                  Connect Outlook
                </button>
              )}
            </div>
          ) : null}
        </div>
      </section>

      <section
        className="rounded-lg border border-[var(--color-line-2)] bg-white px-4 py-3"
        data-testid="calendar-google-panel"
      >
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-sm font-semibold text-[var(--color-ink)]">
              <CalendarDays className="h-4 w-4" aria-hidden />
              Google Calendar
            </div>
            <div className="mt-1 text-xs text-[var(--color-mute)]">
              {syncStatusQuery.isPending ? (
                "Checking Google Calendar readiness..."
              ) : !googleConfigured ? (
                "Google Calendar OAuth is not configured. The authenticated .ics export remains available as a one-time download."
              ) : connectedGoogleConnection ? (
                <>
                  Connected as{" "}
                  {connectedGoogleConnection.display_email ?? "Google account"}
                  {connectedGoogleConnection.last_sync_at
                    ? ` Â· Last sync ${formatDateTime(
                        connectedGoogleConnection.last_sync_at,
                      )}`
                    : ""}
                </>
              ) : (
                "Manual hearing, task, and deadline sync is available after a Google Calendar connection is added."
              )}
            </div>
            {googleMissingConfigNames.length > 0 ? (
              <div
                className="mt-1 text-xs text-[var(--color-mute)]"
                data-testid="calendar-google-provider-config-status"
              >
                Missing Google config: {googleMissingConfigNames.join(", ")}
              </div>
            ) : null}
            {googleMessage ? (
              <div className="mt-1 text-xs text-[var(--color-warning-700,#8a5a00)]">
                {googleMessage}
              </div>
            ) : null}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <a
              href={icsHref}
              className="inline-flex h-8 items-center gap-1.5 rounded-md border border-[var(--color-line-2)] px-3 text-xs font-medium text-[var(--color-ink)] hover:bg-[var(--color-line-1)]"
              data-testid="calendar-google-ics-download"
              download="caseops-calendar.ics"
            >
              <Download className="h-3.5 w-3.5" aria-hidden />
              Download .ics
            </a>
            <Link
              href="/app/admin/integrations"
              className="inline-flex h-8 items-center gap-1.5 rounded-md border border-[var(--color-line-2)] px-3 text-xs font-medium text-[var(--color-ink)] hover:bg-[var(--color-line-1)]"
              data-testid="calendar-google-integrations-link"
            >
              <ExternalLink className="h-3.5 w-3.5" aria-hidden />
              Integration status
            </Link>
            {canSyncCalendar ? (
              connectedGoogleConnection ? (
                <>
                  <button
                    type="button"
                    onClick={() => syncGoogleRangeMutation.mutate()}
                    disabled={syncGoogleRangeMutation.isPending}
                    className="inline-flex h-8 items-center rounded-md bg-[var(--color-ink)] px-3 text-xs font-medium text-white hover:bg-[var(--color-ink-2)] disabled:opacity-60"
                    data-testid="calendar-google-sync-range"
                    aria-label={`Sync visible range ${label} to Google Calendar`}
                  >
                    {syncGoogleRangeMutation.isPending
                      ? "Syncing..."
                      : "Sync visible range to Google"}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      revokeGoogleMutation.mutate(connectedGoogleConnection.id);
                    }}
                    disabled={revokeGoogleMutation.isPending}
                    className="inline-flex h-8 items-center rounded-md border border-[var(--color-line-2)] px-3 text-xs font-medium text-[var(--color-ink)] hover:bg-[var(--color-line-1)] disabled:opacity-60"
                    data-testid="calendar-google-revoke"
                  >
                    Revoke
                  </button>
                </>
              ) : (
                <button
                  type="button"
                  onClick={() => startGoogleMutation.mutate()}
                  disabled={startGoogleMutation.isPending || !googleConfigured}
                  className="inline-flex h-8 items-center rounded-md bg-[var(--color-line-2)] px-3 text-xs font-medium text-[var(--color-mute)] enabled:bg-[var(--color-ink)] enabled:text-white enabled:hover:bg-[var(--color-ink-2)] disabled:opacity-70"
                  data-testid="calendar-google-connect"
                >
                  Connect Google
                </button>
              )
            ) : null}
          </div>
        </div>
      </section>

      <section
        className="rounded-lg border border-[var(--color-line-2)] bg-white px-4 py-3"
        data-testid="calendar-gmail-panel"
      >
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-sm font-semibold text-[var(--color-ink)]">
              <Mail className="h-4 w-4" aria-hidden />
              Gmail mailbox
            </div>
            <div className="mt-1 text-xs text-[var(--color-mute)]">
              {gmailStatusQuery.isPending ? (
                "Checking Gmail readiness..."
              ) : !gmailConfigured ? (
                "Gmail OAuth is not configured. Imported email candidates remain available from manual imports."
              ) : connectedGmailConnection ? (
                <>
                  Connected as {connectedGmailConnection.display_email ?? "Gmail account"}
                  {connectedGmailConnection.last_import_at
                    ? ` Â· Last import ${formatDateTime(
                        connectedGmailConnection.last_import_at,
                      )}`
                    : ""}
                  {connectedGmailConnection.watch_expires_at
                    ? ` Â· Watch expires ${formatDateTime(
                        connectedGmailConnection.watch_expires_at,
                      )}`
                    : ""}
                </>
              ) : (
                "Connect Gmail to import message metadata into the review-first mailbox queue."
              )}
            </div>
            {gmailMissingConfigNames.length > 0 ? (
              <div
                className="mt-1 text-xs text-[var(--color-mute)]"
                data-testid="calendar-gmail-provider-config-status"
              >
                Missing Gmail config: {gmailMissingConfigNames.join(", ")}
              </div>
            ) : null}
            {!gmailWebhookConfigured ? (
              <div
                className="mt-1 text-xs text-[var(--color-mute)]"
                data-testid="calendar-gmail-webhook-config-status"
              >
                Gmail webhook blocked: {gmailMissingWebhookConfigNames.join(", ")}
              </div>
            ) : null}
            {gmailMessage ? (
              <div className="mt-1 text-xs text-[var(--color-warning-700,#8a5a00)]">
                {gmailMessage}
              </div>
            ) : null}
          </div>
          {canSyncCalendar ? (
            <div className="flex flex-wrap items-center gap-2">
              {connectedGmailConnection ? (
                <>
                  <button
                    type="button"
                    onClick={() => importGmailMutation.mutate()}
                    disabled={importGmailMutation.isPending}
                    className="inline-flex h-8 items-center gap-1.5 rounded-md bg-[var(--color-ink)] px-3 text-xs font-medium text-white hover:bg-[var(--color-ink-2)] disabled:opacity-60"
                    data-testid="calendar-gmail-import"
                  >
                    <Inbox className="h-3.5 w-3.5" aria-hidden />
                    {importGmailMutation.isPending ? "Importing..." : "Import Gmail"}
                  </button>
                  <button
                    type="button"
                    onClick={() => startGmailWatchMutation.mutate()}
                    disabled={
                      startGmailWatchMutation.isPending || !gmailWebhookConfigured
                    }
                    className="inline-flex h-8 items-center gap-1.5 rounded-md border border-[var(--color-line-2)] px-3 text-xs font-medium text-[var(--color-ink)] hover:bg-[var(--color-line-1)] disabled:opacity-60"
                    data-testid="calendar-gmail-watch"
                  >
                    <RefreshCw className="h-3.5 w-3.5" aria-hidden />
                    {startGmailWatchMutation.isPending ? "Starting..." : "Start watch"}
                  </button>
                  <button
                    type="button"
                    onClick={() => revokeGmailMutation.mutate(connectedGmailConnection.id)}
                    disabled={revokeGmailMutation.isPending}
                    className="inline-flex h-8 items-center rounded-md border border-[var(--color-line-2)] px-3 text-xs font-medium text-[var(--color-ink)] hover:bg-[var(--color-line-1)] disabled:opacity-60"
                    data-testid="calendar-gmail-revoke"
                  >
                    Revoke
                  </button>
                </>
              ) : (
                <button
                  type="button"
                  onClick={() => startGmailMutation.mutate()}
                  disabled={startGmailMutation.isPending || !gmailConfigured}
                  className="inline-flex h-8 items-center rounded-md bg-[var(--color-line-2)] px-3 text-xs font-medium text-[var(--color-mute)] enabled:bg-[var(--color-ink)] enabled:text-white enabled:hover:bg-[var(--color-ink-2)] disabled:opacity-70"
                  data-testid="calendar-gmail-connect"
                >
                  Connect Gmail
                </button>
              )}
            </div>
          ) : null}
        </div>
      </section>

      {query.isError ? (
        <QueryErrorState
          title="Could not load calendar"
          error={query.error}
          onRetry={query.refetch}
        />
      ) : null}

      {/* BUG-019 (Ram 2026-04-26): when the tenant has zero events
          across the visible window the per-cell "No events" hints
          read as broken UI. Render an explicit, actionable banner
          ABOVE the grid so a fresh tenant understands the calendar
          will populate from hearings + tasks + deadlines on its
          matters. The grid still renders below so the user sees the
          date layout immediately and confirms the calendar is alive. */}
      {!query.isPending && !query.isError && (query.data?.events ?? []).length === 0 ? (
        <div
          className="flex flex-col gap-2 rounded-[var(--radius-md)] border border-[var(--color-line)] bg-[var(--color-bg-2)] px-4 py-3 text-sm text-[var(--color-ink-2)]"
          data-testid="calendar-empty-state"
        >
          <div className="font-medium text-[var(--color-ink)]">
            No events on the calendar yet
          </div>
          <div className="text-xs text-[var(--color-mute)]">
            The calendar populates from hearings, tasks, and deadlines
            attached to your matters. Schedule a hearing on any
            matter — it will appear here within seconds. (Verified
            end-to-end 2026-04-28 against prod.)
          </div>
          <div className="flex flex-wrap gap-3">
            <Link
              href="/app/matters"
              data-testid="calendar-empty-cta-schedule"
              className="inline-flex items-center gap-1.5 text-xs font-semibold text-[var(--color-brand-700)] underline-offset-4 hover:underline"
            >
              Schedule a hearing
              <ChevronRight className="h-3 w-3" aria-hidden />
            </Link>
            <Link
              href="/app/matters"
              data-testid="calendar-empty-cta-open-matters"
              className="inline-flex items-center gap-1.5 text-xs font-medium text-[var(--color-ink-2)] underline-offset-4 hover:underline"
            >
              Open Matters
              <ChevronRight className="h-3 w-3" aria-hidden />
            </Link>
          </div>
        </div>
      ) : null}

      {view === "month" ? (
        <MonthView
          monthStart={startOfMonth(cursor)}
          eventsByDay={eventsByDay}
          isPending={query.isPending}
          todayKey={todayKey}
        />
      ) : view === "week" ? (
        <WeekView
          weekStart={startOfWeekMonday(cursor)}
          eventsByDay={eventsByDay}
          isPending={query.isPending}
          todayKey={todayKey}
        />
      ) : (
        <DayView
          day={cursor}
          eventsByDay={eventsByDay}
          isPending={query.isPending}
          todayKey={todayKey}
        />
      )}
    </div>
  );
}
// --- views ----------------------------------------------------------

function MonthView({
  monthStart,
  eventsByDay,
  isPending,
  todayKey,
}: {
  monthStart: Date;
  eventsByDay: Map<string, CalendarEventRecord[]>;
  isPending: boolean;
  todayKey: string;
}) {
  const grid = buildMonthGrid(monthStart);
  return (
    <div className="overflow-hidden rounded-lg border border-[var(--color-line-2)]">
      <div className="grid grid-cols-7 border-b border-[var(--color-line-2)] bg-[var(--color-line-1)] text-[10px] font-semibold uppercase tracking-wider text-[var(--color-mute)]">
        {WEEKDAY_LABELS.map((w) => (
          <div key={w} className="px-3 py-2">{w}</div>
        ))}
      </div>
      <div className="grid grid-cols-7 grid-rows-6">
        {grid.map((d, idx) => {
          const key = isoDate(d);
          const inMonth = d.getMonth() === monthStart.getMonth();
          const isToday = key === todayKey;
          const events = eventsByDay.get(key) ?? [];
          const showCount = events.slice(0, 3);
          const overflow = events.length - showCount.length;
          return (
            <div
              key={`${idx}-${key}`}
              className={cn(
                "min-h-[7rem] border-b border-r border-[var(--color-line-2)] p-2",
                !inMonth && "bg-[var(--color-line-1)]/40",
                isToday && "bg-[var(--color-accent-bg)]",
                idx % 7 === 6 && "border-r-0",
                idx >= 35 && "border-b-0",
              )}
            >
              <div
                className={cn(
                  "mb-1 text-[11px] font-medium",
                  inMonth
                    ? isToday
                      ? "text-[var(--color-accent)]"
                      : "text-[var(--color-ink)]"
                    : "text-[var(--color-mute)]",
                )}
              >
                {d.getDate()}
              </div>
              <div className="flex flex-col gap-1">
                {isPending ? (
                  <Skeleton className="h-4 w-full" />
                ) : (
                  showCount.map((event) => (
                    <CalendarEventChip key={event.id} event={event} />
                  ))
                )}
                {overflow > 0 ? (
                  <div className="text-[10px] text-[var(--color-mute)]">
                    +{overflow} more
                  </div>
                ) : null}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function WeekView({
  weekStart,
  eventsByDay,
  isPending,
  todayKey,
}: {
  weekStart: Date;
  eventsByDay: Map<string, CalendarEventRecord[]>;
  isPending: boolean;
  todayKey: string;
}) {
  const days = Array.from({ length: 7 }, (_, i) => {
    const d = new Date(weekStart);
    d.setDate(weekStart.getDate() + i);
    return d;
  });
  return (
    <div className="overflow-hidden rounded-lg border border-[var(--color-line-2)]">
      <div className="grid grid-cols-7">
        {days.map((d, idx) => {
          const key = isoDate(d);
          const isToday = key === todayKey;
          const events = eventsByDay.get(key) ?? [];
          return (
            <div
              key={key}
              className={cn(
                "flex min-h-[24rem] flex-col border-b border-r border-[var(--color-line-2)] p-2",
                isToday && "bg-[var(--color-accent-bg)]",
                idx === 6 && "border-r-0",
                "border-b-0",
              )}
              data-testid={`calendar-week-day-${key}`}
            >
              <div className="mb-2 flex items-baseline justify-between">
                <div className="text-[10px] font-semibold uppercase tracking-wider text-[var(--color-mute)]">
                  {WEEKDAY_LABELS[idx]}
                </div>
                <div
                  className={cn(
                    "text-sm font-semibold tabular",
                    isToday
                      ? "text-[var(--color-accent)]"
                      : "text-[var(--color-ink)]",
                  )}
                >
                  {d.getDate()}
                </div>
              </div>
              <div className="flex flex-col gap-1">
                {isPending ? (
                  <Skeleton className="h-4 w-full" />
                ) : events.length === 0 ? (
                  <div className="text-[10px] italic text-[var(--color-mute)]">
                    No events
                  </div>
                ) : (
                  events.map((event) => (
                    <CalendarEventChip key={event.id} event={event} />
                  ))
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function DayView({
  day,
  eventsByDay,
  isPending,
  todayKey,
}: {
  day: Date;
  eventsByDay: Map<string, CalendarEventRecord[]>;
  isPending: boolean;
  todayKey: string;
}) {
  const key = isoDate(day);
  const isToday = key === todayKey;
  const events = eventsByDay.get(key) ?? [];
  return (
    <div
      className={cn(
        "rounded-lg border border-[var(--color-line-2)] p-4",
        isToday && "bg-[var(--color-accent-bg)]",
      )}
      data-testid={`calendar-day-pane-${key}`}
    >
      {isPending ? (
        <div className="flex flex-col gap-2">
          <Skeleton className="h-6 w-3/4" />
          <Skeleton className="h-6 w-1/2" />
        </div>
      ) : events.length === 0 ? (
        <div className="text-sm italic text-[var(--color-mute)]">
          No hearings, tasks, or deadlines on this day.
        </div>
      ) : (
        <ul className="flex flex-col gap-2">
          {events.map((event) => {
            const Icon = KIND_ICON[event.kind];
            return (
              <li key={event.id}>
                <Link
                  href={deepLinkForEvent(event)}
                  className="group flex items-start gap-3 rounded-md border border-[var(--color-line-2)] bg-white px-3 py-2 hover:border-[var(--color-ink-3)]"
                  data-testid={`calendar-event-${event.id}`}
                >
                  <span
                    className={cn(
                      "mt-1 inline-flex h-6 w-6 items-center justify-center rounded-full text-white",
                      KIND_DOT[event.kind],
                    )}
                  >
                    <Icon className="h-3.5 w-3.5" aria-hidden />
                  </span>
                  <div className="flex-1">
                    <div className="font-medium text-[var(--color-ink)]">
                      {event.title}
                    </div>
                    <div className="text-xs text-[var(--color-mute)]">
                      <span className="font-mono">{event.matter_code}</span>
                      {" · "}
                      {event.matter_title}
                      {event.detail ? ` · ${event.detail}` : ""}
                    </div>
                  </div>
                  <ExternalLink
                    className="h-4 w-4 text-[var(--color-mute)] opacity-0 group-hover:opacity-100"
                    aria-hidden
                  />
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function deepLinkForEvent(event: CalendarEventRecord): string {
  switch (event.kind) {
    case "hearing":
      return `/app/matters/${event.matter_id}/hearings`;
    case "task":
      return `/app/matters/${event.matter_id}/tasks`;
    case "deadline":
      return `/app/matters/${event.matter_id}/tasks`;
  }
}

function CalendarEventChip({ event }: { event: CalendarEventRecord }) {
  return (
    <Link
      href={deepLinkForEvent(event)}
      className="group flex items-start gap-1.5 rounded-sm px-1.5 py-1 text-[11px] hover:bg-[var(--color-line-1)]"
      title={`${event.matter_code} · ${event.matter_title} — ${event.title}`}
      data-testid={`calendar-event-${event.id}`}
    >
      <span
        className={cn("mt-1 h-1.5 w-1.5 shrink-0 rounded-full", KIND_DOT[event.kind])}
      />
      <span className="flex-1 truncate text-[var(--color-ink)] group-hover:underline">
        {event.title}
      </span>
      <ExternalLink
        className="h-3 w-3 shrink-0 text-[var(--color-mute)] opacity-0 group-hover:opacity-100"
        aria-hidden
      />
    </Link>
  );
}
