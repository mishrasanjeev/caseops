"use client";

/**
 * MOD-TS-001-A (Sprint P, 2026-04-25).
 *
 * Per-ground argument-completeness panel rendered alongside the
 * BenchContextCard on the appeal-drafting flow. Frame is "argument
 * completeness", NOT outcome prediction.
 *
 * Bench-aware drafting hard rules (mirrored on the UI):
 * - No favorability copy. The panel never says "you'll win",
 *   "favorable", or "tendency". The backend service enforces this
 *   structurally via _FORBIDDEN_PATTERN; this component just
 *   displays the strings the API returns.
 * - Weak grounds are visually distinct (amber/red) and labelled
 *   as such — the lawyer can't miss them.
 * - Suggestions are concrete and actionable ("Add SC authority",
 *   "Drop ground 4"); they never tell the user the appeal will
 *   succeed or fail.
 */

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, FileText, MinusCircle } from "lucide-react";

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
import { fetchAppealStrength } from "@/lib/api/endpoints";

export function AppealStrengthPanel({ matterId }: { matterId: string }) {
  const q = useQuery({
    queryKey: ["appeal-strength", matterId],
    queryFn: () => fetchAppealStrength(matterId),
    enabled: matterId.length > 0,
    staleTime: 60_000,
  });

  if (q.isPending) {
    return (
      <Card data-testid="appeal-strength-panel-loading">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <FileText className="h-4 w-4" /> Appeal strength
          </CardTitle>
          <CardDescription>
            Scoring per-ground argument completeness…
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Skeleton className="h-32 w-full" />
        </CardContent>
      </Card>
    );
  }

  if (q.isError) {
    return (
      <QueryErrorState
        title="Could not load appeal strength"
        error={q.error}
        onRetry={() => q.refetch()}
      />
    );
  }

  const rep = q.data;
  if (!rep) return null;

  const overallTone: "brand" | "neutral" | "warning" =
    rep.overall_strength === "strong"
      ? "brand"
      : rep.overall_strength === "moderate"
        ? "neutral"
        : "warning";

  return (
    <Card data-testid="appeal-strength-panel">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <FileText className="h-4 w-4" /> Appeal strength
          <Badge tone={overallTone}>{rep.overall_strength}</Badge>
        </CardTitle>
        <CardDescription>
          Per-ground argument completeness. Frame: argument coverage,
          not outcome prediction. <strong>No win/lose scoring.</strong>
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {!rep.has_draft ? (
          <p
            className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900"
            data-testid="appeal-strength-no-draft-note"
          >
            No appeal-memorandum draft on this matter yet. Per-ground
            scoring needs draft text. Start a draft from the Drafting
            stepper.
          </p>
        ) : null}

        {rep.ground_assessments.length > 0 ? (
          <ul className="flex flex-col gap-3">
            {rep.ground_assessments.map((g) => {
              const tone =
                g.citation_coverage === "supported"
                  ? "brand"
                  : g.citation_coverage === "partial"
                    ? "neutral"
                    : "warning";
              const Icon =
                g.citation_coverage === "supported"
                  ? CheckCircle2
                  : g.citation_coverage === "partial"
                    ? MinusCircle
                    : AlertTriangle;
              return (
                <li
                  key={g.ordinal}
                  className="flex flex-col gap-1.5 rounded-md border border-[var(--color-line)] px-3 py-2"
                  data-testid={`appeal-strength-ground-${g.ordinal}`}
                >
                  <div className="flex items-baseline justify-between gap-3">
                    <div className="flex items-center gap-2">
                      <Icon className="h-3.5 w-3.5" aria-hidden />
                      <span className="text-sm font-medium text-[var(--color-ink)]">
                        Ground {g.ordinal}
                      </span>
                      <Badge tone={tone}>{g.citation_coverage}</Badge>
                    </div>
                    {g.supporting_authorities.length > 0 ? (
                      <span className="tabular text-xs text-[var(--color-mute)]">
                        {g.supporting_authorities.length} cited
                      </span>
                    ) : null}
                  </div>
                  <p className="text-xs text-[var(--color-ink-2)]">
                    {g.summary}
                  </p>
                  {g.supporting_authorities.length > 0 ? (
                    <ul className="flex flex-wrap gap-1.5">
                      {g.supporting_authorities.map((ref) => (
                        <li
                          key={ref.citation}
                          className="inline-flex items-center gap-1 rounded-md border border-[var(--color-line)] bg-[var(--color-bg)] px-2 py-0.5 text-[10px] text-[var(--color-ink-2)]"
                        >
                          <span className="font-mono">{ref.citation}</span>
                          <span className="text-[var(--color-mute)]">
                            · {ref.strength_label}
                          </span>
                        </li>
                      ))}
                    </ul>
                  ) : null}
                  {g.suggestions.length > 0 ? (
                    <ul className="mt-1 flex flex-col gap-1">
                      {g.suggestions.map((s, i) => (
                        <li
                          key={i}
                          className="text-xs text-[var(--color-mute)]"
                        >
                          → {s}
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </li>
              );
            })}
          </ul>
        ) : null}

        {rep.weak_evidence_paths.length > 0 ? (
          <Section title="Weak-evidence paths (address before submission)">
            <ul className="flex flex-col gap-1.5 text-xs text-amber-900">
              {rep.weak_evidence_paths.map((p, i) => (
                <li key={i} className="flex items-start gap-1.5">
                  <AlertTriangle
                    className="mt-0.5 h-3.5 w-3.5 shrink-0"
                    aria-hidden
                  />
                  <span>{p}</span>
                </li>
              ))}
            </ul>
          </Section>
        ) : null}

        {rep.recommended_edits.length > 0 ? (
          <Section title="Recommended edits">
            <ul className="flex flex-col gap-1.5 text-xs text-[var(--color-mute)]">
              {rep.recommended_edits.map((e, i) => (
                <li key={i}>→ {e}</li>
              ))}
            </ul>
          </Section>
        ) : null}
      </CardContent>
    </Card>
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
