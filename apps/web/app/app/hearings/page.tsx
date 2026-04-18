"use client";

import { useQuery } from "@tanstack/react-query";
import { Calendar, Gavel } from "lucide-react";
import Link from "next/link";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { listMatters } from "@/lib/api/endpoints";
import type { Matter } from "@/lib/api/schemas";
import { formatLegalDate } from "@/lib/dates";

type BucketKey = "past-due" | "this-week" | "next-7-30" | "later";

const BUCKET_TITLES: Record<BucketKey, string> = {
  "past-due": "Past listing date",
  "this-week": "This week",
  "next-7-30": "Next 30 days",
  later: "Later",
};

const BUCKET_ORDER: BucketKey[] = ["past-due", "this-week", "next-7-30", "later"];

function bucketFor(hearingDate: string): BucketKey {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const date = new Date(hearingDate);
  const diff = Math.floor((date.getTime() - today.getTime()) / (24 * 60 * 60 * 1000));
  if (diff < 0) return "past-due";
  if (diff <= 7) return "this-week";
  if (diff <= 30) return "next-7-30";
  return "later";
}

export default function AllHearingsPage() {
  const mattersQuery = useQuery({
    queryKey: ["matters", "hearings-aggregate"],
    queryFn: () => listMatters({ limit: 200 }),
  });

  const withHearings = (mattersQuery.data?.matters ?? [])
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

      {mattersQuery.isPending ? (
        <div className="flex flex-col gap-3">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-64 w-full" />
        </div>
      ) : mattersQuery.isError ? (
        <QueryErrorState
          title="Could not load hearings"
          error={mattersQuery.error}
          onRetry={mattersQuery.refetch}
        />
      ) : withHearings.length === 0 ? (
        <EmptyState
          icon={Gavel}
          title="No hearings scheduled"
          description="Add a next-hearing date to any matter and it will show up here bucketed by urgency."
        />
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
                        <HearingRow matter={matter} />
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

function HearingRow({ matter }: { matter: Matter }) {
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
        <StatusBadge status={matter.status} />
      </div>
    </Link>
  );
}
