"use client";

// Phase B / J08 / M08 / US-022 / US-023 / FT-042-043 — unified calendar.
//
// Slice 1 (shipped 2026-04-23): month grid + tenant-scoped event feed
// across hearings + tasks + matter_deadlines.
// Slice 2b (this file): adds Week + Day views and an .ics subscribe link.

import { useQuery } from "@tanstack/react-query";
import {
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  Download,
  ExternalLink,
  Gavel,
  ListTodo,
  Timer,
} from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { fetchCalendarEvents } from "@/lib/api/endpoints";
import type { CalendarEventKind, CalendarEventRecord } from "@/lib/api/schemas";
import { API_BASE_URL } from "@/lib/api/config";
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
          {/* iCal export — Google Calendar / Outlook / Apple Calendar
              all subscribe to this URL. The link target uses the
              current view's range so a "Subscribe" downloads
              exactly what's on screen. */}
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
            attached to your matters. Open a matter to schedule a
            hearing or set a deadline — it will appear here within
            seconds.
          </div>
          <div>
            <Link
              href="/app/matters"
              className="inline-flex items-center gap-1.5 text-xs font-semibold text-[var(--color-brand-700)] underline-offset-4 hover:underline"
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
      return `/app/matters/${event.matter_id}`;
    case "deadline":
      return `/app/matters/${event.matter_id}`;
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

const _calendarIcon = CalendarDays;
void _calendarIcon;
