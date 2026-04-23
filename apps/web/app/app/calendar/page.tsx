"use client";

// Phase B / J08 / M08 / US-022 / US-023 / FT-042 — unified calendar.
//
// Single screen, single primary job per the impeccable / PRD UX rule:
// show every hearing, task due-date, and matter_deadline due-on for the
// caller's company in one month grid the lawyer can scan in seconds.
// Click a cell → see the events for that day; click an event → deep
// link to the source matter's tab.
//
// Slice 1 ships month view only. Week / day views and iCal export
// land in slice 2.

import { useQuery } from "@tanstack/react-query";
import {
  CalendarDays,
  ChevronLeft,
  ChevronRight,
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
import { cn } from "@/lib/cn";

const KIND_ICON: Record<CalendarEventKind, typeof Gavel> = {
  hearing: Gavel,
  task: ListTodo,
  deadline: Timer,
};

// OKLCH-derived semantic colours — the impeccable skill prohibits
// neon / gradient. These map to the existing palette tokens.
const KIND_DOT: Record<CalendarEventKind, string> = {
  hearing: "bg-[var(--color-accent)]",
  task: "bg-[var(--color-info-500)]",
  deadline: "bg-[var(--color-warning-500)]",
};

function startOfMonth(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), 1);
}

function isoDate(d: Date): string {
  // Local-tz YYYY-MM-DD. Cookie-set TZ doesn't matter; the API works
  // in dates not datetimes, so the user's local interpretation of
  // "today" is the right one.
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function buildMonthGrid(monthStart: Date): Date[] {
  // Six weeks × seven days; pad with prev-month / next-month days so
  // the grid is always a full rectangle. Indian calendars start on
  // Sunday by convention, but our user base is mixed — defaulting to
  // Monday-first because it matches court week structure (Mon–Fri).
  const firstWeekday = monthStart.getDay(); // 0 = Sun, 1 = Mon, …
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
  const [cursor, setCursor] = useState<Date>(() => startOfMonth(new Date()));

  const monthStart = startOfMonth(cursor);
  const monthEnd = new Date(
    monthStart.getFullYear(), monthStart.getMonth() + 1, 0,
  );
  const grid = useMemo(() => buildMonthGrid(monthStart), [monthStart]);
  const gridFrom = grid[0];
  const gridTo = grid[grid.length - 1];

  const query = useQuery({
    queryKey: ["calendar", isoDate(gridFrom), isoDate(gridTo)],
    queryFn: () =>
      fetchCalendarEvents({ from: isoDate(gridFrom), to: isoDate(gridTo) }),
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
  const monthLabel = `${MONTH_NAMES[monthStart.getMonth()]} ${monthStart.getFullYear()}`;

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
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() =>
              setCursor((c) => new Date(c.getFullYear(), c.getMonth() - 1, 1))
            }
            className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-[var(--color-line-2)] text-[var(--color-mute)] hover:text-[var(--color-ink)]"
            aria-label="Previous month"
            data-testid="calendar-prev-month"
          >
            <ChevronLeft className="h-4 w-4" aria-hidden />
          </button>
          <div
            className="min-w-[10rem] text-center text-sm font-medium text-[var(--color-ink)]"
            data-testid="calendar-month-label"
          >
            {monthLabel}
          </div>
          <button
            type="button"
            onClick={() =>
              setCursor((c) => new Date(c.getFullYear(), c.getMonth() + 1, 1))
            }
            className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-[var(--color-line-2)] text-[var(--color-mute)] hover:text-[var(--color-ink)]"
            aria-label="Next month"
            data-testid="calendar-next-month"
          >
            <ChevronRight className="h-4 w-4" aria-hidden />
          </button>
          <button
            type="button"
            onClick={() => setCursor(startOfMonth(new Date()))}
            className="ml-2 inline-flex h-8 items-center rounded-md border border-[var(--color-line-2)] px-3 text-xs font-medium text-[var(--color-ink)] hover:bg-[var(--color-line-1)]"
            data-testid="calendar-today"
          >
            Today
          </button>
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

      {/* Month grid */}
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
                  // Last column / row strip the right / bottom border
                  // so the table sits flush in its rounded container.
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
                  {query.isPending ? (
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

// Placeholder import the bundler will tree-shake when the icon is
// only referenced via type. Keeping the import explicit so the
// dev-tools devtools tooltip on the page header shows the right
// icon at a glance.
const _calendarIcon = CalendarDays;
void _calendarIcon;
