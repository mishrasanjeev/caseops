"use client";

// PG-004 (2026-05-01) — Today cockpit. Pulls hearings + tasks +
// drafts in review + overdue invoices + deadlines into a single
// prioritised feed. Replaces the "open the matters list and remember
// what's hot" workflow.

import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  CalendarClock,
  CheckSquare,
  ClipboardCheck,
  FileText,
  Gavel,
  Receipt,
  Sun,
} from "lucide-react";
import Link from "next/link";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import {
  type TodayDeadline,
  type TodayDraftInReview,
  type TodayHearing,
  type TodayInvoice,
  type TodayTask,
  type TodayView,
  fetchTodayView,
} from "@/lib/api/endpoints";
import { formatLegalDate } from "@/lib/dates";

export default function TodayPage() {
  const query = useQuery({
    queryKey: ["today", { horizon: 7 }],
    queryFn: () => fetchTodayView({ horizonDays: 7 }),
  });

  return (
    <div className="flex flex-col gap-5">
      <header className="flex items-center gap-3">
        <Sun className="h-6 w-6 text-[var(--color-brand-600)]" aria-hidden />
        <div>
          <h1 className="text-xl font-semibold text-[var(--color-ink)]">Today</h1>
          <p className="text-sm text-[var(--color-mute)]">
            Hearings, tasks, drafts pending review, overdue invoices, and deadlines —
            all your matters, prioritised by urgency.
          </p>
        </div>
      </header>

      {query.isPending ? (
        <SkeletonGrid />
      ) : query.isError ? (
        <QueryErrorState
          title="Could not load Today feed"
          error={query.error}
          onRetry={query.refetch}
        />
      ) : query.data ? (
        <TodayBody data={query.data} />
      ) : null}
    </div>
  );
}

function TodayBody({ data }: { data: TodayView }) {
  const allEmpty =
    data.hearings_next_7d.length === 0 &&
    data.tasks_due_or_overdue.length === 0 &&
    data.drafts_in_review.length === 0 &&
    data.overdue_invoices.length === 0 &&
    data.deadlines_next_7d.length === 0;

  if (allEmpty) {
    return (
      <EmptyState
        icon={Sun}
        title="Nothing demanding attention today"
        description="No upcoming hearings, no overdue tasks, no drafts pending review, no overdue invoices. Open a matter to start something."
      />
    );
  }

  const tr = data.stream_truncated;
  const lim = data.stream_limits;
  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <HearingsCard
        hearings={data.hearings_next_7d}
        truncated={!!tr?.hearings_next_7d}
        limit={lim?.hearings_next_7d}
      />
      <DeadlinesCard
        deadlines={data.deadlines_next_7d}
        truncated={!!tr?.deadlines_next_7d}
        limit={lim?.deadlines_next_7d}
      />
      <TasksCard
        tasks={data.tasks_due_or_overdue}
        truncated={!!tr?.tasks_due_or_overdue}
        limit={lim?.tasks_due_or_overdue}
      />
      <DraftsInReviewCard
        drafts={data.drafts_in_review}
        truncated={!!tr?.drafts_in_review}
        limit={lim?.drafts_in_review}
      />
      <OverdueInvoicesCard
        invoices={data.overdue_invoices}
        truncated={!!tr?.overdue_invoices}
        limit={lim?.overdue_invoices}
      />
    </div>
  );
}

// PG-perf (2026-05-16): a Today stream is capped server-side
// (MAX_PER_STREAM). When the cap is hit we show a quiet note so the
// user knows the screen isn't the full list — full pagination is a
// separate follow-up; the matters / hearings / calendar list views
// remain the unbounded source of truth.
function TruncationNote({
  truncated,
  limit,
}: {
  truncated?: boolean;
  limit?: number;
}) {
  if (!truncated) return null;
  return (
    <p
      className="mt-3 text-xs text-[var(--color-mute)]"
      data-testid="today-stream-truncated"
    >
      {limit ? `Showing the first ${limit}.` : "Showing a capped subset."} More
      available — open the matter list views to see everything.
    </p>
  );
}

function HearingsCard({
  hearings,
  truncated,
  limit,
}: {
  hearings: TodayHearing[];
  truncated?: boolean;
  limit?: number;
}) {
  if (hearings.length === 0) {
    return (
      <Card data-testid="today-hearings">
        <CardHeader>
          <CardTitle as="h2">
            <Gavel className="mr-2 inline-block h-4 w-4" aria-hidden />
            Hearings — next 7 days
          </CardTitle>
          <CardDescription>No hearings scheduled in the next week.</CardDescription>
        </CardHeader>
      </Card>
    );
  }
  return (
    <Card data-testid="today-hearings">
      <CardHeader>
        <CardTitle as="h2">
          <Gavel className="mr-2 inline-block h-4 w-4" aria-hidden />
          Hearings — next 7 days ({hearings.length})
        </CardTitle>
      </CardHeader>
      <CardContent>
        <ul className="flex flex-col gap-2 text-sm">
          {hearings.map((h) => (
            <li
              key={h.id}
              className="flex flex-col gap-0.5 rounded-md border border-[var(--color-line)] px-3 py-2"
              data-testid={`today-hearing-${h.id}`}
            >
              <div className="flex items-baseline justify-between gap-2">
                <Link
                  href={`/app/matters/${h.matter.id}/hearings`}
                  className="font-medium text-[var(--color-ink)] hover:underline"
                >
                  {h.matter.matter_code} — {h.purpose}
                </Link>
                <span className="tabular text-xs text-[var(--color-mute)]">
                  {formatDate(h.hearing_on)}
                </span>
              </div>
              <p className="text-xs text-[var(--color-mute)]">
                {h.forum_name}
                {h.judge_name ? ` · ${h.judge_name}` : ""} ·{" "}
                {h.matter.title}
              </p>
            </li>
          ))}
        </ul>
        <TruncationNote truncated={truncated} limit={limit} />
      </CardContent>
    </Card>
  );
}

function DeadlinesCard({
  deadlines,
  truncated,
  limit,
}: {
  deadlines: TodayDeadline[];
  truncated?: boolean;
  limit?: number;
}) {
  if (deadlines.length === 0) {
    return (
      <Card data-testid="today-deadlines">
        <CardHeader>
          <CardTitle as="h2">
            <CalendarClock className="mr-2 inline-block h-4 w-4" aria-hidden />
            Deadlines — next 7 days
          </CardTitle>
          <CardDescription>No statutory deadlines in the next week.</CardDescription>
        </CardHeader>
      </Card>
    );
  }
  return (
    <Card data-testid="today-deadlines">
      <CardHeader>
        <CardTitle as="h2">
          <CalendarClock className="mr-2 inline-block h-4 w-4" aria-hidden />
          Deadlines — next 7 days ({deadlines.length})
        </CardTitle>
      </CardHeader>
      <CardContent>
        <ul className="flex flex-col gap-2 text-sm">
          {deadlines.map((d) => (
            <li
              key={d.id}
              className="flex flex-col gap-0.5 rounded-md border border-[var(--color-line)] px-3 py-2"
              data-testid={`today-deadline-${d.id}`}
            >
              <div className="flex items-baseline justify-between gap-2">
                <Link
                  href={`/app/matters/${d.matter.id}`}
                  className="font-medium text-[var(--color-ink)] hover:underline"
                >
                  {d.matter.matter_code} — {d.title}
                </Link>
                <span className="tabular text-xs text-[var(--color-mute)]">
                  {d.days_until <= 0 ? "today" : `in ${d.days_until}d`}
                </span>
              </div>
              <p className="text-xs text-[var(--color-mute)]">
                {formatDate(d.due_on)} · {d.matter.title}
              </p>
            </li>
          ))}
        </ul>
        <TruncationNote truncated={truncated} limit={limit} />
      </CardContent>
    </Card>
  );
}

function TasksCard({
  tasks,
  truncated,
  limit,
}: {
  tasks: TodayTask[];
  truncated?: boolean;
  limit?: number;
}) {
  if (tasks.length === 0) {
    return (
      <Card data-testid="today-tasks">
        <CardHeader>
          <CardTitle as="h2">
            <CheckSquare className="mr-2 inline-block h-4 w-4" aria-hidden /> Tasks
          </CardTitle>
          <CardDescription>Nothing overdue or due in the next week.</CardDescription>
        </CardHeader>
      </Card>
    );
  }
  return (
    <Card data-testid="today-tasks">
      <CardHeader>
        <CardTitle as="h2">
          <CheckSquare className="mr-2 inline-block h-4 w-4" aria-hidden />
          Tasks — overdue + due soon ({tasks.length})
        </CardTitle>
      </CardHeader>
      <CardContent>
        <ul className="flex flex-col gap-2 text-sm">
          {tasks.map((t) => (
            <li
              key={t.id}
              className={`flex flex-col gap-0.5 rounded-md border px-3 py-2 ${
                t.overdue
                  ? "border-red-200 bg-red-50"
                  : "border-[var(--color-line)]"
              }`}
              data-testid={`today-task-${t.id}`}
            >
              <div className="flex items-baseline justify-between gap-2">
                <Link
                  href={`/app/matters/${t.matter.id}`}
                  className={`font-medium hover:underline ${
                    t.overdue ? "text-red-900" : "text-[var(--color-ink)]"
                  }`}
                >
                  {t.matter.matter_code} — {t.title}
                </Link>
                <span className="tabular text-xs text-[var(--color-mute)]">
                  {t.due_on
                    ? t.overdue
                      ? `overdue (${formatDate(t.due_on)})`
                      : formatDate(t.due_on)
                    : "no date"}
                </span>
              </div>
              <p className="text-xs text-[var(--color-mute)]">
                {t.priority} · {t.status} · {t.matter.title}
              </p>
            </li>
          ))}
        </ul>
        <TruncationNote truncated={truncated} limit={limit} />
      </CardContent>
    </Card>
  );
}

function DraftsInReviewCard({
  drafts,
  truncated,
  limit,
}: {
  drafts: TodayDraftInReview[];
  truncated?: boolean;
  limit?: number;
}) {
  if (drafts.length === 0) {
    return (
      <Card data-testid="today-drafts-in-review">
        <CardHeader>
          <CardTitle as="h2">
            <ClipboardCheck className="mr-2 inline-block h-4 w-4" aria-hidden />
            Drafts pending review
          </CardTitle>
          <CardDescription>No drafts waiting for partner review.</CardDescription>
        </CardHeader>
      </Card>
    );
  }
  return (
    <Card data-testid="today-drafts-in-review">
      <CardHeader>
        <CardTitle as="h2">
          <ClipboardCheck className="mr-2 inline-block h-4 w-4" aria-hidden />
          Drafts pending review ({drafts.length})
        </CardTitle>
      </CardHeader>
      <CardContent>
        <ul className="flex flex-col gap-2 text-sm">
          {drafts.map((d) => (
            <li
              key={d.id}
              className="flex flex-col gap-0.5 rounded-md border border-[var(--color-line)] px-3 py-2"
              data-testid={`today-draft-${d.id}`}
            >
              <div className="flex items-baseline justify-between gap-2">
                <Link
                  href={`/app/matters/${d.matter.id}/drafts/${d.id}`}
                  className="font-medium text-[var(--color-ink)] hover:underline"
                >
                  {d.matter.matter_code} — {d.title}
                </Link>
                <span className="tabular text-xs text-[var(--color-mute)]">
                  {d.template_type ?? d.draft_type}
                </span>
              </div>
              <p className="text-xs text-[var(--color-mute)]">{d.matter.title}</p>
            </li>
          ))}
        </ul>
        <TruncationNote truncated={truncated} limit={limit} />
      </CardContent>
    </Card>
  );
}

function OverdueInvoicesCard({
  invoices,
  truncated,
  limit,
}: {
  invoices: TodayInvoice[];
  truncated?: boolean;
  limit?: number;
}) {
  if (invoices.length === 0) {
    return (
      <Card data-testid="today-overdue-invoices">
        <CardHeader>
          <CardTitle as="h2">
            <Receipt className="mr-2 inline-block h-4 w-4" aria-hidden />
            Overdue invoices
          </CardTitle>
          <CardDescription>Nothing overdue. Collections clean.</CardDescription>
        </CardHeader>
      </Card>
    );
  }
  return (
    <Card data-testid="today-overdue-invoices" className="lg:col-span-2">
      <CardHeader>
        <CardTitle as="h2">
          <AlertTriangle
            className="mr-2 inline-block h-4 w-4 text-red-700"
            aria-hidden
          />
          Overdue invoices ({invoices.length})
        </CardTitle>
        <CardDescription>
          Invoices past their due date — chase or write off.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ul className="flex flex-col gap-2 text-sm">
          {invoices.map((inv) => (
            <li
              key={inv.id}
              className="flex flex-col gap-0.5 rounded-md border border-red-200 bg-red-50 px-3 py-2"
              data-testid={`today-invoice-${inv.id}`}
            >
              <div className="flex items-baseline justify-between gap-2">
                <Link
                  href={`/app/matters/${inv.matter.id}/billing`}
                  className="font-medium text-red-900 hover:underline"
                >
                  {inv.matter.matter_code} — {inv.invoice_number ?? "(no number)"}
                </Link>
                <span className="tabular text-xs text-red-900">
                  {formatAmount(inv.total_amount_minor, inv.currency)} ·{" "}
                  {inv.days_overdue}d overdue
                </span>
              </div>
              <p className="text-xs text-red-900/80">
                Due {formatDate(inv.due_on)} · {inv.status} · {inv.matter.title}
              </p>
            </li>
          ))}
        </ul>
        <TruncationNote truncated={truncated} limit={limit} />
      </CardContent>
    </Card>
  );
}

function SkeletonGrid() {
  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <Skeleton className="h-48 w-full" />
      <Skeleton className="h-48 w-full" />
      <Skeleton className="h-48 w-full" />
      <Skeleton className="h-48 w-full" />
    </div>
  );
}

function formatDate(iso: string): string {
  return formatLegalDate(iso, {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

function formatAmount(amountMinor: number, currency: string): string {
  return `${currency} ${(amountMinor / 100).toLocaleString(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  })}`;
}

// Suppress import-unused warnings for icons used dynamically above.
const _icons = [FileText];
void _icons;
