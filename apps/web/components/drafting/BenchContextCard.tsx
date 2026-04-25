"use client";

/**
 * BAAD-001 slice 4 (Sprint P5, 2026-04-25).
 *
 * Surfaces the evidence-cited bench history that backs the appeal-
 * drafting flow. Renders ONLY when the calling stepper has a
 * matter_id selected and the template is `appeal_memorandum`.
 *
 * Bench-aware drafting hard rules enforced at this surface:
 * - No favorability copy. The card reads "in the indexed decisions
 *   provided" or shows an enumerated count + sample authority IDs.
 * - When `context_quality` is "low" or "none", the card hides the
 *   pattern detail and shows a one-line limitation note instead, so
 *   the lawyer can't accidentally rely on a thin signal.
 * - Every pattern row carries the supporting authority IDs the
 *   drafting prompt was given — full audit trail in the UI.
 */

import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  BookOpenCheck,
  Gavel,
  Info,
  ShieldCheck,
  Target,
} from "lucide-react";

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
import { fetchBenchStrategyContext } from "@/lib/api/endpoints";

export function BenchContextCard({ matterId }: { matterId: string }) {
  const ctxQuery = useQuery({
    queryKey: ["bench-strategy-context", matterId],
    queryFn: () => fetchBenchStrategyContext(matterId),
    enabled: matterId.length > 0,
    // Stale after 5 min — this is a slow-moving signal.
    staleTime: 5 * 60_000,
  });

  if (ctxQuery.isPending) {
    return (
      <Card data-testid="bench-context-card-loading">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Gavel className="h-4 w-4" /> Bench history context
          </CardTitle>
          <CardDescription>
            Looking up indexed decisions from the assigned judge or
            likely bench…
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Skeleton className="h-24 w-full" />
        </CardContent>
      </Card>
    );
  }

  if (ctxQuery.isError) {
    return (
      <QueryErrorState
        title="Could not load bench history context"
        error={ctxQuery.error}
        onRetry={() => ctxQuery.refetch()}
      />
    );
  }

  const ctx = ctxQuery.data;
  if (!ctx) return null;

  const qualityTone: "brand" | "neutral" | "warning" =
    ctx.context_quality === "high"
      ? "brand"
      : ctx.context_quality === "medium"
        ? "neutral"
        : "warning";

  return (
    <Card data-testid="bench-context-card">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Gavel className="h-4 w-4" /> Bench history context
          <Badge tone={qualityTone}>{ctx.context_quality}</Badge>
        </CardTitle>
        <CardDescription>
          Evidence-cited summary of how the assigned judge or likely
          bench has decided similar matters. Used by the appeal-draft
          generator. <strong>No favorability scoring.</strong>
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="grid gap-3 sm:grid-cols-3">
          <Stat
            icon={ShieldCheck}
            label="Structured-match coverage"
            value={`${ctx.structured_match_coverage_percent}%`}
          />
          <Stat
            icon={BookOpenCheck}
            label="Citable indexed decisions"
            value={String(ctx.similar_authorities.length)}
          />
          <Stat
            icon={Gavel}
            label="Judge candidates"
            value={String(ctx.judge_candidates.length)}
          />
        </div>

        {ctx.context_quality === "low" || ctx.context_quality === "none" ? (
          <p
            className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900"
            data-testid="bench-context-fallback-note"
          >
            Bench-history evidence is sparse for this matter. The
            appeal draft will fall back to general appellate framing
            and add a visible limitation note in the grounds section
            — by design.
          </p>
        ) : (
          <>
            {ctx.practice_area_patterns.length > 0 ? (
              <Section title="Practice-area concentration">
                <ul className="flex flex-col gap-1.5 text-sm">
                  {ctx.practice_area_patterns.map((p) => (
                    <li
                      key={p.area}
                      className="flex items-baseline justify-between gap-3 border-b border-dashed border-[var(--color-line)] pb-1 last:border-b-0"
                      data-testid={`bench-context-area-${p.area}`}
                    >
                      <span className="text-[var(--color-ink-2)]">
                        {p.area}
                      </span>
                      <span className="tabular text-xs text-[var(--color-mute)]">
                        {p.authority_count} indexed decisions
                      </span>
                    </li>
                  ))}
                </ul>
              </Section>
            ) : null}

            {ctx.recurring_tests.length > 0 ? (
              <Section title="Recurring legal tests in the indexed decisions">
                <ul className="flex flex-col gap-1.5 text-sm">
                  {ctx.recurring_tests.map((t) => (
                    <li
                      key={t.phrase}
                      className="flex items-baseline justify-between gap-3 border-b border-dashed border-[var(--color-line)] pb-1 last:border-b-0"
                      data-testid={`bench-context-test-${t.phrase}`}
                    >
                      <span className="text-[var(--color-ink-2)]">
                        {t.phrase}
                      </span>
                      <span className="tabular text-xs text-[var(--color-mute)]">
                        {t.occurrences}× across the indexed decisions
                      </span>
                    </li>
                  ))}
                </ul>
              </Section>
            ) : null}
          </>
        )}

        {/* Slice C (MOD-TS-001-D, 2026-04-25). Bench-specific block —
            authorities authored by the SPECIFIC bench scheduled to
            hear the next listing. Per PRD §2.1, advocate-bias
            selection: items tagged `practice_area` were chosen
            because they support the matter's practice area. */}
        {ctx.bench_specific_authorities &&
        ctx.bench_specific_authorities.length > 0 ? (
          <Section title="Specific bench (next hearing) — selected to support your case">
            <ul
              className="flex flex-col gap-2 text-sm"
              data-testid="bench-context-specific-list"
            >
              {ctx.bench_specific_authorities.map((a) => (
                <li
                  key={a.id}
                  className="flex items-start gap-2 rounded-md border border-[var(--color-line)] bg-white px-3 py-2"
                  data-testid={`bench-context-specific-${a.id}`}
                >
                  <Target
                    className="mt-0.5 h-4 w-4 shrink-0 text-[var(--color-brand-600)]"
                    aria-hidden
                  />
                  <div className="min-w-0 flex-1">
                    <div className="font-medium text-[var(--color-ink)]">
                      {a.title}
                    </div>
                    <div className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-[var(--color-mute)]">
                      {a.decision_date ? <span>{a.decision_date}</span> : null}
                      {a.case_reference ? (
                        <span className="font-mono">· {a.case_reference}</span>
                      ) : null}
                      {a.neutral_citation ? (
                        <span className="font-mono">
                          · {a.neutral_citation}
                        </span>
                      ) : null}
                      {a.relevance === "practice_area" ? (
                        <Badge tone="brand">practice-area match</Badge>
                      ) : null}
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          </Section>
        ) : ctx.bench_specific_limitation_note ? (
          <p
            className="flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900"
            data-testid="bench-context-specific-note"
          >
            <AlertTriangle
              className="mt-0.5 h-3.5 w-3.5 shrink-0"
              aria-hidden
            />
            <span>
              <strong>Specific bench (next hearing):</strong>{" "}
              {ctx.bench_specific_limitation_note}
            </span>
          </p>
        ) : null}

        {ctx.drafting_cautions.length > 0 ? (
          <Section title="Cautions surfaced in the draft summary">
            <ul className="flex flex-col gap-1.5 text-xs text-[var(--color-mute)]">
              {ctx.drafting_cautions.map((c, i) => (
                <li key={i} className="flex items-start gap-1.5">
                  <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
                  <span>{c}</span>
                </li>
              ))}
            </ul>
          </Section>
        ) : null}
      </CardContent>
    </Card>
  );
}


function Stat({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Gavel;
  label: string;
  value: string;
}) {
  return (
    <div className="flex items-start gap-2 rounded-md border border-[var(--color-line)] px-3 py-2">
      <Icon className="mt-0.5 h-4 w-4 text-[var(--color-ink-3)]" aria-hidden />
      <div>
        <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--color-mute-2)]">
          {label}
        </div>
        <div className="tabular text-base font-semibold text-[var(--color-ink)]">
          {value}
        </div>
      </div>
    </div>
  );
}


function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--color-mute-2)]">
        {title}
      </div>
      {children}
    </div>
  );
}
