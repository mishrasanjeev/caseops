"use client";

import { useQuery } from "@tanstack/react-query";
import { Sparkles, Users } from "lucide-react";

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
    <li className="flex flex-col gap-1.5 rounded-lg border border-[var(--color-line)] bg-[var(--color-bg)] px-3 py-2.5">
      <div className="flex items-start justify-between gap-3">
        <div className="flex flex-col">
          <span className="text-sm font-semibold text-[var(--color-ink)]">
            {rec.counsel_name}
          </span>
          <span className="text-[11px] text-[var(--color-mute-2)]">
            {rec.total_matters_count} matter{rec.total_matters_count === 1 ? "" : "s"}
            {rec.active_matters_count > 0 ? ` · ${rec.active_matters_count} active` : ""}
            {rec.approved_spend_minor > 0
              ? ` · ${formatMoney(rec.approved_spend_minor)} approved spend`
              : ""}
          </span>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1">
          <span className="tabular text-sm font-semibold text-[var(--color-ink)]">
            {formatScore(rec.score)}
          </span>
          <StatusBadge status={rec.panel_status} />
        </div>
      </div>
      {rec.evidence.length > 0 ? (
        <ul className="flex flex-wrap gap-1.5">
          {rec.evidence.slice(0, 4).map((reason) => (
            <li
              key={reason}
              className="inline-flex items-center rounded-full border border-[var(--color-line)] bg-white px-2 py-0.5 text-[10px] text-[var(--color-mute)]"
            >
              {reason}
            </li>
          ))}
        </ul>
      ) : null}
    </li>
  );
}

export function CounselRecommendationsCard({ matterId }: { matterId: string }) {
  const canRecommend = useCapability("outside_counsel:recommend");
  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: ["outside-counsel", "recommendations", matterId],
    queryFn: () => fetchOutsideCounselRecommendations({ matterId, limit: 5 }),
    enabled: canRecommend,
    staleTime: 5 * 60_000,
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
          <ul className="flex flex-col gap-2">
            {data.results.map((rec) => (
              <CounselRow key={rec.counsel_id} rec={rec} />
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
