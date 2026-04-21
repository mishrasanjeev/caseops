"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2,
  ClipboardCheck,
  FileQuestion,
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
import { StatusBadge } from "@/components/ui/StatusBadge";
import { ApiError } from "@/lib/api/config";
import {
  generateRecommendation,
  listRecommendations,
  recordRecommendationDecision,
} from "@/lib/api/endpoints";
import type {
  DecisionKind,
  Recommendation,
  RecommendationType,
} from "@/lib/api/schemas";
import { cn } from "@/lib/cn";

const TYPE_LABEL: Record<RecommendationType, string> = {
  forum: "Forum",
  authority: "Authority",
  remedy: "Remedy",
  next_best_action: "Next-best action",
};

const CONFIDENCE_TONE: Record<string, string> = {
  high: "bg-emerald-50 text-emerald-800 border-emerald-200",
  medium: "bg-amber-50 text-amber-800 border-amber-200",
  low: "bg-slate-100 text-slate-700 border-slate-200",
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

export default function MatterRecommendationsPage() {
  const params = useParams<{ id: string }>();
  const matterId = params.id;
  const queryClient = useQueryClient();
  const [pendingType, setPendingType] = useState<RecommendationType | null>(null);

  const query = useQuery({
    queryKey: ["matters", matterId, "recommendations"],
    queryFn: () => listRecommendations(matterId),
    enabled: Boolean(matterId),
  });

  const generateMutation = useMutation({
    mutationFn: (type: RecommendationType) =>
      generateRecommendation({ matterId, type }),
    onMutate: (type) => setPendingType(type),
    onSettled: () => setPendingType(null),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["matters", matterId, "recommendations"],
      });
      toast.success("Recommendation ready for review");
    },
    onError: (err) => {
      // BUG-012 Hari 2026-04-21: previously we hard-coded "Refused on
      // purpose" for EVERY 422 and discarded the backend's actionable
      // detail. The backend distinguishes (a) retrieval returned zero
      // authorities — widen the matter description or expand the
      // corpus — from (b) the model produced citations but none were
      // verifiable. Surface that text so the user knows which lever
      // to pull.
      toast.error(
        err instanceof ApiError
          ? err.detail
          : "Could not generate a recommendation.",
      );
    },
  });

  const decisionMutation = useMutation({
    mutationFn: (input: {
      recommendationId: string;
      decision: DecisionKind;
      selectedOptionIndex?: number | null;
    }) => recordRecommendationDecision(input),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["matters", matterId, "recommendations"],
      });
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.detail : "Could not record decision."),
  });

  const recommendations = query.data?.recommendations ?? [];

  return (
    <div className="flex flex-col gap-5">
      <Card>
        <CardHeader className="flex-row items-start justify-between gap-4">
          <div>
            <CardTitle>Recommendations</CardTitle>
            <CardDescription>
              Grounded options with verified citations. Every output carries
              <em className="ml-1">review_required</em> until a human signs off.
            </CardDescription>
          </div>
          <div className="flex flex-wrap gap-2">
            <GenerateButton
              type="authority"
              label="Authority"
              pendingType={pendingType}
              disabled={generateMutation.isPending}
              onClick={() => generateMutation.mutate("authority")}
              testId="generate-authority-recommendation"
              variant="primary"
            />
            <GenerateButton
              type="forum"
              label="Forum"
              pendingType={pendingType}
              disabled={generateMutation.isPending}
              onClick={() => generateMutation.mutate("forum")}
            />
            <GenerateButton
              type="remedy"
              label="Remedy"
              pendingType={pendingType}
              disabled={generateMutation.isPending}
              onClick={() => generateMutation.mutate("remedy")}
              testId="generate-remedy-recommendation"
            />
            <GenerateButton
              type="next_best_action"
              label="Next-best action"
              pendingType={pendingType}
              disabled={generateMutation.isPending}
              onClick={() => generateMutation.mutate("next_best_action")}
              testId="generate-nba-recommendation"
            />
          </div>
        </CardHeader>
        <CardContent className="py-5 text-sm text-[var(--color-mute)]">
          {query.isPending ? (
            "Loading recommendations…"
          ) : query.isError ? (
            <QueryErrorState
              title="Could not load recommendations"
              error={query.error}
              onRetry={query.refetch}
            />
          ) : recommendations.length === 0 ? (
            <EmptyState
              icon={ClipboardCheck}
              title="No recommendations yet"
              description="Generate a citation-grounded recommendation from the retrieved authorities. Outputs are always marked for partner review."
            />
          ) : (
            <div className="flex items-center gap-2 text-xs">
              <ShieldCheck
                className="h-4 w-4 text-[var(--color-brand-600)]"
                aria-hidden
              />
              Every option below was filtered through CaseOps' citation verifier.
            </div>
          )}
        </CardContent>
      </Card>

      {recommendations.map((rec) => (
        <RecommendationCard
          key={rec.id}
          rec={rec}
          onDecide={(decision, optionIndex) =>
            decisionMutation.mutate({
              recommendationId: rec.id,
              decision,
              selectedOptionIndex: optionIndex,
            })
          }
          isDeciding={decisionMutation.isPending}
        />
      ))}
    </div>
  );
}

function RecommendationCard({
  rec,
  onDecide,
  isDeciding,
}: {
  rec: Recommendation;
  onDecide: (decision: DecisionKind, optionIndex?: number | null) => void;
  isDeciding: boolean;
}) {
  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-4">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="brand">{TYPE_LABEL[rec.type]}</Badge>
            <StatusBadge status={rec.status} />
            <ConfidenceBadge confidence={rec.confidence} />
            {rec.review_required ? (
              <span className="inline-flex items-center gap-1 rounded-full border border-amber-200 bg-amber-50 px-2.5 py-0.5 text-xs font-medium text-amber-800">
                <FileQuestion className="h-3.5 w-3.5" aria-hidden /> Partner review
                required
              </span>
            ) : null}
          </div>
          <CardTitle className="mt-3 text-lg">{rec.title}</CardTitle>
          <CardDescription>
            Generated {formatDateTime(rec.created_at)}
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-5 py-5">
        <p className="text-prose-wide whitespace-pre-line text-sm leading-relaxed text-[var(--color-ink-2)]">
          {rec.rationale}
        </p>

        <ol className="flex flex-col gap-3">
          {rec.options.map((option, idx) => (
            <li
              key={option.id}
              className={cn(
                "rounded-xl border bg-white p-4",
                idx === rec.primary_option_index
                  ? "border-[var(--color-ink-2)] shadow-[var(--shadow-soft)]"
                  : "border-[var(--color-line)]",
              )}
            >
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-[var(--color-bg-2)] text-[11px] font-semibold text-[var(--color-ink-2)]">
                      {idx + 1}
                    </span>
                    <h3 className="text-sm font-semibold text-[var(--color-ink)]">
                      {option.label}
                    </h3>
                    {idx === rec.primary_option_index ? (
                      <Badge tone="brand">Primary</Badge>
                    ) : null}
                  </div>
                  <p className="mt-2 text-sm leading-relaxed text-[var(--color-ink-2)]">
                    {option.rationale}
                  </p>
                </div>
                <ConfidenceBadge confidence={option.confidence} />
              </div>
              {option.supporting_citations.length > 0 ? (
                <ul className="mt-3 flex flex-wrap gap-2">
                  {option.supporting_citations.map((citation) => (
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
                  No citations survived verification for this option.
                </p>
              )}
              {option.risk_notes ? (
                <p className="mt-3 rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-900">
                  {option.risk_notes}
                </p>
              ) : null}
              <div className="mt-3 flex flex-wrap gap-2">
                <Button
                  size="sm"
                  variant={
                    idx === rec.primary_option_index ? "primary" : "outline"
                  }
                  onClick={() => onDecide("accepted", idx)}
                  disabled={isDeciding || rec.status === "accepted"}
                  data-testid={`accept-option-${idx}`}
                >
                  <CheckCircle2 className="h-4 w-4" /> Accept this option
                </Button>
              </div>
            </li>
          ))}
        </ol>

        <div className="grid gap-4 md:grid-cols-2">
          {rec.assumptions.length > 0 ? (
            <Detail title="Assumptions" items={rec.assumptions} />
          ) : null}
          {rec.missing_facts.length > 0 ? (
            <Detail title="Missing facts" items={rec.missing_facts} />
          ) : null}
        </div>

        {rec.next_action ? (
          <p className="rounded-md bg-[var(--color-bg)] px-3 py-2 text-xs text-[var(--color-mute)]">
            <span className="font-semibold text-[var(--color-ink-2)]">
              Next action:
            </span>{" "}
            {rec.next_action}
          </p>
        ) : null}

        <div className="flex items-center justify-between border-t border-[var(--color-line-2)] pt-4">
          <div className="text-xs text-[var(--color-mute)]">
            {rec.decisions.length > 0
              ? `Last decision: ${rec.decisions[rec.decisions.length - 1]?.decision}`
              : "Not yet decided"}
          </div>
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant="ghost"
              onClick={() => onDecide("deferred")}
              disabled={isDeciding}
            >
              Defer
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => onDecide("rejected")}
              disabled={isDeciding}
              data-testid="reject-recommendation"
            >
              <XCircle className="h-4 w-4" /> Reject all
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function ConfidenceBadge({ confidence }: { confidence: string }) {
  const className =
    CONFIDENCE_TONE[confidence] ??
    "bg-slate-100 text-slate-700 border-slate-200";
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium capitalize",
        className,
      )}
    >
      {confidence} confidence
    </span>
  );
}

function GenerateButton({
  type,
  label,
  pendingType,
  disabled,
  onClick,
  testId,
  variant,
}: {
  type: RecommendationType;
  label: string;
  pendingType: RecommendationType | null;
  disabled: boolean;
  onClick: () => void;
  testId?: string;
  variant?: "primary" | "outline";
}) {
  const isThisPending = pendingType === type;
  return (
    <Button
      variant={variant ?? "outline"}
      onClick={onClick}
      disabled={disabled}
      data-testid={testId}
    >
      {isThisPending ? (
        <>
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Generating…
        </>
      ) : (
        <>
          <Sparkles className="h-4 w-4" aria-hidden /> {label}
        </>
      )}
    </Button>
  );
}

function Detail({ title, items }: { title: string; items: string[] }) {
  return (
    <div>
      <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--color-mute-2)]">
        {title}
      </div>
      <ul className="mt-2 flex flex-col gap-1 text-sm text-[var(--color-ink-2)]">
        {items.map((item) => (
          <li key={item} className="flex gap-2">
            <span
              aria-hidden
              className="mt-[9px] h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--color-brand-500)]"
            />
            <span className="leading-relaxed">{item}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
