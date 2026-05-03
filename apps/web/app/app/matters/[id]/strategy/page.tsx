"use client";

/**
 * MOD-LSE-5 (2026-05-03). Matter cockpit Strategy sub-tab.
 *
 * Surfaces the litigation strategy + escalation planner for the
 * matter. Lists the most-recent strategy if one exists, plus a
 * Generate button. The strategy card renders:
 *
 *   - Current posture
 *   - Recommended route + alternatives
 *   - Forum sequence timeline (escalation ladder)
 *   - Limitation flags
 *   - Recommended draft pack with one-click Generate buttons
 *   - Required documents + missing facts
 *   - Risks
 *   - Authority citations
 *   - Review-required banner + disclaimer
 *
 * Hard product rule (PRD §2): every strategy is review_required
 * until a partner signs off, and the page never silently swallows a
 * 422 refusal — actionable copy from the backend renders verbatim.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  BadgeCheck,
  CheckCircle2,
  ChevronRight,
  ClipboardCheck,
  FileQuestion,
  FileText,
  Loader2,
  ShieldCheck,
  Sparkles,
  XCircle,
} from "lucide-react";
import { useParams } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
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
import { apiErrorMessage } from "@/lib/api/config";
import {
  generateRecommendation,
  listRecommendations,
} from "@/lib/api/endpoints";
import type {
  ForumStep,
  LimitationFlag,
  LitigationStrategyPayload,
  Recommendation,
  RecommendedDraft,
  StrategyRisk,
  StrategyRoute,
} from "@/lib/api/schemas";
import { cn } from "@/lib/cn";

const FORUM_LEVEL_LABEL: Record<string, string> = {
  lower_court: "Trial / Lower Court",
  tribunal: "Tribunal",
  high_court_single_bench: "HC Single Bench",
  high_court_division_bench: "HC Division Bench",
  supreme_court: "Supreme Court",
  supreme_court_review: "SC Review",
  supreme_court_curative: "SC Curative",
  arbitration: "Arbitration",
  executive: "Executive / Authority",
  other: "Other",
};

const SEVERITY_TONE: Record<string, string> = {
  info: "border-slate-200 bg-slate-50 text-slate-800",
  warning: "border-amber-200 bg-amber-50 text-amber-900",
  critical: "border-red-300 bg-red-50 text-red-900",
};

const RISK_TONE: Record<string, string> = {
  low: "border-slate-200 bg-slate-50 text-slate-800",
  medium: "border-amber-200 bg-amber-50 text-amber-900",
  high: "border-red-300 bg-red-50 text-red-900",
};

function formatDateTime(value: string): string {
  try {
    return new Date(value).toLocaleString(undefined, {
      day: "2-digit",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return value;
  }
}

export default function MatterStrategyPage() {
  const params = useParams<{ id: string }>();
  const matterId = params.id;
  const queryClient = useQueryClient();
  const [lastError, setLastError] = useState<string | null>(null);

  const query = useQuery({
    queryKey: ["matters", matterId, "recommendations"],
    queryFn: () => listRecommendations(matterId),
    enabled: Boolean(matterId),
  });

  const generateMutation = useMutation({
    mutationFn: () =>
      generateRecommendation({ matterId, type: "litigation_strategy" }),
    onMutate: () => {
      setLastError(null);
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["matters", matterId, "recommendations"],
      });
      setLastError(null);
      toast.success("Strategy ready for review");
    },
    onError: (err) => {
      // Backend's 422 detail is actionable — surface it verbatim. The
      // PRD-mandated refusal copy ("No grounding authorities were
      // verified...") lands here when retrieval / verification fails
      // closed.
      const message = apiErrorMessage(
        err,
        "Could not generate the strategy.",
      );
      setLastError(message);
      toast.error(message);
    },
  });

  if (query.isPending) {
    return <Skeleton className="h-64 w-full" data-testid="strategy-loading" />;
  }
  if (query.isError) {
    return (
      <QueryErrorState
        title="Could not load strategies"
        error={query.error}
        onRetry={() => query.refetch()}
      />
    );
  }

  const strategies = (query.data?.recommendations ?? []).filter(
    (r) => r.type === "litigation_strategy",
  );
  // The latest strategy is the head of the list (created_at desc on
  // the backend). The page surfaces the latest only — historical
  // strategies live on the Recommendations tab.
  const latest = strategies[0] ?? null;

  return (
    <div className="flex flex-col gap-5">
      {lastError ? (
        <Card
          className="border-amber-300 bg-amber-50"
          data-testid="strategy-last-error"
        >
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base text-amber-900">
              <XCircle className="h-4 w-4" aria-hidden />
              Strategy generation needs more grounding
            </CardTitle>
            <CardDescription className="text-amber-800">
              {lastError}
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              data-testid="strategy-retry-from-banner"
              onClick={() => generateMutation.mutate()}
              disabled={generateMutation.isPending}
            >
              Try again
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setLastError(null)}
            >
              Dismiss
            </Button>
          </CardContent>
        </Card>
      ) : null}

      <Card>
        <CardHeader className="flex-row items-start justify-between gap-4">
          <div>
            <CardTitle>Litigation strategy</CardTitle>
            <CardDescription>
              Citation-grounded strategy and escalation plan up to Supreme
              Court level where legally available. Every strategy carries
              <em className="ml-1">review_required</em> until a partner
              signs off.
            </CardDescription>
          </div>
          <Button
            data-testid="strategy-generate"
            onClick={() => generateMutation.mutate()}
            disabled={generateMutation.isPending}
          >
            {generateMutation.isPending ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                Generating…
              </>
            ) : (
              <>
                <Sparkles className="h-4 w-4" aria-hidden />
                {latest ? "Re-generate" : "Generate strategy"}
              </>
            )}
          </Button>
        </CardHeader>
        <CardContent className="py-5 text-sm text-[var(--color-mute)]">
          {!latest ? (
            <EmptyState
              icon={ClipboardCheck}
              title="No strategy yet"
              description="Generate a citation-grounded litigation strategy. CaseOps will surface the route plan, escalation ladder, and recommended drafts."
            />
          ) : (
            <div className="flex items-center gap-2 text-xs">
              <ShieldCheck
                className="h-4 w-4 text-[var(--color-brand-600)]"
                aria-hidden
              />
              Strategy filtered through CaseOps' citation verifier and the
              outcome-promise scrub.
            </div>
          )}
        </CardContent>
      </Card>

      {latest ? (
        <StrategyCard rec={latest} matterId={matterId} />
      ) : null}
    </div>
  );
}

function StrategyCard({
  rec,
  matterId,
}: {
  rec: Recommendation;
  matterId: string;
}) {
  const payload = rec.strategy_payload;
  if (!payload) {
    // Defensive: ought never to happen because the backend pins
    // strategy_payload on every type='litigation_strategy' row. If
    // it does, surface it as a degraded state rather than crashing
    // the page.
    return (
      <Card className="border-amber-300 bg-amber-50">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base text-amber-900">
            <AlertTriangle className="h-4 w-4" aria-hidden />
            Strategy payload missing
          </CardTitle>
          <CardDescription className="text-amber-800">
            This strategy row has no payload attached. Re-generate to recover.
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }

  return (
    <Card data-testid="strategy-card">
      <CardHeader className="flex-row items-start justify-between gap-4">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="brand">Strategy</Badge>
            {rec.review_required ? (
              <span
                className="inline-flex items-center gap-1 rounded-full border border-amber-200 bg-amber-50 px-2.5 py-0.5 text-xs font-medium text-amber-800"
                data-testid="strategy-review-required"
              >
                <FileQuestion className="h-3.5 w-3.5" aria-hidden />
                Partner review required
              </span>
            ) : null}
          </div>
          <CardTitle className="mt-3 text-lg">{rec.title}</CardTitle>
          <CardDescription>
            Generated {formatDateTime(rec.created_at)}
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-6 py-5">
        <Section title="Current posture">
          <p
            className="text-prose-wide whitespace-pre-line text-sm leading-relaxed text-[var(--color-ink-2)]"
            data-testid="strategy-current-posture"
          >
            {payload.current_posture}
          </p>
        </Section>

        <Section title="Recommended route">
          <RouteCard route={payload.recommended_route} primary />
        </Section>

        {payload.alternative_routes.length > 0 ? (
          <Section title="Alternative routes">
            <div className="flex flex-col gap-3">
              {payload.alternative_routes.map((route, idx) => (
                <RouteCard
                  key={`${route.label}-${idx}`}
                  route={route}
                  primary={false}
                />
              ))}
            </div>
          </Section>
        ) : null}

        <Section
          title="Forum sequence"
          subtitle="Escalation ladder up to Supreme Court level where legally available."
        >
          <ForumSequenceTimeline steps={payload.forum_sequence} />
        </Section>

        {payload.recommended_drafts.length > 0 ? (
          <Section title="Recommended drafts">
            <DraftPackList
              drafts={payload.recommended_drafts}
              matterId={matterId}
            />
          </Section>
        ) : null}

        {payload.limitation_flags.length > 0 ? (
          <Section title="Limitation flags">
            <ul
              className="flex flex-col gap-2"
              data-testid="strategy-limitation-flags"
            >
              {payload.limitation_flags.map((flag, idx) => (
                <LimitationFlagRow flag={flag} key={`${flag.label}-${idx}`} />
              ))}
            </ul>
          </Section>
        ) : null}

        {payload.required_documents.length > 0 ? (
          <Section title="Required documents">
            <ul
              className="grid grid-cols-1 gap-1.5 text-sm sm:grid-cols-2"
              data-testid="strategy-required-documents"
            >
              {payload.required_documents.map((doc) => (
                <li key={doc} className="flex items-start gap-2">
                  <CheckCircle2
                    className="mt-0.5 h-4 w-4 shrink-0 text-[var(--color-brand-600)]"
                    aria-hidden
                  />
                  <span>{doc}</span>
                </li>
              ))}
            </ul>
          </Section>
        ) : null}

        {payload.missing_facts.length > 0 ? (
          <Section title="Missing facts">
            <ul
              className="flex flex-col gap-1.5 text-sm"
              data-testid="strategy-missing-facts"
            >
              {payload.missing_facts.map((fact) => (
                <li key={fact} className="flex items-start gap-2">
                  <AlertTriangle
                    className="mt-0.5 h-4 w-4 shrink-0 text-amber-600"
                    aria-hidden
                  />
                  <span>{fact}</span>
                </li>
              ))}
            </ul>
          </Section>
        ) : null}

        {payload.risks.length > 0 ? (
          <Section title="Risks">
            <ul className="flex flex-col gap-2" data-testid="strategy-risks">
              {payload.risks.map((risk, idx) => (
                <RiskRow key={`${risk.label}-${idx}`} risk={risk} />
              ))}
            </ul>
          </Section>
        ) : null}

        {rec.retrieved_authorities && rec.retrieved_authorities.length > 0 ? (
          <Section title="Authorities considered">
            <ul
              className="flex flex-col gap-1 text-xs text-[var(--color-mute)]"
              data-testid="strategy-authorities"
            >
              {rec.retrieved_authorities.map((cite) => (
                <li key={cite} className="flex items-start gap-2">
                  <BadgeCheck
                    className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[var(--color-brand-600)]"
                    aria-hidden
                  />
                  <span>{cite}</span>
                </li>
              ))}
            </ul>
          </Section>
        ) : null}

        {payload.next_best_actions.length > 0 ? (
          <Section title="Next best actions">
            <ol
              className="flex list-decimal flex-col gap-1.5 pl-5 text-sm"
              data-testid="strategy-next-best-actions"
            >
              {payload.next_best_actions.map((action) => (
                <li key={action}>{action}</li>
              ))}
            </ol>
          </Section>
        ) : null}

        <p
          className="rounded-md border border-[var(--color-line)] bg-[var(--color-bg)] px-3 py-2 text-xs text-[var(--color-mute)]"
          data-testid="strategy-disclaimer"
        >
          {payload.disclaimer}
        </p>
      </CardContent>
    </Card>
  );
}

function Section({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="flex flex-col gap-2">
      <div>
        <h3 className="text-sm font-semibold text-[var(--color-ink)]">
          {title}
        </h3>
        {subtitle ? (
          <p className="text-xs text-[var(--color-mute)]">{subtitle}</p>
        ) : null}
      </div>
      {children}
    </section>
  );
}

function RouteCard({
  route,
  primary,
}: {
  route: StrategyRoute;
  primary: boolean;
}) {
  return (
    <div
      className={cn(
        "rounded-xl border bg-white p-4",
        primary
          ? "border-[var(--color-ink-2)] shadow-[var(--shadow-soft)]"
          : "border-[var(--color-line)]",
      )}
      data-testid={primary ? "strategy-recommended-route" : "strategy-alternative-route"}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <h4 className="text-sm font-semibold text-[var(--color-ink)]">
          {route.label}
        </h4>
        <div className="flex items-center gap-1.5">
          {primary ? <Badge tone="brand">Primary</Badge> : null}
          <Badge tone="neutral">{route.confidence}</Badge>
          <Badge tone={route.availability === "available" ? "brand" : "warning"}>
            {route.availability.replace("_", " ")}
          </Badge>
        </div>
      </div>
      <p className="mt-2 whitespace-pre-line text-sm leading-relaxed text-[var(--color-ink-2)]">
        {route.rationale}
      </p>
      {route.supporting_citations.length > 0 ? (
        <ul className="mt-3 flex flex-wrap gap-2">
          {route.supporting_citations.map((citation) => (
            <li
              key={citation}
              className="inline-flex items-center gap-1.5 rounded-full border border-[var(--color-brand-100)] bg-[var(--color-brand-50)] px-2.5 py-0.5 text-xs font-medium text-[var(--color-brand-700)]"
            >
              <CheckCircle2 className="h-3 w-3" aria-hidden /> {citation}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-3 text-xs italic text-[var(--color-mute-2)]">
          No citations survived verification for this route.
        </p>
      )}
      {route.risk_notes ? (
        <p className="mt-3 rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-900">
          {route.risk_notes}
        </p>
      ) : null}
    </div>
  );
}

function ForumSequenceTimeline({ steps }: { steps: ForumStep[] }) {
  return (
    <ol
      className="flex flex-col gap-3"
      data-testid="strategy-forum-sequence"
    >
      {steps.map((step, idx) => (
        <li
          key={`${step.forum_level}-${idx}`}
          className="flex gap-3 rounded-lg border border-[var(--color-line)] bg-white p-3"
        >
          <div className="flex flex-col items-center pt-0.5">
            <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-[var(--color-bg-2)] text-[11px] font-semibold text-[var(--color-ink-2)]">
              {idx + 1}
            </span>
            {idx < steps.length - 1 ? (
              <span className="mt-1 h-full w-px bg-[var(--color-line)]" />
            ) : null}
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-baseline gap-2">
              <h4 className="text-sm font-semibold text-[var(--color-ink)]">
                {step.stage_label}
              </h4>
              <Badge tone="neutral">
                {FORUM_LEVEL_LABEL[step.forum_level] ?? step.forum_level}
              </Badge>
              {step.forum_name ? (
                <span className="text-xs text-[var(--color-mute)]">
                  {step.forum_name}
                </span>
              ) : null}
            </div>
            <p className="mt-1 text-sm text-[var(--color-ink-2)]">
              {step.rationale}
            </p>
            {step.statutory_basis.length > 0 ? (
              <p className="mt-1 text-xs text-[var(--color-mute)]">
                <span className="font-semibold">Basis:</span>{" "}
                {step.statutory_basis.join(", ")}
              </p>
            ) : null}
            {step.expected_filings.length > 0 ? (
              <p className="mt-1 text-xs text-[var(--color-mute)]">
                <span className="font-semibold">Filings:</span>{" "}
                {step.expected_filings.join(", ")}
              </p>
            ) : null}
          </div>
        </li>
      ))}
    </ol>
  );
}

function DraftPackList({
  drafts,
  matterId,
}: {
  drafts: RecommendedDraft[];
  matterId: string;
}) {
  return (
    <ul
      className="grid grid-cols-1 gap-2 sm:grid-cols-2"
      data-testid="strategy-recommended-drafts"
    >
      {drafts.map((draft) => (
        <li
          key={draft.template_type}
          className={cn(
            "flex flex-col gap-1.5 rounded-lg border bg-white p-3",
            draft.available
              ? "border-[var(--color-line)]"
              : "border-[var(--color-line)] opacity-70",
          )}
          data-testid={`strategy-draft-${draft.template_type}`}
        >
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <h4 className="text-sm font-semibold text-[var(--color-ink)]">
                {draft.display_name}
              </h4>
              <p className="text-xs text-[var(--color-mute)]">
                {draft.purpose}
              </p>
            </div>
            <FileText
              className="h-4 w-4 shrink-0 text-[var(--color-brand-600)]"
              aria-hidden
            />
          </div>
          {draft.available ? (
            <Button
              size="sm"
              variant="outline"
              href={`/app/matters/${matterId}/drafts/new?type=${encodeURIComponent(draft.template_type)}`}
              data-testid={`strategy-draft-button-${draft.template_type}`}
            >
              Generate this draft
              <ChevronRight className="h-4 w-4" aria-hidden />
            </Button>
          ) : (
            <p
              className="rounded-md bg-amber-50 px-2 py-1 text-xs text-amber-900"
              data-testid={`strategy-draft-unavailable-${draft.template_type}`}
            >
              {draft.reason_unavailable ?? "Not available at this stage."}
            </p>
          )}
        </li>
      ))}
    </ul>
  );
}

function LimitationFlagRow({ flag }: { flag: LimitationFlag }) {
  return (
    <li
      className={cn(
        "rounded-md border px-3 py-2 text-sm",
        SEVERITY_TONE[flag.severity] ?? SEVERITY_TONE.info,
      )}
    >
      <div className="flex flex-wrap items-baseline gap-2">
        <span className="font-semibold">{flag.label}</span>
        <Badge tone={flag.severity === "critical" ? "warning" : "neutral"}>
          {flag.severity}
        </Badge>
        {flag.deadline_iso ? (
          <span className="text-xs">Deadline: {flag.deadline_iso}</span>
        ) : null}
      </div>
      <p className="mt-1 text-sm leading-relaxed">{flag.description}</p>
      {flag.statutory_basis ? (
        <p className="mt-1 text-xs">
          <span className="font-semibold">Basis:</span> {flag.statutory_basis}
        </p>
      ) : null}
    </li>
  );
}

function RiskRow({ risk }: { risk: StrategyRisk }) {
  return (
    <li
      className={cn(
        "rounded-md border px-3 py-2 text-sm",
        RISK_TONE[risk.severity] ?? RISK_TONE.medium,
      )}
    >
      <div className="flex flex-wrap items-baseline gap-2">
        <span className="font-semibold">{risk.label}</span>
        <Badge tone={risk.severity === "high" ? "warning" : "neutral"}>
          {risk.severity}
        </Badge>
      </div>
      <p className="mt-1 text-sm leading-relaxed">{risk.description}</p>
      {risk.mitigation ? (
        <p className="mt-1 text-xs">
          <span className="font-semibold">Mitigation:</span> {risk.mitigation}
        </p>
      ) : null}
    </li>
  );
}
