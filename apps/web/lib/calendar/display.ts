// Calendar display vocabulary shared by the Month, Week, Day and Year views,
// so every view and the legend paint one type with one defined token colour.
import {
  CalendarCheck,
  Gavel,
  Inbox,
  ListTodo,
  Mail,
  RefreshCw,
  Target,
  Timer,
} from "lucide-react";

import type { CalendarEventDisplayType, CalendarEventRecord } from "@/lib/api/schemas";

export type CalendarDisplayMeta = {
  label: string;
  shortLabel: string;
  /** Singular and plural nouns for spoken counts ("5 hearings"). */
  noun: [string, string];
  icon: typeof Gavel;
  /** Tailwind background class; every colour resolves to a defined token. */
  dot: string;
};

export const DISPLAY_META: Record<CalendarEventDisplayType, CalendarDisplayMeta> = {
  hearing: { label: "Hearing or listing", shortLabel: "Hearing", noun: ["hearing", "hearings"], icon: Gavel, dot: "bg-[var(--color-accent)]" },
  task_date: { label: "Task date", shortLabel: "Task", noun: ["task date", "task dates"], icon: ListTodo, dot: "bg-[var(--color-info-500)]" },
  filing_deadline: { label: "Legal filing deadline", shortLabel: "Filing", noun: ["legal filing deadline", "legal filing deadlines"], icon: Timer, dot: "bg-red-600" },
  internal_target: { label: "Internal target", shortLabel: "Target", noun: ["internal target", "internal targets"], icon: Target, dot: "bg-amber-500" },
  renewal: { label: "Renewal date", shortLabel: "Renewal", noun: ["renewal date", "renewal dates"], icon: RefreshCw, dot: "bg-emerald-600" },
  client_instruction: { label: "Client-instruction date", shortLabel: "Client", noun: ["client-instruction date", "client-instruction dates"], icon: Inbox, dot: "bg-cyan-700" },
  reminder: { label: "Reminder time", shortLabel: "Reminder", noun: ["reminder", "reminders"], icon: Mail, dot: "bg-violet-600" },
  // Neutral slate so an unclassified deadline never reads as an internal target (amber).
  deadline: { label: "Other deadline", shortLabel: "Deadline", noun: ["other deadline", "other deadlines"], icon: CalendarCheck, dot: "bg-[var(--color-ink-3)]" },
};

/** Fixed legend and dot order: legal dates first, then working dates. */
export const DISPLAY_ORDER: CalendarEventDisplayType[] = [
  "filing_deadline",
  "hearing",
  "internal_target",
  "renewal",
  "task_date",
  "client_instruction",
  "reminder",
  "deadline",
];

export function displayTypeForEvent(event: CalendarEventRecord): CalendarEventDisplayType {
  if (event.display_type) return event.display_type;
  if (event.kind === "hearing") return "hearing";
  if (event.kind === "task") return "task_date";
  return "deadline";
}

export function isoDate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

/** Parses a strict yyyy-mm-dd into a local date, or null when invalid. */
export function parseIsoDate(value: string | null): Date | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value ?? "");
  if (!match) return null;
  const parsed = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  return isoDate(parsed) === value ? parsed : null;
}

export function buildMonthGrid(monthStart: Date): Date[] {
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

export const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];
export const WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

/** "26 Sep 2026: 6 events — 5 hearings, 1 task date". Colour is never the only signal. */
export function describeDayCounts(
  day: Date,
  byType: Partial<Record<CalendarEventDisplayType, number>>,
): string {
  const dateLabel = `${day.getDate()} ${MONTH_NAMES[day.getMonth()].slice(0, 3)} ${day.getFullYear()}`;
  const parts = DISPLAY_ORDER.flatMap((type) => {
    const count = byType[type] ?? 0;
    if (count <= 0) return [];
    const [one, many] = DISPLAY_META[type].noun;
    return [`${count} ${count === 1 ? one : many}`];
  });
  const total = DISPLAY_ORDER.reduce((sum, type) => sum + (byType[type] ?? 0), 0);
  if (total === 0) return `${dateLabel}: no open items`;
  return `${dateLabel}: ${total} ${total === 1 ? "event" : "events"} — ${parts.join(", ")}`;
}

/** Calendar quarters of a year, each within the 92-day export cap. */
export function yearQuarters(year: number): { label: string; from: string; to: string }[] {
  return [0, 3, 6, 9].map((startMonth, index) => ({
    label: `Q${index + 1}`,
    from: isoDate(new Date(year, startMonth, 1)),
    to: isoDate(new Date(year, startMonth + 3, 0)),
  }));
}
