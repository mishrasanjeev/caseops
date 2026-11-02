"use client";

import { type UseInfiniteQueryResult, type InfiniteData, useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { Calendar, CalendarCheck, Gavel } from "lucide-react";
import Link from "next/link";
import { type ReactNode, useState } from "react";

import { Button } from "@/components/ui/Button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Input";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { StatusBadge } from "@/components/ui/StatusBadge";
import {
  fetchMatterHearingFollowUp,
  fetchMatterHearingPortfolio,
} from "@/lib/api/endpoints";
import type { Matter, MatterHearingFollowUp } from "@/lib/api/schemas";
import { useCapability } from "@/lib/capabilities";
import { formatLegalDate, toLocalCalendarDate } from "@/lib/dates";

type BucketKey = "past-due" | "this-week" | "next-7-30" | "later";

const BUCKET_TITLES: Record<BucketKey, string> = {
  "past-due": "Past listing date",
  "this-week": "This week",
  "next-7-30": "Next 30 days",
  later: "Later",
};

const BUCKET_ORDER: BucketKey[] = ["past-due", "this-week", "next-7-30", "later"];

/** Rows per follow-up page; Load more reads the next page of one queue. */
const FOLLOW_UP_PAGE = 50;

type FollowUpQueue = "overdue" | "missing_date";
type FollowUpQuery = UseInfiniteQueryResult<InfiniteData<MatterHearingFollowUp, number>>;

function queueRows(page: MatterHearingFollowUp, queue: FollowUpQueue): Matter[] {
  return queue === "overdue" ? page.overdue_matters : page.missing_date_matters;
}

function queueCount(page: MatterHearingFollowUp, queue: FollowUpQueue): number {
  return queue === "overdue" ? page.overdue_count : page.missing_date_count;
}

function useFollowUpQueue(queue: FollowUpQueue): FollowUpQuery {
  return useInfiniteQuery({
    queryKey: ["matters", "hearing-follow-up", queue],
    queryFn: ({ pageParam }) =>
      fetchMatterHearingFollowUp({ queue, offset: pageParam, limit: FOLLOW_UP_PAGE }),
    initialPageParam: 0,
    getNextPageParam: (last) => {
      const rows = queueRows(last, queue).length;
      const next = last.offset + rows;
      return rows > 0 && next < queueCount(last, queue) ? next : undefined;
    },
  });
}

function bucketFor(hearingDate: string): BucketKey {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const date = toLocalCalendarDate(hearingDate);
  if (!date) return "later";
  const diff = Math.round((date.getTime() - today.getTime()) / (24 * 60 * 60 * 1000));
  if (diff < 0) return "past-due";
  if (diff <= 7) return "this-week";
  if (diff <= 30) return "next-7-30";
  return "later";
}

export default function AllHearingsPage() {
  const canSyncOutlook = useCapability("calendar:sync");
  const [exactDate, setExactDate] = useState("");
  const hearingsQuery = useQuery({
    queryKey: ["matters", "hearing-portfolio", exactDate || "all"],
    queryFn: () =>
      fetchMatterHearingPortfolio({
        date: exactDate || undefined,
        limit: 500,
      }),
  });
  const overdueQuery = useFollowUpQueue("overdue");
  const missingQuery = useFollowUpQueue("missing_date");
  const overdueTotal = overdueQuery.data?.pages.at(-1)?.overdue_count ?? 0;
  const missingTotal = missingQuery.data?.pages.at(-1)?.missing_date_count ?? 0;
  const showFollowUp =
    overdueQuery.isError || missingQuery.isError || overdueTotal > 0 || missingTotal > 0;

  const withHearings = (hearingsQuery.data?.matters ?? [])
    .filter((m) => !!m.next_hearing_on)
    .sort((a, b) =>
      (a.next_hearing_on ?? "").localeCompare(b.next_hearing_on ?? ""),
    );

  const buckets: Record<BucketKey, Matter[]> = {
    "past-due": [],
    "this-week": [],
    "next-7-30": [],
    later: [],
  };
  for (const matter of withHearings) {
    buckets[bucketFor(matter.next_hearing_on!)].push(matter);
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Hearings"
        title="Hearings across your portfolio"
        description="Every open matter with a scheduled hearing, bucketed by urgency. Open a matter to run court-sync or generate a hearing pack."
      />

      <Card>
        <CardHeader>
          <CardTitle as="h2" className="text-base">
            Date filter
          </CardTitle>
          <CardDescription>
            Choose one date to see only matters scheduled for that hearing date.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3 sm:flex-row sm:items-end">
          <Field label="Exact hearing date">
            <Input
              type="date"
              value={exactDate}
              onChange={(event) => setExactDate(event.target.value)}
            />
          </Field>
          {exactDate ? (
            <Button type="button" variant="outline" onClick={() => setExactDate("")}>
              Clear date
            </Button>
          ) : null}
          {hearingsQuery.data ? (
            <div className="pb-2 text-sm text-[var(--color-mute)]">
              {hearingsQuery.data.total_count} matching hearing
              {hearingsQuery.data.total_count === 1 ? "" : "s"}
              {hearingsQuery.data.truncated
                ? `; showing first ${hearingsQuery.data.limit}`
                : ""}
            </div>
          ) : null}
        </CardContent>
      </Card>

      {!exactDate && showFollowUp ? (
        <section className="grid gap-4 lg:grid-cols-2" aria-label="Hearing date follow-up">
          <FollowUpCard
            title="Past listing date"
            description="Active matters whose stored next-hearing date has passed."
            queue="overdue"
            query={overdueQuery}
            loadMoreLabel="Load more past-listing matters"
            canSyncOutlook={canSyncOutlook}
          />
          <FollowUpCard
            title="Missing hearing date"
            description="Active matters with no next-hearing date recorded."
            queue="missing_date"
            query={missingQuery}
            loadMoreLabel="Load more matters missing a date"
            canSyncOutlook={canSyncOutlook}
          />
        </section>
      ) : null}

      {hearingsQuery.isPending ? (
        <div className="flex flex-col gap-3">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-64 w-full" />
        </div>
      ) : hearingsQuery.isError ? (
        <QueryErrorState
          title="Could not load hearings"
          error={hearingsQuery.error}
          onRetry={hearingsQuery.refetch}
        />
      ) : withHearings.length === 0 ? (
        <EmptyState
          icon={Gavel}
          title={exactDate ? "No hearings on this date" : "No hearings scheduled"}
          description={
            exactDate
              ? "Choose another date or clear the filter to see the full hearing portfolio."
              : "Add a next-hearing date to any matter and it will show up here bucketed by urgency."
          }
        />
      ) : exactDate ? (
        <Card>
          <CardHeader>
            <CardTitle as="h2" className="text-base">
              {formatLegalDate(exactDate)} ({withHearings.length})
            </CardTitle>
            <CardDescription>
              Matters whose stored next-hearing date exactly matches the selected date.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <ul className="divide-y divide-[var(--color-line-2)]">
              {withHearings.map((matter) => (
                <li key={matter.id} className="py-3">
                  <HearingRow matter={matter} canSyncOutlook={canSyncOutlook} />
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      ) : (
        <div className="flex flex-col gap-5">
          {BUCKET_ORDER.map((key) => {
            const list = buckets[key];
            if (list.length === 0) return null;
            return (
              <Card key={key}>
                <CardHeader>
                  <CardTitle as="h2" className="text-base">
                    {BUCKET_TITLES[key]} ({list.length})
                  </CardTitle>
                  <CardDescription>
                    {key === "past-due"
                      ? "Listings that appear to have already occurred — record the outcome or reschedule."
                      : key === "this-week"
                        ? "Hearings in the next 7 days."
                        : key === "next-7-30"
                          ? "Hearings between 8 and 30 days out."
                          : "Further out — keep an eye on filing deadlines."}
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <ul className="divide-y divide-[var(--color-line-2)]">
                    {list.map((matter) => (
                      <li key={matter.id} className="py-3">
                        <HearingRow matter={matter} canSyncOutlook={canSyncOutlook} />
                      </li>
                    ))}
                  </ul>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}

function FollowUpCard({
  title,
  description,
  queue,
  query,
  loadMoreLabel,
  canSyncOutlook,
}: {
  title: string;
  description: string;
  queue: FollowUpQueue;
  query: FollowUpQuery;
  loadMoreLabel: string;
  canSyncOutlook: boolean;
}) {
  const pages = query.data?.pages ?? [];
  const total = pages.length ? queueCount(pages[pages.length - 1], queue) : null;
  const seen = new Set<string>();
  const matters = pages
    .flatMap((page) => queueRows(page, queue))
    .filter((matter) => (seen.has(matter.id) ? false : (seen.add(matter.id), true)));
  return (
    <Card>
      <CardHeader>
        <CardTitle as="h2" className="text-base">
          {total === null ? title : `${title} (${total})`}
        </CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent>
        {query.isPending ? (
          <Skeleton className="h-16 w-full" />
        ) : query.isError && matters.length === 0 ? (
          <QueryErrorState
            title={`Could not load the ${title.toLowerCase()} queue`}
            error={query.error}
            onRetry={() => void query.refetch()}
          />
        ) : matters.length === 0 ? (
          <div className="text-sm text-[var(--color-mute)]">No matters in this follow-up queue.</div>
        ) : (
          <ul className="divide-y divide-[var(--color-line-2)]">
            {matters.map((matter) => (
              <li key={matter.id} className="py-3">
                <HearingRow matter={matter} canSyncOutlook={canSyncOutlook} />
              </li>
            ))}
          </ul>
        )}
        {total !== null && matters.length > 0 && matters.length < total ? (
          <div className="mt-2 flex flex-wrap items-center gap-3">
            <p role="status" className="text-sm text-[var(--color-mute)]">
              Showing {matters.length} of {total}.
            </p>
            {query.hasNextPage ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => void query.fetchNextPage()}
                disabled={query.isFetchingNextPage}
              >
                {query.isFetchingNextPage ? "Loading..." : loadMoreLabel}
              </Button>
            ) : null}
          </div>
        ) : null}
        {query.isFetchNextPageError ? (
          <p role="alert" className="mt-2 text-sm text-[var(--color-danger-700)]">
            Could not load more matters. Try Load more again.
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex min-w-0 flex-1 flex-col gap-1 text-sm font-medium text-[var(--color-ink-2)]">
      {label}
      {children}
    </label>
  );
}

function HearingRow({
  matter,
  canSyncOutlook,
}: {
  matter: Matter;
  canSyncOutlook: boolean;
}) {
  const date = formatLegalDate(matter.next_hearing_on, {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
  return (
    <Link
      href={`/app/matters/${matter.id}/hearings`}
      className="flex items-center justify-between gap-3 rounded-md px-2 py-1.5 transition-colors hover:bg-[var(--color-bg-2)]"
    >
      <div className="min-w-0">
        <div className="truncate text-sm font-medium text-[var(--color-ink)]">
          {matter.title}
        </div>
        <div className="truncate text-xs text-[var(--color-mute)]">
          {matter.court_name ?? matter.forum_level ?? matter.matter_code}
          {matter.judge_name ? ` · ${matter.judge_name}` : ""}
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-3">
        <div className="inline-flex items-center gap-1 text-xs font-medium text-[var(--color-ink-2)]">
          <Calendar className="h-3 w-3" aria-hidden /> {date}
        </div>
        {canSyncOutlook ? (
          <span
            className="inline-flex items-center gap-1 text-xs font-medium text-[var(--color-mute)]"
            data-testid="hearings-sync-affordance"
          >
            <CalendarCheck className="h-3 w-3" aria-hidden /> Sync in matter
          </span>
        ) : null}
        <StatusBadge status={matter.status} />
      </div>
    </Link>
  );
}
