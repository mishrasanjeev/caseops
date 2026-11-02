"use client";

import { useQuery } from "@tanstack/react-query";
import { Briefcase, PanelsTopLeft } from "lucide-react";
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
import { fetchMatterPortfolioHealth } from "@/lib/api/endpoints";
import type { Matter } from "@/lib/api/schemas";

type Bucket = { key: string | null; count: number };

/**
 * Firm-wide roll-up counted on the server over every Matter the user can see.
 * The page used to bucket one list page (at most 200 Matters), so a larger
 * book showed wrong totals with no sign of a cap (B4-ADJ-03).
 */
export default function PortfolioPage() {
  const healthQuery = useQuery({
    queryKey: ["matters", "portfolio-health"],
    queryFn: fetchMatterPortfolioHealth,
  });
  const health = healthQuery.data;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Portfolio"
        title="Portfolio health"
        description="Firm-wide roll-up of every matter you can see. Break-outs by status, forum, and practice area; plus the active matters that need attention."
      />

      {healthQuery.isPending ? (
        <div className="flex flex-col gap-3">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-64 w-full" />
        </div>
      ) : healthQuery.isError || !health ? (
        <QueryErrorState
          title="Could not load the portfolio"
          error={healthQuery.error}
          onRetry={healthQuery.refetch}
        />
      ) : health.total_visible_count === 0 ? (
        <EmptyState
          icon={PanelsTopLeft}
          title="No matters yet"
          description="Create your first matter to populate the portfolio view. Matters behind an ethical wall are not counted."
        />
      ) : (
        <>
          <section className="grid gap-4 md:grid-cols-4">
            <KpiCard
              label="Total matters"
              value={health.total_visible_count}
              hint={`${health.active_matters_count.toLocaleString()} active`}
            />
            <KpiCard
              label="In intake"
              value={health.intake_matters_count}
              hint="Awaiting kickoff"
            />
            <KpiCard
              label="Hearings this week"
              value={health.hearings_next_7_days_count}
              hint="Across open matters"
            />
            <KpiCard
              label={`Active + idle > ${health.idle_after_days}d`}
              value={health.idle_active_count}
              hint="Active but untouched in the last month"
            />
          </section>

          <section className="grid gap-5 lg:grid-cols-3">
            <BucketCard
              title="By status"
              description="How your book is distributed across lifecycle stages."
              entries={health.status_counts}
              renderLabel={(s) => <StatusBadge status={s} />}
            />
            <BucketCard
              title="By forum"
              description="Court mix — are you a SC shop, an HC shop, or tribunal-heavy?"
              entries={health.forum_level_counts}
              renderLabel={(forum) => (
                <span className="text-sm font-medium text-[var(--color-ink)]">
                  {forum.replace(/_/g, " ")}
                </span>
              )}
            />
            <BucketCard
              title="By practice area"
              description="Where your fee-earners are actually working."
              entries={health.practice_area_counts}
              emptyLabel="Unspecified"
              renderLabel={(area) => (
                <span className="text-sm font-medium text-[var(--color-ink)]">
                  {area}
                </span>
              )}
            />
          </section>

          {health.idle_active_count > 0 ? (
            <Card>
              <CardHeader>
                <CardTitle>Needs a nudge</CardTitle>
                <CardDescription>
                  Active matters with no edits in the last {health.idle_after_days} days, longest idle first. Pull one
                  forward or close it.
                </CardDescription>
              </CardHeader>
              <CardContent className="flex flex-col gap-2">
                <ul className="divide-y divide-[var(--color-line-2)]">
                  {health.idle_active_matters.map((matter) => (
                    <li key={matter.id} className="py-3">
                      <MatterRow matter={matter} />
                    </li>
                  ))}
                </ul>
                {health.idle_active_count > health.idle_active_matters.length ? (
                  <p role="status" className="text-sm text-[var(--color-mute)]" data-testid="portfolio-idle-cap">
                    Showing the {health.idle_active_matters.length} longest-idle of{" "}
                    {health.idle_active_count.toLocaleString()} idle active matters.{" "}
                    <Link className="font-semibold text-[var(--color-brand-700)]" href="/app/matters">
                      Open the matter list
                    </Link>
                  </p>
                ) : null}
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

/**
 * Merge the server's "no value" buckets (NULL and blank) into one, keyed apart
 * from every real value, so a missing value never shares a row or React key
 * with a value.
 */
function withOneEmptyBucket(entries: Bucket[]): Bucket[] {
  const merged = new Map<string | null, number>();
  for (const { key, count } of entries) {
    const normalised = key && key.trim() ? key : null;
    merged.set(normalised, (merged.get(normalised) ?? 0) + count);
  }
  return Array.from(merged, ([key, count]) => ({ key, count }));
}

function BucketCard({
  title,
  description,
  entries: serverEntries,
  emptyLabel = "—",
  renderLabel,
}: {
  title: string;
  description: string;
  entries: Bucket[];
  /** Label for Matters with no value for this field. */
  emptyLabel?: string;
  renderLabel: (key: string) => React.ReactNode;
}) {
  const entries = withOneEmptyBucket(serverEntries);
  const total = entries.reduce((acc, bucket) => acc + bucket.count, 0);
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
          {entries.map(({ key: raw, count }) => {
            const pct = total > 0 ? (count / total) * 100 : 0;
            return (
              <li
                key={raw === null ? "empty-bucket" : `value:${raw}`}
                className="rounded-md border border-[var(--color-line)] bg-white p-2.5"
              >
                <div className="flex items-center justify-between gap-3">
                  <div>
                    {raw === null ? (
                      <span className="text-sm font-medium text-[var(--color-mute)]">{emptyLabel}</span>
                    ) : (
                      renderLabel(raw)
                    )}
                  </div>
                  <div className="text-xs text-[var(--color-mute)]">
                    {count.toLocaleString()} · {pct.toFixed(0)}%
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
