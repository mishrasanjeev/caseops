"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronDown, Sparkles, Users } from "lucide-react";

import { formatCounselAmount } from "@/components/app/CounselCurrencyTotals";
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
import { StatusBadge } from "@/components/ui/StatusBadge";
import {
  fetchOutsideCounselRecommendations,
  type OutsideCounselRecommendation,
} from "@/lib/api/endpoints";
import { useCapability } from "@/lib/capabilities";
import { useSequencedQuerySettled } from "@/lib/use-sequenced-query-settled";

function CounselRow({ rec }: { rec: OutsideCounselRecommendation }) {
  const spend = rec.approved_spend_by_currency;
  const evidence = rec.evidence.filter((reason) =>
    !/^Approved spend history totals \d+ minor units across prior matters\.$/.test(reason),
  );
  return (
    // Every closed card has the same width and height: the name takes exactly
    // two lines (full name on hover, and unclamped once the card is open), and the face carries
    // the same single-line rows for every counsel. The grid aligns cards to the
    // top, so opening one never stretches its neighbours (Nov 24 row 6, B5-016).
    // The face's lines sit at the same height in every card of a row.
    <li
      className="flex min-w-0 flex-col rounded-lg border border-[var(--color-line)] bg-[var(--color-bg)]"
      data-testid="counsel-recommendation"
    >
      <details className="group">
        <summary tabIndex={0} className="flex min-h-11 cursor-pointer list-none flex-col gap-1.5 rounded-lg px-3 py-2.5 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 [&::-webkit-details-marker]:hidden">
          <span className="flex min-w-0 items-start justify-between gap-2">
            <span
              className="line-clamp-2 h-10 min-w-0 group-open:line-clamp-none group-open:h-auto text-sm font-semibold leading-5 text-[var(--color-ink)] [overflow-wrap:anywhere]"
              title={rec.counsel_name}
              data-testid="counsel-name"
            >
              {rec.counsel_name}
            </span>
            <ChevronDown className="mt-0.5 h-4 w-4 shrink-0 group-open:rotate-180" aria-hidden />
          </span>
          <span className="flex min-w-0 items-center justify-between gap-2" data-testid="counsel-score-row">
            <span className="tabular shrink-0 text-sm font-semibold text-[var(--color-ink)]">
              {rec.score} pts
            </span>
            <StatusBadge status={rec.panel_status} className="whitespace-nowrap" />
          </span>
          <span className="truncate text-[11px] text-[var(--color-mute-2)]">
            {rec.total_matters_count} matter{rec.total_matters_count === 1 ? "" : "s"}
            {rec.active_matters_count > 0 ? ` · ${rec.active_matters_count} active` : ""}
          </span>
        </summary>
        <div className="space-y-2 border-t border-[var(--color-line)] px-3 py-2">
          {spend?.length ? (
            <div className="text-xs text-[var(--color-mute)]">
              <p className="font-medium">Approved spend</p>
              <dl aria-label="Approved spend by currency" className="mt-1 space-y-1 tabular-nums">
                {spend.map(({ currency, approved_spend_minor: amount }) => (
                  <div key={currency} className="flex flex-wrap gap-x-2">
                    <dt>{currency || "Unknown currency"}</dt>
                    <dd>{formatCounselAmount(amount, currency)}</dd>
                  </div>
                ))}
              </dl>
            </div>
          ) : spend === undefined && rec.approved_spend_minor > 0 ? (
            <p className="text-xs text-[var(--color-mute)]">Approved spend by currency is unavailable.</p>
          ) : null}
          {evidence.length > 0 ? (
            <ul className="space-y-1 break-words text-xs text-[var(--color-mute)]">
              {evidence.map((reason) => <li key={reason}>{reason}</li>)}
            </ul>
          ) : null}
        </div>
      </details>
    </li>
  );
}

export function CounselRecommendationsCard({
  matterId,
  loadEnabled = true,
  onLoadSettled,
  className,
}: {
  matterId: string;
  /** Placement in the parent grid (the overview gives it a full row). */
  className?: string;
  loadEnabled?: boolean;
  onLoadSettled?: () => void;
}) {
  const canRecommend = useCapability("outside_counsel:recommend");
  const query = useQuery({
    queryKey: ["outside-counsel", "recommendations", matterId],
    queryFn: ({ signal }) =>
      fetchOutsideCounselRecommendations({ matterId, limit: 5 }, { signal }),
    enabled: canRecommend && loadEnabled,
    staleTime: 5 * 60_000,
  });
  const { data, isPending, isError, error, refetch } = query;
  useSequencedQuerySettled({
    enabled: loadEnabled,
    identity: matterId,
    settled: !canRecommend || query.isFetched,
    onSettled: onLoadSettled,
  });

  if (!canRecommend) {
    return null;
  }

  return (
    <Card className={className} data-testid="counsel-recommendations-card">
      <CardHeader>
        <div className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-[var(--color-brand-500)]" aria-hidden />
          <CardTitle>Suggested counsel</CardTitle>
        </div>
        <CardDescription>
          Ranked from your panel by practice fit, jurisdiction, and relevant matter experience.
          Partner approves any engagement.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {isPending ? (
          <div className="flex flex-col gap-2">
            <Skeleton className="h-14 w-full" />
            <Skeleton className="h-14 w-full" />
          </div>
        ) : isError ? (
          <QueryErrorState
            title="Could not load recommendations"
            error={error}
            onRetry={refetch}
          />
        ) : !data || data.results.length === 0 ? (
          <EmptyState
            icon={Users}
            title="No counsel suggestions yet"
            description="Add counsel to the panel and we'll rank them for this matter."
          />
        ) : (
          // Up to five equal columns in one row; narrower screens and higher
          // zoom drop to fewer columns, never to uneven widths.
          <ul
            className="grid items-start gap-3 [grid-template-columns:repeat(auto-fill,minmax(max(min(100%,11.5rem),calc((100%_-_3rem)/5)),1fr))]"
            data-testid="counsel-recommendations-grid"
          >
            {data.results.map((rec) => (
              <CounselRow key={rec.counsel_id} rec={rec} />
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
