"use client";

// ENH-017 / US-064 / FT-098 — Year view: twelve month mini-grids with per-day
// open-item density by display type. Counts come from /api/calendar/summary,
// which shares the month list's predicates, so a dot here always opens to the
// same items in Day view.

import { Skeleton } from "@/components/ui/Skeleton";
import type { CalendarDaySummary } from "@/lib/api/schemas";
import {
  DISPLAY_META,
  DISPLAY_ORDER,
  MONTH_NAMES,
  WEEKDAY_LABELS,
  buildMonthGrid,
  describeDayCounts,
  isoDate,
} from "@/lib/calendar/display";
import { cn } from "@/lib/cn";

const MAX_DOTS = 4;

export function YearView({
  year,
  daysByDate,
  isPending,
  todayKey,
  onOpenDay,
  onOpenMonth,
}: {
  year: number;
  daysByDate: Map<string, CalendarDaySummary>;
  isPending: boolean;
  todayKey: string;
  onOpenDay: (day: Date) => void;
  onOpenMonth: (monthStart: Date) => void;
}) {
  return (
    <div
      className="grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4"
      data-testid="calendar-year-grid"
      aria-busy={isPending}
    >
      {MONTH_NAMES.map((monthName, month) => {
        const monthStart = new Date(year, month, 1);
        const monthKey = isoDate(monthStart).slice(0, 7);
        const headingId = `calendar-year-month-${monthKey}-heading`;
        return (
          <section
            key={monthKey}
            aria-labelledby={headingId}
            className="min-w-0 rounded-lg border border-[var(--color-line)] bg-[var(--color-surface)] p-2"
            data-testid={`calendar-year-month-${monthKey}`}
          >
            <h2 id={headingId} className="mb-1">
              <button
                type="button"
                onClick={() => onOpenMonth(monthStart)}
                className="rounded-sm px-1 text-sm font-semibold text-[var(--color-ink)] hover:underline focus-visible:outline focus-visible:outline-2"
                aria-label={`Open ${monthName} ${year} in Month view`}
                data-testid={`calendar-year-open-month-${monthKey}`}
              >
                {monthName}
              </button>
            </h2>
            <div className="grid grid-cols-7 text-center text-[10px] font-semibold uppercase text-[var(--color-mute)]" aria-hidden>
              {WEEKDAY_LABELS.map((w) => (
                <div key={w}>{w.slice(0, 1)}</div>
              ))}
            </div>
            {isPending ? (
              <Skeleton className="mt-1 h-40 w-full" />
            ) : (
              <div className="grid grid-cols-7">
                {buildMonthGrid(monthStart).map((d, idx) => {
                  if (d.getMonth() !== month) return <div key={idx} aria-hidden />;
                  const key = isoDate(d);
                  const summary = daysByDate.get(key);
                  const total = summary?.total ?? 0;
                  const types = summary
                    ? DISPLAY_ORDER.filter((type) => (summary.by_display_type[type] ?? 0) > 0)
                    : [];
                  const isToday = key === todayKey;
                  return (
                    <button
                      key={key}
                      type="button"
                      onClick={() => onOpenDay(d)}
                      // Only dates with items are tab stops; the month heading
                      // reaches every other date through Month view.
                      tabIndex={total > 0 ? 0 : -1}
                      aria-label={`${describeDayCounts(d, summary?.by_display_type ?? {})}. Open in Day view`}
                      title={describeDayCounts(d, summary?.by_display_type ?? {})}
                      data-testid={`calendar-year-day-${key}`}
                      data-total={total}
                      className={cn(
                        "flex min-h-11 min-w-0 flex-col items-center justify-start rounded-sm pt-0.5 text-[11px] tabular-nums hover:bg-[var(--color-line-1)] focus-visible:outline focus-visible:outline-2",
                        isToday && "bg-[var(--color-accent-bg)] font-semibold text-[var(--color-accent)]",
                        !isToday && (total > 0 ? "font-semibold text-[var(--color-ink)]" : "text-[var(--color-mute)]"),
                      )}
                    >
                      <span>{d.getDate()}</span>
                      {total > 0 ? (
                        <span className="mt-0.5 flex items-center gap-0.5" aria-hidden>
                          {types.slice(0, MAX_DOTS).map((type) => (
                            <span
                              key={type}
                              className={cn("h-1.5 w-1.5 rounded-full", DISPLAY_META[type].dot)}
                              data-display-type={type}
                            />
                          ))}
                          {total > 1 ? (
                            <span className="text-[9px] font-medium leading-none text-[var(--color-ink-2)]">{total}</span>
                          ) : null}
                        </span>
                      ) : null}
                    </button>
                  );
                })}
              </div>
            )}
          </section>
        );
      })}
    </div>
  );
}
