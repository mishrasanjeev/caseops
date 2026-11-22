"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronDown, Sparkles, Users } from "lucide-react";

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

function formatScore(score: number): string {
  return Math.round(score * 100).toString();
}

function formatMoney(minor: number): string {
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  }).format(minor / 100);
}

function CounselRow({ rec }: { rec: OutsideCounselRecommendation }) {
  return (
    <li className="min-w-0 rounded-lg border border-[var(--color-line)] bg-[var(--color-bg)]">
      <details className="group">
        <summary tabIndex={0} className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-2 rounded-lg px-3 py-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 [&::-webkit-details-marker]:hidden">
          <span className="min-w-0 break-words text-sm font-semibold text-[var(--color-ink)]">
            {rec.counsel_name}
          </span>
          <span className="flex shrink-0 items-center gap-2">
            <span className="tabular text-sm font-semibold text-[var(--color-ink)]" aria-label={`Panel match score ${formatScore(rec.score)}`}>
              {formatScore(rec.score)}
            </span>
            <ChevronDown className="h-4 w-4 group-open:rotate-180" aria-hidden />
          </span>
        </summary>
        <div className="space-y-2 border-t border-[var(--color-line)] px-3 py-2">
          <StatusBadge status={rec.panel_status} />
          <span className="text-[11px] text-[var(--color-mute-2)]">
            {rec.total_matters_count} matter{rec.total_matters_count === 1 ? "" : "s"}
            {rec.active_matters_count > 0 ? ` · ${rec.active_matters_count} active` : ""}
            {rec.approved_spend_minor > 0
              ? ` · ${formatMoney(rec.approved_spend_minor)} approved spend`
              : ""}
          </span>
          {rec.evidence.length > 0 ? (
            <ul className="space-y-1 break-words text-xs text-[var(--color-mute)]">
              {rec.evidence.map((reason) => <li key={reason}>{reason}</li>)}
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
}: {
  matterId: string;
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
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-[var(--color-brand-500)]" aria-hidden />
          <CardTitle>Suggested counsel</CardTitle>
        </div>
        <CardDescription>
          Ranked from your panel by jurisdiction, practice fit, and prior spend on
          comparable matters. Partner approves any engagement.
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
          <ul className="grid items-start gap-2 sm:grid-cols-2">
            {data.results.map((rec) => (
              <CounselRow key={rec.counsel_id} rec={rec} />
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
