"use client";

/**
 * MOD-TS-018 Phase 4 (2026-04-26). Bench-strategy panel for the
 * matter cockpit.
 *
 * Renders L-A/L-B/L-C analysis layers as:
 * - evidence_quality chip (strong / partial / weak / insufficient)
 * - top authorities the bench has cited (from L-B)
 * - top statute sections the bench engages with (from L-C)
 * - "not legal advice" disclaimer at the bottom
 *
 * Hard rules:
 * - Always renders the disclaimer when any authority/statute row is
 *   present.
 * - When evidence_quality === "insufficient" (bench resolution failed
 *   or fewer than 1 indexed decision), the panel renders a one-line
 *   limitation note instead of empty tables.
 * - Predictive surfaces (judge tendencies, predicted_disposition)
 *   land in a follow-up commit once L-E ships.
 */

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, BookOpenCheck, Gavel, Info, ScrollText } from "lucide-react";

import { Badge } from "@/components/ui/Badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/Card";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { fetchBenchStrategy } from "@/lib/api/endpoints";

const QUALITY_LABELS: Record<string, string> = {
  strong: "Strong evidence base",
  partial: "Partial evidence base",
  weak: "Weak evidence base",
  insufficient: "Insufficient bench history",
};

function qualityTone(q: string): "brand" | "neutral" | "warning" {
  if (q === "strong") return "brand";
  if (q === "partial") return "neutral";
  return "warning";
}

export function BenchStrategyPanel({ matterId }: { matterId: string }) {
  const query = useQuery({
    queryKey: ["bench-strategy", matterId],
    queryFn: () => fetchBenchStrategy(matterId),
    enabled: matterId.length > 0,
    staleTime: 5 * 60_000,
  });

  if (query.isPending) {
    return (
      <Card data-testid="bench-strategy-panel-loading">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Gavel className="h-4 w-4" /> Bench strategy
          </CardTitle>
          <CardDescription>
            Looking up which authorities + statutes this bench has
            engaged with…
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Skeleton className="h-32 w-full" />
        </CardContent>
      </Card>
    );
  }

  if (query.isError) {
    return (
      <QueryErrorState
        title="Could not load bench strategy"
        error={query.error}
        onRetry={() => query.refetch()}
      />
    );
  }

  const data = query.data;
  if (!data) return null;

  const quality = data.evidence_quality;
  const qualityLabel = QUALITY_LABELS[quality] || quality;

  return (
    <Card data-testid="bench-strategy-panel">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Gavel className="h-4 w-4" /> Bench strategy
          <span data-testid="bench-strategy-quality-chip">
            <Badge tone={qualityTone(quality)}>{qualityLabel}</Badge>
          </span>
        </CardTitle>
        <CardDescription>
          What this bench has historically cited in the indexed decisions.
          Sample size: {data.total_decisions_indexed} decisions across{" "}
          {data.bench_judge_ids.length} judge
          {data.bench_judge_ids.length === 1 ? "" : "s"}.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        {quality === "insufficient" ? (
          <div
            className="flex items-start gap-2 rounded-[var(--radius-md)] border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900"
            data-testid="bench-strategy-insufficient-note"
          >
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
            <span>
              We don&apos;t have enough indexed decisions for this
              matter&apos;s bench to surface meaningful patterns yet.
              Either no listing has been resolved, or the bench&apos;s
              decisions haven&apos;t been ingested + Layer-2 enriched.
            </span>
          </div>
        ) : null}

        {data.top_statute_sections.length > 0 ? (
          <section data-testid="bench-strategy-statutes">
            <div className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-[0.12em] text-[var(--color-mute-2)]">
              <ScrollText className="h-3 w-3" aria-hidden />
              Top statute sections cited
            </div>
            <ul className="divide-y divide-[var(--color-line-2)]">
              {data.top_statute_sections.slice(0, 10).map((s) => (
                <li
                  key={s.statute_section_id}
                  className="flex items-start justify-between gap-3 py-2"
                  data-testid={`bench-strategy-statute-${s.statute_section_id}`}
                >
                  <div className="min-w-0">
                    <div className="font-mono text-sm font-semibold text-[var(--color-ink)]">
                      {s.statute_id} · {s.section_number}
                    </div>
                    {s.section_label ? (
                      <div className="truncate text-xs text-[var(--color-mute)]">
                        {s.section_label}
                      </div>
                    ) : null}
                  </div>
                  <div className="shrink-0 text-right text-xs text-[var(--color-mute-2)]">
                    <div className="font-semibold text-[var(--color-ink-2)]">
                      {s.citation_count}×
                    </div>
                    {s.last_year ? <div>last {s.last_year}</div> : null}
                  </div>
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        {data.top_authorities.length > 0 ? (
          <section data-testid="bench-strategy-authorities">
            <div className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-[0.12em] text-[var(--color-mute-2)]">
              <BookOpenCheck className="h-3 w-3" aria-hidden />
              Top authorities cited
            </div>
            <ul className="divide-y divide-[var(--color-line-2)]">
              {data.top_authorities.slice(0, 10).map((a) => (
                <li
                  key={a.authority_id}
                  className="flex items-start justify-between gap-3 py-2"
                  data-testid={`bench-strategy-authority-${a.authority_id}`}
                >
                  <div className="min-w-0">
                    <div className="truncate text-sm text-[var(--color-ink)]">
                      {a.title || a.authority_id}
                    </div>
                  </div>
                  <div className="shrink-0 text-right text-xs text-[var(--color-mute-2)]">
                    <div className="font-semibold text-[var(--color-ink-2)]">
                      {a.citation_count}×
                    </div>
                    {a.last_year ? <div>last {a.last_year}</div> : null}
                  </div>
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        {data.top_authorities.length === 0 &&
        data.top_statute_sections.length === 0 &&
        quality !== "insufficient" ? (
          <div
            className="flex items-start gap-2 rounded-[var(--radius-md)] border border-[var(--color-line)] bg-[var(--color-bg-2)] px-3 py-2 text-xs text-[var(--color-mute)]"
            data-testid="bench-strategy-no-aggregates"
          >
            <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
            <span>
              The bench has indexed decisions in our corpus but the
              citation + statute aggregations haven&apos;t been
              materialised yet. Run{" "}
              <code className="rounded bg-[var(--color-bg)] px-1">
                refresh_bench_analysis_layers
              </code>{" "}
              to populate.
            </span>
          </div>
        ) : null}

        <div
          className="flex items-start gap-2 rounded-[var(--radius-md)] border border-[var(--color-line)] bg-[var(--color-bg-2)] px-3 py-2 text-[10px] leading-snug text-[var(--color-mute-2)]"
          data-testid="bench-strategy-disclaimer"
        >
          <Info className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />
          <span>{data.disclaimer}</span>
        </div>
      </CardContent>
    </Card>
  );
}
