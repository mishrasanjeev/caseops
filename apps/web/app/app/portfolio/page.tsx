"use client";

import { useQuery } from "@tanstack/react-query";
import { Briefcase, PanelsTopLeft } from "lucide-react";
import Link from "next/link";
import { useMemo } from "react";

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

function bucketize<T>(items: T[], key: (item: T) => string): Map<string, T[]> {
  const map = new Map<string, T[]>();
  for (const item of items) {
    const k = key(item) || "—";
    const bucket = map.get(k) ?? [];
    bucket.push(item);
    map.set(k, bucket);
  }
  return map;
}

function sortBuckets<T>(buckets: Map<string, T[]>): [string, T[]][] {
  return [...buckets.entries()].sort((a, b) => b[1].length - a[1].length);
}

export default function PortfolioPage() {
  const mattersQuery = useQuery({
    queryKey: ["matters", "portfolio"],
    queryFn: () => listMatters({ limit: 500 }),
  });

  const matters = mattersQuery.data?.matters ?? [];
  const byStatus = useMemo(() => bucketize(matters, (m) => m.status), [matters]);
  const byForum = useMemo(
    () => bucketize(matters, (m) => m.forum_level ?? "—"),
    [matters],
  );
  const byPracticeArea = useMemo(
    () => bucketize(matters, (m) => m.practice_area ?? "Unspecified"),
    [matters],
  );

  const upcomingThisWeek = matters.filter((m) => {
    if (!m.next_hearing_on) return false;
    const d = new Date(m.next_hearing_on);
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const weekOut = new Date(today);
    weekOut.setDate(weekOut.getDate() + 7);
    return d >= today && d <= weekOut;
  });

  const withoutActivity = matters.filter((m) => {
    if (m.status !== "active") return false;
    const lastTouch = new Date(m.updated_at ?? m.created_at);
    const daysIdle = (Date.now() - lastTouch.getTime()) / (24 * 60 * 60 * 1000);
    return daysIdle > 30;
  });

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Portfolio"
        title="Portfolio health"
        description="Firm-wide roll-up. Break-outs by status, forum, and practice area; plus an at-a-glance list of matters that need attention."
      />

      {mattersQuery.isPending ? (
        <div className="flex flex-col gap-3">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-64 w-full" />
        </div>
      ) : mattersQuery.isError ? (
        <QueryErrorState
          title="Could not load the portfolio"
          error={mattersQuery.error}
          onRetry={mattersQuery.refetch}
        />
      ) : matters.length === 0 ? (
        <EmptyState
          icon={PanelsTopLeft}
          title="No matters yet"
          description="Create your first matter to populate the portfolio view."
        />
      ) : (
        <>
          <section className="grid gap-4 md:grid-cols-4">
            <KpiCard
              label="Total matters"
              value={matters.length}
              hint={`${matters.filter((m) => m.status === "active").length} active`}
            />
            <KpiCard
              label="In intake"
              value={matters.filter((m) => m.status === "intake").length}
              hint="Awaiting kickoff"
            />
            <KpiCard
              label="Hearings this week"
              value={upcomingThisWeek.length}
              hint="Across open matters"
            />
            <KpiCard
              label="Active + idle > 30d"
              value={withoutActivity.length}
              hint="Active but untouched in the last month"
            />
          </section>

          <section className="grid gap-5 lg:grid-cols-3">
            <BucketCard
              title="By status"
              description="How your book is distributed across lifecycle stages."
              entries={sortBuckets(byStatus)}
              renderLabel={(s) => <StatusBadge status={s} />}
            />
            <BucketCard
              title="By forum"
              description="Court mix — are you a SC shop, an HC shop, or tribunal-heavy?"
              entries={sortBuckets(byForum)}
              renderLabel={(forum) => (
                <span className="text-sm font-medium text-[var(--color-ink)]">
                  {forum.replace(/_/g, " ")}
                </span>
              )}
            />
            <BucketCard
              title="By practice area"
              description="Where your fee-earners are actually working."
              entries={sortBuckets(byPracticeArea)}
              renderLabel={(area) => (
                <span className="text-sm font-medium text-[var(--color-ink)]">
                  {area}
                </span>
              )}
            />
          </section>

          {withoutActivity.length > 0 ? (
            <Card>
              <CardHeader>
                <CardTitle>Needs a nudge</CardTitle>
                <CardDescription>
                  Active matters with no edits in the last 30 days. Pull one
                  forward or close it.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <ul className="divide-y divide-[var(--color-line-2)]">
                  {withoutActivity.slice(0, 10).map((matter) => (
                    <li key={matter.id} className="py-3">
                      <MatterRow matter={matter} />
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          ) : null}
        </>
      )}
    </div>
  );
}

function KpiCard({
  label,
  value,
  hint,
}: {
  label: string;
  value: number;
  hint: string;
}) {
  return (
    <Card>
      <CardContent className="flex flex-col gap-1 py-5">
        <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--color-mute-2)]">
          {label}
        </div>
        <div className="tabular text-2xl font-semibold tracking-tight text-[var(--color-ink)]">
          {value.toLocaleString()}
        </div>
        <div className="text-xs text-[var(--color-mute)]">{hint}</div>
      </CardContent>
    </Card>
  );
}

function BucketCard({
  title,
  description,
  entries,
  renderLabel,
}: {
  title: string;
  description: string;
  entries: [string, Matter[]][];
  renderLabel: (key: string) => React.ReactNode;
}) {
  const total = entries.reduce((acc, [, list]) => acc + list.length, 0);
  return (
    <Card>
      <CardHeader>
        <CardTitle as="h2" className="text-base">
          {title}
        </CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent>
        <ul className="flex flex-col gap-2">
          {entries.map(([key, list]) => {
            const pct = total > 0 ? (list.length / total) * 100 : 0;
            return (
              <li
                key={key}
                className="rounded-md border border-[var(--color-line)] bg-white p-2.5"
              >
                <div className="flex items-center justify-between gap-3">
                  <div>{renderLabel(key)}</div>
                  <div className="text-xs text-[var(--color-mute)]">
                    {list.length} · {pct.toFixed(0)}%
                  </div>
                </div>
                <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-[var(--color-bg-2)]">
                  <div
                    className="h-full bg-[var(--color-brand-500)]"
                    style={{ width: `${pct}%` }}
                  />
                </div>
              </li>
            );
          })}
        </ul>
      </CardContent>
    </Card>
  );
}

function MatterRow({ matter }: { matter: Matter }) {
  return (
    <Link
      href={`/app/matters/${matter.id}`}
      className="flex items-center justify-between gap-3 rounded-md px-2 py-1.5 transition-colors hover:bg-[var(--color-bg-2)]"
    >
      <div className="min-w-0 flex items-center gap-2">
        <Briefcase className="h-4 w-4 text-[var(--color-mute)]" aria-hidden />
        <div className="min-w-0">
          <div className="truncate text-sm font-medium text-[var(--color-ink)]">
            {matter.title}
          </div>
          <div className="truncate text-xs text-[var(--color-mute)]">
            {matter.matter_code} · {matter.practice_area ?? "—"}
          </div>
        </div>
      </div>
      <StatusBadge status={matter.status} />
    </Link>
  );
}
