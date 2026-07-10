"use client";

import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  BarChart3,
  BookOpen,
  CheckCircle2,
  FileText,
  Loader2,
  LockKeyhole,
  Scale,
  ShieldCheck,
} from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import type { ReactNode } from "react";

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
import { isApiErrorShape } from "@/lib/api/config";
import { fetchPredictiveIntelligence } from "@/lib/api/endpoints";
import type {
  BenchContextSummary,
  CalibratedPredictiveSignal,
  HearingPrepScorecard,
  MatterRiskSummary,
  PredictionFeatureContribution,
  PredictiveEvidence,
  PredictiveIntelligenceResponse,
  PredictiveSignal,
} from "@/lib/api/schemas";
import { cn } from "@/lib/cn";
import { formatLegalDate } from "@/lib/dates";

const STATUS_LABEL: Record<string, string> = {
  supported: "Supported",
  limited_context: "Limited context",
  insufficient_evidence: "Insufficient evidence",
  unavailable: "Unavailable",
};

const SIGNAL_TYPE_LABELS: Record<string, string> = {
  bench_outcome_tendency: "Bench/forum outcome tendency",
  interim_relief_likelihood: "Interim relief likelihood",
  stay_likelihood: "Stay likelihood",
  notice_issuance_likelihood: "Notice issuance likelihood",
  adjournment_likelihood: "Adjournment likelihood",
  disposal_delay_risk: "Disposal/delay risk",
  adverse_order_risk: "Adverse order risk",
  settlement_inclination_signal: "Settlement inclination signal",
  bench_party_side_tendency: "Bench/party-side tendency",
  forum_practice_pattern: "Forum practice pattern",
};

export default function PredictiveIntelligencePage() {
  const params = useParams<{ id: string }>();
  const matterId = params.id;
  const query = useQuery({
    queryKey: ["matters", matterId, "predictive-intelligence"],
    queryFn: () => fetchPredictiveIntelligence(matterId),
    enabled: Boolean(matterId),
  });
  const refetchPredictiveIntelligence = query.refetch;

  if (query.isPending) return <PredictiveLoadingState />;

  if (query.isError) {
    if (isApiErrorShape(query.error) && query.error.status === 403) {
      return <PolicyDisabledState message={query.error.detail} />;
    }
    return (
      <QueryErrorState
        title="Could not load predictive intelligence"
        error={query.error}
        onRetry={() => refetchPredictiveIntelligence()}
      />
    );
  }

  if (!query.data) {
    return (
      <QueryErrorState
        title="Predictive intelligence unavailable"
        error={new Error("No response was returned for this matter.")}
        onRetry={() => refetchPredictiveIntelligence()}
      />
    );
  }

  return <PredictiveIntelligenceView data={query.data} matterId={matterId} />;
}

function PredictiveIntelligenceView({
  data,
  matterId,
}: {
  data: PredictiveIntelligenceResponse;
  matterId: string;
}) {
  const signals = data.bench_summary.signals;
  const supportedCount = signals.filter((signal) => signal.status === "supported").length;
  const insufficientCount = signals.length - supportedCount;
  const overallStatus =
    supportedCount > 0
      ? `${supportedCount} source-backed signal${supportedCount === 1 ? "" : "s"}`
      : "insufficient evidence";

  return (
    <div className="flex flex-col gap-5" data-testid="predictive-page">
      <Card>
        <CardHeader className="gap-4">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone="brand">Predictive Intelligence</Badge>
                <StatusPill status={supportedCount > 0 ? "supported" : "insufficient_evidence"} />
                <Badge tone="neutral">
                  <ShieldCheck className="h-3.5 w-3.5" aria-hidden />
                  Policy enabled
                </Badge>
              </div>
              <CardTitle as="h1" className="mt-3 text-xl">
                Source-backed litigation signals
              </CardTitle>
              <CardDescription className="mt-1 max-w-3xl">
                Based on indexed sources, confidence bands, and linked
                judgment or order evidence. Human review remains required.
              </CardDescription>
            </div>
            <div className="grid min-w-full grid-cols-2 gap-2 text-sm sm:min-w-[28rem] sm:grid-cols-4">
              <SummaryMetric
                label="Evidence quality"
                value={titleCase(data.bench_summary.evidence_quality)}
              />
              <SummaryMetric label="Signal status" value={overallStatus} />
              <SummaryMetric label="Generated" value={formatDateTime(data.generated_at)} />
              <SummaryMetric
                label="Bench scope"
                value={
                  data.bench_summary.bench_judge_ids.length > 0
                    ? `${data.bench_summary.bench_judge_ids.length} bench ID`
                    : "Forum aggregate"
                }
              />
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          <p
            className="rounded-md border border-[var(--color-line)] bg-[var(--color-bg)] px-3 py-2 text-xs leading-relaxed text-[var(--color-mute)]"
            data-testid="predictive-disclaimer"
          >
            {data.disclaimer}
          </p>
          {supportedCount === 0 ? (
            <div
              className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900"
              data-testid="predictive-insufficient-banner"
            >
              No predictive signal crossed the source threshold. Add indexed
              judgments, orders, or aggregate backfill data before relying on
              this surface.
            </div>
          ) : (
            <div className="text-xs text-[var(--color-mute)]">
              {insufficientCount} signal{insufficientCount === 1 ? "" : "s"} still
              need more source evidence.
            </div>
          )}
        </CardContent>
      </Card>

      <BenchContextPanel context={data.bench_context} matterId={matterId} />
      <CalibratedSignalsPanel signals={data.calibrated_signals} matterId={matterId} />

      <section className="grid gap-4 xl:grid-cols-[minmax(0,1.6fr)_minmax(22rem,0.9fr)]">
        <div className="flex flex-col gap-4">
          {signals.map((signal) => (
            <SignalPanel key={signal.signal_type} signal={signal} matterId={matterId} />
          ))}
        </div>
        <div className="flex flex-col gap-4">
          <MatterRiskPanel summary={data.matter_risk_summary} matterId={matterId} />
          <HearingPrepPanel scorecard={data.hearing_prep_scorecard} />
        </div>
      </section>
    </div>
  );
}

function CalibratedSignalsPanel({
  signals,
  matterId,
}: {
  signals: CalibratedPredictiveSignal[];
  matterId: string;
}) {
  const supported = signals.filter((signal) => signal.status === "supported");
  return (
    <Card data-testid="predictive-calibrated-signals">
      <CardHeader className="gap-3">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone="neutral">Calibrated signals</Badge>
              <StatusPill status={supported.length > 0 ? "supported" : "insufficient_evidence"} />
            </div>
            <CardTitle className="mt-2 text-base">
              Observed historical patterns
            </CardTitle>
            <CardDescription className="mt-1 max-w-3xl">
              Stored outcome classifications are shown as source-backed
              distributions with confidence bands, snapshot scope, and cited
              evidence.
            </CardDescription>
          </div>
          <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-3">
            <CompactMetric label="Supported" value={String(supported.length)} />
            <CompactMetric label="Total signals" value={String(signals.length)} />
            <CompactMetric label="Review gate" value="Human review" />
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {signals.length === 0 ? (
          <EmptyState
            icon={BarChart3}
            title="No calibrated signal set"
            description="Run source-backed outcome classification and aggregate refresh before calibrated signals can be displayed."
          />
        ) : (
          <div className="overflow-hidden rounded-md border border-[var(--color-line)]">
            <table className="w-full text-left text-xs">
              <thead className="bg-[var(--color-bg)] text-[var(--color-mute)]">
                <tr>
                  <th className="px-3 py-2 font-semibold">Signal</th>
                  <th className="px-3 py-2 font-semibold">Status</th>
                  <th className="px-3 py-2 font-semibold">Sample</th>
                  <th className="px-3 py-2 font-semibold">Observed rate</th>
                  <th className="px-3 py-2 font-semibold">Band</th>
                  <th className="px-3 py-2 font-semibold">Scope</th>
                  <th className="px-3 py-2 font-semibold">Sources</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--color-line)] bg-white">
                {signals.map((signal) => (
                  <CalibratedSignalRow
                    key={`${signal.signal_type}-${signal.aggregate_snapshot_id ?? "missing"}`}
                    signal={signal}
                    matterId={matterId}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function CalibratedSignalRow({
  signal,
  matterId,
}: {
  signal: CalibratedPredictiveSignal;
  matterId: string;
}) {
  return (
    <tr data-testid={`predictive-calibrated-signal-${signal.signal_type}`}>
      <td className="px-3 py-2 align-top">
        <div className="font-semibold text-[var(--color-ink)]">{signal.label}</div>
        <div className="mt-1 text-[var(--color-mute)]">
          {signal.aggregate_snapshot_id
            ? `Snapshot ${signal.aggregate_snapshot_id}`
            : "No aggregate snapshot"}
        </div>
        {signal.missing_data.length > 0 ? (
          <ul className="mt-2 space-y-1 text-amber-900">
            {signal.missing_data.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        ) : null}
        <p className="mt-2 max-w-xl leading-relaxed text-[var(--color-mute)]">
          {signal.limitation_note}
        </p>
      </td>
      <td className="px-3 py-2 align-top">
        <StatusPill status={signal.status} />
      </td>
      <td className="px-3 py-2 align-top tabular-nums text-[var(--color-ink-2)]">
        {signal.sample_size}
      </td>
      <td className="px-3 py-2 align-top tabular-nums text-[var(--color-ink-2)]">
        {formatRate(signal.observed_rate)}
        <div className="mt-1 text-[var(--color-mute)]">
          {signal.positive_count}/{signal.negative_count}/{signal.neutral_count}
        </div>
      </td>
      <td className="px-3 py-2 align-top text-[var(--color-ink-2)]">
        {confidenceBand(signal)}
        <div className="mt-1 text-[var(--color-mute)]">
          {titleCase(signal.calibration_level)} · {titleCase(signal.evidence_quality)}
        </div>
      </td>
      <td className="px-3 py-2 align-top text-[var(--color-ink-2)]">
        {calibratedScopeLabel(signal)}
        <div className="mt-1 text-[var(--color-mute)]">
          {yearWindow(signal.scope.year_start, signal.scope.year_end)}
        </div>
      </td>
      <td className="px-3 py-2 align-top">
        {signal.evidence.length > 0 ? (
          <div className="flex flex-col gap-1">
            {signal.evidence.slice(0, 3).map((item) => {
              const href = sourceHref(item, matterId);
              const label = item.source_reference || item.title || item.source_id;
              return href ? (
                <Link
                  key={item.id}
                  href={href}
                  className="text-xs font-medium text-[var(--color-accent)] hover:underline"
                >
                  {label}
                </Link>
              ) : (
                <span key={item.id} className="text-xs text-[var(--color-mute)]">
                  {label}
                </span>
              );
            })}
          </div>
        ) : (
          <span className="text-xs text-[var(--color-mute)]">No source links</span>
        )}
      </td>
    </tr>
  );
}

function BenchContextPanel({
  context,
  matterId,
}: {
  context: BenchContextSummary;
  matterId: string;
}) {
  const scope = context.scope;
  return (
    <Card data-testid="predictive-bench-context">
      <CardHeader className="gap-3">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <StatusPill status={context.status} />
              <Badge tone="neutral">Bench context</Badge>
            </div>
            <CardTitle className="mt-2 text-base">Bench and judge context</CardTitle>
            <CardDescription className="mt-1 max-w-3xl">
              Indexed judgments and orders for the resolved bench, shown with
              sample size, source distribution, and limitation notes.
            </CardDescription>
          </div>
          <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
            <CompactMetric label="Sample size" value={String(context.sample_size)} />
            <CompactMetric label="Evidence quality" value={titleCase(context.evidence_quality)} />
            <CompactMetric label="Confidence band" value={confidenceBand(context)} />
            <CompactMetric label="Year window" value={yearWindow(scope.year_start, scope.year_end)} />
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-2 text-xs md:grid-cols-4">
          <CompactMetric label="Court/forum" value={scope.court_name ?? scope.forum_level ?? "Not set"} />
          <CompactMetric label="Bench" value={scope.bench_name ?? "Not resolved"} />
          <CompactMetric
            label="Judge IDs"
            value={scope.judge_ids.length ? String(scope.judge_ids.length) : "None"}
          />
          <CompactMetric label="Matter type" value={scope.matter_type ?? "Not set"} />
        </div>

        {scope.judge_names.length > 0 ? (
          <div className="space-y-2">
            <SectionLabel>Resolved judges</SectionLabel>
            <div className="flex flex-wrap gap-2">
              {scope.judge_names.map((name) => (
                <span
                  key={name}
                  className="rounded-full border border-[var(--color-line)] bg-white px-2.5 py-1 text-xs font-medium text-[var(--color-ink-2)]"
                >
                  {name}
                </span>
              ))}
            </div>
          </div>
        ) : null}

        {context.observed_distribution.length > 0 ? (
          <div className="space-y-2">
            <SectionLabel>Observed signal distribution</SectionLabel>
            <div className="overflow-hidden rounded-md border border-[var(--color-line)]">
              <table className="w-full text-left text-xs">
                <thead className="bg-[var(--color-bg)] text-[var(--color-mute)]">
                  <tr>
                    <th className="px-3 py-2 font-semibold">Signal</th>
                    <th className="px-3 py-2 font-semibold">Sample</th>
                    <th className="px-3 py-2 font-semibold">Positive</th>
                    <th className="px-3 py-2 font-semibold">Adverse</th>
                    <th className="px-3 py-2 font-semibold">Neutral</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--color-line)] bg-white">
                  {context.observed_distribution.map((item) => (
                    <tr key={`${item.signal_type}-${item.sample_size}`}>
                      <td className="px-3 py-2 font-medium text-[var(--color-ink)]">
                        {item.label}
                      </td>
                      <td className="px-3 py-2 tabular-nums text-[var(--color-ink-2)]">
                        {item.sample_size}
                      </td>
                      <td className="px-3 py-2 tabular-nums text-[var(--color-ink-2)]">
                        {item.positive_count}
                      </td>
                      <td className="px-3 py-2 tabular-nums text-[var(--color-ink-2)]">
                        {item.negative_count}
                      </td>
                      <td className="px-3 py-2 tabular-nums text-[var(--color-ink-2)]">
                        {item.neutral_count}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ) : null}

        {context.missing_data.length > 0 ? (
          <MissingDataList items={context.missing_data} />
        ) : null}

        <p className="rounded-md bg-[var(--color-bg)] px-3 py-2 text-xs leading-relaxed text-[var(--color-mute)]">
          {context.limitation_note}
        </p>
        <p className="text-xs leading-relaxed text-[var(--color-mute)]">
          {context.disclaimer}
        </p>

        <EvidenceList evidence={context.evidence} matterId={matterId} />
      </CardContent>
    </Card>
  );
}

function SignalPanel({
  signal,
  matterId,
}: {
  signal: PredictiveSignal;
  matterId: string;
}) {
  const features = signal.features.filter((feature) => feature.explanation);
  return (
    <Card data-testid={`predictive-signal-${signal.signal_type}`}>
      <CardHeader className="gap-3">
        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <StatusPill status={signal.status} />
              <span className="text-xs font-medium text-[var(--color-mute)]">
                {formatSignalType(signal.signal_type)}
              </span>
            </div>
            <CardTitle className="mt-2 text-base">
              {SIGNAL_TYPE_LABELS[signal.signal_type] ?? signal.label}
            </CardTitle>
            {signal.estimate_label ? (
              <CardDescription className="mt-1">
                Classified signal: {signal.estimate_label}
              </CardDescription>
            ) : null}
          </div>
          <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-3">
            <CompactMetric label="Confidence band" value={confidenceBand(signal)} />
            <CompactMetric label="Sample size" value={String(signal.sample_size)} />
            <CompactMetric label="Scope" value="Bench/forum aggregate" />
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {features.length > 0 ? (
          <div className="space-y-2">
            <SectionLabel>Feature explanation</SectionLabel>
            <ul className="space-y-2">
              {features.map((feature) => (
                <FeatureRow key={`${feature.feature_key}-${feature.label}`} feature={feature} />
              ))}
            </ul>
          </div>
        ) : null}

        {signal.missing_data.length > 0 ? (
          <MissingDataList items={signal.missing_data} />
        ) : null}

        <p className="rounded-md bg-[var(--color-bg)] px-3 py-2 text-xs leading-relaxed text-[var(--color-mute)]">
          {signal.limitation_note}
        </p>

        <EvidenceList evidence={signal.evidence} matterId={matterId} />
      </CardContent>
    </Card>
  );
}

function MatterRiskPanel({
  summary,
  matterId,
}: {
  summary: MatterRiskSummary;
  matterId: string;
}) {
  return (
    <Card data-testid="predictive-matter-risk">
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <Scale className="h-4 w-4" aria-hidden />
            Matter risk context
          </CardTitle>
          <StatusPill status={summary.status} />
        </div>
        <CardDescription>
          Evidence-backed factors only; no standalone score is shown.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-2 gap-2 text-xs">
          <CompactMetric label="Risk band" value={summary.risk_band ?? "Not available"} />
          <CompactMetric label="Sample size" value={String(summary.confidence.sample_size)} />
          <CompactMetric label="Confidence band" value={confidenceBand(summary)} />
          <CompactMetric label="Review gate" value="Human review" />
        </div>

        {summary.features.length > 0 ? (
          <ul className="space-y-2">
            {summary.features.map((feature) => (
              <FeatureRow key={`${feature.feature_key}-${feature.label}`} feature={feature} />
            ))}
          </ul>
        ) : null}

        {summary.missing_data.length > 0 ? (
          <MissingDataList items={summary.missing_data} />
        ) : null}

        <EvidenceList evidence={summary.evidence} matterId={matterId} compact />
      </CardContent>
    </Card>
  );
}

function HearingPrepPanel({ scorecard }: { scorecard: HearingPrepScorecard }) {
  return (
    <Card data-testid="predictive-hearing-scorecard">
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <BarChart3 className="h-4 w-4" aria-hidden />
            Hearing prep scorecard
          </CardTitle>
          <StatusPill status={scorecard.status} />
        </div>
        <CardDescription>
          Observable preparation metrics only, based on transcript and source support.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {scorecard.observable_metrics.length > 0 ? (
          <ul className="space-y-2">
            {scorecard.observable_metrics.map((metric) => (
              <FeatureRow key={`${metric.feature_key}-${metric.label}`} feature={metric} />
            ))}
          </ul>
        ) : (
          <EmptyState
            icon={FileText}
            title="No hearing-prep metrics yet"
            description="Capture source-linked mock-hearing turns before this panel can score preparation consistency."
          />
        )}
        {scorecard.missing_data.length > 0 ? (
          <MissingDataList items={scorecard.missing_data} />
        ) : null}
      </CardContent>
    </Card>
  );
}

function EvidenceList({
  evidence,
  matterId,
  compact = false,
}: {
  evidence: PredictiveEvidence[];
  matterId: string;
  compact?: boolean;
}) {
  if (evidence.length === 0) {
    return (
      <div
        className="rounded-md border border-dashed border-[var(--color-line)] px-3 py-2 text-xs text-[var(--color-mute)]"
        data-testid="predictive-no-evidence"
      >
        No source links are available for this signal.
      </div>
    );
  }

  return (
    <div className="space-y-2" data-testid="predictive-evidence-list">
      <SectionLabel>Source evidence</SectionLabel>
      <ul className={cn("grid gap-2", compact ? "grid-cols-1" : "lg:grid-cols-2")}>
        {evidence.map((item) => (
          <EvidenceItem key={item.id} item={item} matterId={matterId} />
        ))}
      </ul>
    </div>
  );
}

function EvidenceItem({
  item,
  matterId,
}: {
  item: PredictiveEvidence;
  matterId: string;
}) {
  const href = sourceHref(item, matterId);
  return (
    <li className="rounded-lg border border-[var(--color-line)] bg-[var(--color-bg-2)] p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2 text-[11px] text-[var(--color-mute)]">
            <span>{sourceTypeLabel(item.source_type)}</span>
            {item.source_date ? <span>{formatDate(item.source_date)}</span> : null}
          </div>
          <h4 className="mt-1 text-sm font-semibold text-[var(--color-ink)]">
            {item.title || item.source_reference || item.source_id}
          </h4>
          {item.source_reference ? (
            <p className="mt-1 font-mono text-xs text-[var(--color-mute)]">
              {item.source_reference}
            </p>
          ) : null}
        </div>
        {href ? (
          <Link
            href={href}
            className="inline-flex shrink-0 items-center gap-1 rounded-md border border-[var(--color-line)] bg-white px-2 py-1 text-xs font-medium text-[var(--color-ink-2)] hover:text-[var(--color-ink)]"
          >
            <BookOpen className="h-3.5 w-3.5" aria-hidden />
            View source
          </Link>
        ) : (
          <span
            className="inline-flex shrink-0 rounded-md border border-[var(--color-line)] px-2 py-1 text-xs font-medium text-[var(--color-mute)]"
            data-testid="predictive-source-unavailable"
          >
            Source unavailable
          </span>
        )}
      </div>
      {item.excerpt ? (
        <p className="mt-2 line-clamp-3 text-xs leading-relaxed text-[var(--color-mute)]">
          {item.excerpt}
        </p>
      ) : null}
    </li>
  );
}

function FeatureRow({ feature }: { feature: PredictionFeatureContribution }) {
  return (
    <li className="rounded-md border border-[var(--color-line)] bg-white px-3 py-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-semibold text-[var(--color-ink)]">
          {feature.label}
        </span>
        <span className="rounded-full bg-[var(--color-bg)] px-2 py-0.5 text-[11px] font-medium capitalize text-[var(--color-mute)]">
          {feature.direction}
        </span>
      </div>
      <p className="mt-1 text-xs leading-relaxed text-[var(--color-mute)]">
        {feature.explanation}
      </p>
    </li>
  );
}

function MissingDataList({ items }: { items: string[] }) {
  return (
    <div
      className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2"
      data-testid="predictive-missing-data"
    >
      <SectionLabel className="text-amber-900">Missing data</SectionLabel>
      <ul className="mt-2 space-y-1 text-xs leading-relaxed text-amber-900">
        {items.map((item) => (
          <li key={item} className="flex gap-2">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function PolicyDisabledState({ message }: { message: string }) {
  return (
    <Card data-testid="predictive-policy-disabled">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <LockKeyhole className="h-4 w-4" aria-hidden />
          Predictive intelligence is disabled
        </CardTitle>
        <CardDescription>{message}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 text-sm text-[var(--color-mute)]">
        <p>
          This workspace requires an administrator to enable controlled
          predictive intelligence before source-backed signals can be viewed.
        </p>
        <div>
          <Button href="/app/admin" variant="outline" size="sm">
            Open admin settings
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function PredictiveLoadingState() {
  return (
    <div className="flex flex-col gap-4" data-testid="predictive-loading">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            Loading predictive intelligence
          </CardTitle>
          <CardDescription>
            Reading source-backed signals and evidence links.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-2 sm:grid-cols-4">
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
        </CardContent>
      </Card>
      <Skeleton className="h-48 w-full" />
      <Skeleton className="h-48 w-full" />
    </div>
  );
}

function SummaryMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-[var(--color-line)] bg-white px-3 py-2">
      <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-[var(--color-mute)]">
        {label}
      </div>
      <div className="mt-1 min-h-8 text-sm font-semibold text-[var(--color-ink)]">
        {value}
      </div>
    </div>
  );
}

function CompactMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md bg-[var(--color-bg)] px-2.5 py-2">
      <div className="text-[10px] font-medium uppercase tracking-[0.12em] text-[var(--color-mute)]">
        {label}
      </div>
      <div className="mt-1 font-semibold text-[var(--color-ink)]">{value}</div>
    </div>
  );
}

function StatusPill({ status }: { status: string }) {
  const supported = status === "supported";
  const limited = status === "limited_context";
  const className = supported
    ? "border-emerald-200 bg-emerald-50 text-emerald-800"
    : limited
      ? "border-sky-200 bg-sky-50 text-sky-900"
      : "border-amber-200 bg-amber-50 text-amber-900";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium",
        className,
      )}
    >
      {supported ? (
        <CheckCircle2 className="h-3.5 w-3.5" aria-hidden />
      ) : (
        <AlertTriangle className="h-3.5 w-3.5" aria-hidden />
      )}
      {STATUS_LABEL[status] ?? titleCase(status)}
    </span>
  );
}

function SectionLabel({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--color-mute-2)]",
        className,
      )}
    >
      {children}
    </div>
  );
}

function confidenceBand(
  item:
    | PredictiveSignal
    | MatterRiskSummary
    | HearingPrepScorecard
    | BenchContextSummary
    | CalibratedPredictiveSignal,
): string {
  const low = item.confidence.confidence_band_low;
  const high = item.confidence.confidence_band_high;
  if (low === null || high === null) return "No band";
  return `${Math.round(low * 100)}-${Math.round(high * 100)}%`;
}

function formatRate(value?: number | null): string {
  if (value == null) return "No rate";
  return `${Math.round(value * 100)}%`;
}

function calibratedScopeLabel(signal: CalibratedPredictiveSignal): string {
  const scope = signal.scope;
  if (scope.judge_id) return "Judge aggregate";
  if (scope.court_name || scope.forum_level) return scope.court_name ?? titleCase(scope.forum_level ?? "");
  if (scope.matter_type) return `Matter type: ${scope.matter_type}`;
  return titleCase(scope.scope_type ?? "aggregate");
}

function yearWindow(start?: number | null, end?: number | null): string {
  if (start && end && start !== end) return `${start}-${end}`;
  if (start) return String(start);
  if (end) return String(end);
  return "Not available";
}

function sourceHref(item: PredictiveEvidence, matterId: string): string | null {
  switch (item.source_type) {
    case "authority_document": {
      const query = item.source_reference || item.title || item.source_id;
      const params = new URLSearchParams({ q: query });
      return `/app/research?${params.toString()}`;
    }
    case "matter_court_order":
    case "matter_cause_list_entry":
      return `/app/matters/${matterId}/timeline`;
    case "matter_document":
      return `/app/matters/${matterId}/documents`;
    case "aggregate_snapshot":
    case "unavailable":
      return null;
  }
}

function sourceTypeLabel(value: PredictiveEvidence["source_type"]): string {
  const labels: Record<PredictiveEvidence["source_type"], string> = {
    authority_document: "Judgment",
    matter_court_order: "Matter order",
    matter_cause_list_entry: "Proceeding entry",
    matter_document: "Matter document",
    aggregate_snapshot: "Aggregate snapshot",
    unavailable: "Unavailable source",
  };
  return labels[value];
}

function formatSignalType(value: string): string {
  return value
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function titleCase(value: string): string {
  return value
    .split(/[_\s-]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function formatDateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatDate(value: string): string {
  return formatLegalDate(value, {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}
