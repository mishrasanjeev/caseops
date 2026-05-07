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
  Pencil,
  Plus,
  ShieldCheck,
  Sparkles,
  ThumbsUp,
  Trash2,
  Undo2,
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
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { Textarea } from "@/components/ui/Textarea";
import { apiErrorMessage, isApiErrorShape } from "@/lib/api/config";
import {
  createStrategyEntry,
  deleteStrategyEntry,
  generateRecommendation,
  listStrategyEntries,
  listRecommendations,
  recordRecommendationDecision,
  updateStrategyEntry,
} from "@/lib/api/endpoints";
import type {
  ForumStep,
  LimitationFlag,
  LitigationStrategyPayload,
  MatterStrategyEntry,
  MatterStrategyEntryStatus,
  MatterStrategyEntryType,
  Recommendation,
  RecommendedDraft,
  StrategyRisk,
  StrategyRoute,
} from "@/lib/api/schemas";
import { useCapability } from "@/lib/capabilities";
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
  const [lastError, setLastError] = useState<{
    message: string;
    problemType: string | null;
  } | null>(null);
  // Round-2 P2 #7. Strategy generation + approval ride dedicated
  // capabilities on top of the recommendations:* caps. The frontend
  // mirrors the backend gate in apps/api/src/caseops_api/api/routes/
  // recommendations.py: strategy:generate for the Generate button,
  // strategy:approve for the Approve / Request changes bar.
  const canGenerate = useCapability("strategy:generate");
  const canApprove = useCapability("strategy:approve");
  const canManageStrategy = useCapability("strategy:approve");
  const [entryForm, setEntryForm] = useState<{
    title: string;
    body: string;
    entry_type: MatterStrategyEntryType;
    status: MatterStrategyEntryStatus;
  }>({
    title: "",
    body: "",
    entry_type: "plan",
    status: "active",
  });
  const [editingEntryId, setEditingEntryId] = useState<string | null>(null);

  const query = useQuery({
    queryKey: ["matters", matterId, "recommendations"],
    queryFn: () => listRecommendations(matterId),
    enabled: Boolean(matterId),
  });

  const strategyEntriesQuery = useQuery({
    queryKey: ["matters", matterId, "strategy-entries"],
    queryFn: () => listStrategyEntries(matterId),
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
      setLastError({
        message,
        problemType: isApiErrorShape(err) ? err.problemType : null,
      });
      toast.error(message);
    },
  });

  // Round-2 P1 #3: partner-review approval mutation. ``accepted``
  // closes the review (backend clears review_required); ``edited``
  // signals "request changes" — keeps the banner visible.
  const decisionMutation = useMutation({
    mutationFn: (input: {
      recommendationId: string;
      decision: "accepted" | "edited";
    }) =>
      recordRecommendationDecision({
        recommendationId: input.recommendationId,
        decision: input.decision,
        selectedOptionIndex: 0,
      }),
    onSuccess: async (_data, variables) => {
      await queryClient.invalidateQueries({
        queryKey: ["matters", matterId, "recommendations"],
      });
      toast.success(
        variables.decision === "accepted"
          ? "Strategy approved"
          : "Strategy returned for changes",
      );
    },
    onError: (err) =>
      toast.error(apiErrorMessage(err, "Could not record the decision.")),
  });

  const resetEntryForm = () => {
    setEntryForm({
      title: "",
      body: "",
      entry_type: "plan",
      status: "active",
    });
    setEditingEntryId(null);
  };

  const saveEntryMutation = useMutation({
    mutationFn: () => {
      const payload = {
        title: entryForm.title,
        body: entryForm.body,
        entry_type: entryForm.entry_type,
        status: entryForm.status,
      };
      return editingEntryId
        ? updateStrategyEntry({
            matterId,
            entryId: editingEntryId,
            entry: payload,
          })
        : createStrategyEntry({ matterId, entry: payload });
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["matters", matterId, "strategy-entries"],
      });
      resetEntryForm();
      toast.success(editingEntryId ? "Strategy entry updated" : "Strategy entry added");
    },
    onError: (err) =>
      toast.error(apiErrorMessage(err, "Could not save strategy entry.")),
  });

  const deleteEntryMutation = useMutation({
    mutationFn: (entryId: string) => deleteStrategyEntry({ matterId, entryId }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["matters", matterId, "strategy-entries"],
      });
      toast.success("Strategy entry deleted");
    },
    onError: (err) =>
      toast.error(apiErrorMessage(err, "Could not delete strategy entry.")),
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
              {lastError.problemType === "llm_quota_exhausted"
                ? "Strategy generation is temporarily unavailable"
                : "Strategy generation needs more grounding"}
            </CardTitle>
            <CardDescription className="text-amber-800">
              {lastError.message}
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
            <CardTitle>Strategy Plan</CardTitle>
            <CardDescription>
              Lawyer-owned work product for this matter. Entries are human-authored,
              auditable, and separate from AI recommendations.
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {canManageStrategy ? (
            <div
              className="grid gap-3 rounded-md border border-[var(--color-line)] bg-[var(--color-bg)] p-3 md:grid-cols-[minmax(0,1fr)_9rem_9rem_auto]"
              data-testid="strategy-entry-form"
            >
              <div className="space-y-1.5">
                <Label htmlFor="strategy-entry-title">Title</Label>
                <Input
                  id="strategy-entry-title"
                  value={entryForm.title}
                  onChange={(event) =>
                    setEntryForm((current) => ({
                      ...current,
                      title: event.target.value,
                    }))
                  }
                  placeholder="Decision, plan, or note title"
                  data-testid="strategy-entry-title"
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="strategy-entry-type">Type</Label>
                <select
                  id="strategy-entry-type"
                  className="h-10 w-full rounded-md border border-[var(--color-line)] bg-white px-3 text-sm"
                  value={entryForm.entry_type}
                  onChange={(event) =>
                    setEntryForm((current) => ({
                      ...current,
                      entry_type: event.target.value as MatterStrategyEntryType,
                    }))
                  }
                  data-testid="strategy-entry-type"
                >
                  <option value="plan">Plan</option>
                  <option value="decision">Decision</option>
                  <option value="note">Note</option>
                </select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="strategy-entry-status">Status</Label>
                <select
                  id="strategy-entry-status"
                  className="h-10 w-full rounded-md border border-[var(--color-line)] bg-white px-3 text-sm"
                  value={entryForm.status}
                  onChange={(event) =>
                    setEntryForm((current) => ({
                      ...current,
                      status: event.target.value as MatterStrategyEntryStatus,
                    }))
                  }
                  data-testid="strategy-entry-status"
                >
                  <option value="draft">Draft</option>
                  <option value="active">Active</option>
                  <option value="archived">Archived</option>
                </select>
              </div>
              <div className="flex items-end gap-2">
                <Button
                  size="sm"
                  onClick={() => saveEntryMutation.mutate()}
                  disabled={
                    saveEntryMutation.isPending ||
                    entryForm.title.trim().length === 0 ||
                    entryForm.body.trim().length === 0
                  }
                  data-testid="strategy-entry-save"
                >
                  {saveEntryMutation.isPending ? (
                    <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                  ) : editingEntryId ? (
                    <Pencil className="h-4 w-4" aria-hidden />
                  ) : (
                    <Plus className="h-4 w-4" aria-hidden />
                  )}
                  {editingEntryId ? "Update" : "Add"}
                </Button>
                {editingEntryId ? (
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={resetEntryForm}
                    data-testid="strategy-entry-cancel"
                  >
                    Cancel
                  </Button>
                ) : null}
              </div>
              <div className="space-y-1.5 md:col-span-4">
                <Label htmlFor="strategy-entry-body">Entry</Label>
                <Textarea
                  id="strategy-entry-body"
                  value={entryForm.body}
                  onChange={(event) =>
                    setEntryForm((current) => ({
                      ...current,
                      body: event.target.value,
                    }))
                  }
                  placeholder="Record counsel-owned strategy, assumptions, decisions, or next steps."
                  data-testid="strategy-entry-body"
                />
              </div>
            </div>
          ) : null}

          {strategyEntriesQuery.isPending ? (
            <Skeleton className="h-28 w-full" data-testid="strategy-entries-loading" />
          ) : strategyEntriesQuery.isError ? (
            <QueryErrorState
              title="Could not load strategy entries"
              error={strategyEntriesQuery.error}
              onRetry={() => strategyEntriesQuery.refetch()}
            />
          ) : strategyEntriesQuery.data.entries.length === 0 ? (
            <EmptyState
              icon={ClipboardCheck}
              title="No strategy entries yet"
              description="Counsel-authored plans, decisions, and notes will appear here."
            />
          ) : (
            <div className="flex flex-col divide-y divide-[var(--color-line)]">
              {strategyEntriesQuery.data.entries.map((entry) => (
                <StrategyEntryRow
                  key={entry.id}
                  entry={entry}
                  canManage={canManageStrategy}
                  isDeleting={
                    deleteEntryMutation.isPending &&
                    deleteEntryMutation.variables === entry.id
                  }
                  onEdit={() => {
                    setEditingEntryId(entry.id);
                    setEntryForm({
                      title: entry.title,
                      body: entry.body,
                      entry_type: entry.entry_type,
                      status: entry.status,
                    });
                  }}
                  onDelete={() => deleteEntryMutation.mutate(entry.id)}
                />
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex-row items-start justify-between gap-4">
          <div>
            <CardTitle>AI strategy support</CardTitle>
            <CardDescription>
              System-generated litigation strategy support. It remains
              review-required and does not become the lawyer-owned Strategy Plan.
            </CardDescription>
          </div>
          {canGenerate ? (
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
                  {latest ? "Re-generate AI support" : "Generate AI support"}
                </>
              )}
            </Button>
          ) : null}
        </CardHeader>
        <CardContent className="py-5 text-sm text-[var(--color-mute)]">
          {!latest ? (
            <EmptyState
              icon={ClipboardCheck}
              title="No AI strategy support yet"
              description="Generate citation-grounded support for counsel review. Human strategy entries stay in the Strategy Plan above."
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
        <StrategyCard
          rec={latest}
          matterId={matterId}
          canApprove={canApprove}
          onDecision={(decision) =>
            decisionMutation.mutate({
              recommendationId: latest.id,
              decision,
            })
          }
          decisionPending={decisionMutation.isPending}
          pendingDecision={
            decisionMutation.isPending
              ? (decisionMutation.variables?.decision ?? null)
              : null
          }
        />
      ) : null}
    </div>
  );
}

function StrategyCard({
  rec,
  matterId,
  canApprove,
  onDecision,
  decisionPending,
  pendingDecision,
}: {
  rec: Recommendation;
  matterId: string;
  canApprove: boolean;
  onDecision: (decision: "accepted" | "edited") => void;
  decisionPending: boolean;
  pendingDecision: "accepted" | "edited" | null;
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

  // Round-2 fix (P1 #3): the most recent decision determines whether
  // the strategy is currently approved. ``accepted`` clears
  // ``review_required`` server-side; the local copy simply mirrors that.
  // Decisions arrive newest-first per the backend ordering, but we
  // sort defensively in case the API order changes.
  const latestDecision = (() => {
    const decisions = rec.decisions ?? [];
    if (decisions.length === 0) return null;
    const sorted = [...decisions].sort((a, b) =>
      a.created_at < b.created_at ? 1 : -1,
    );
    return sorted[0] ?? null;
  })();
  const approved = !rec.review_required && latestDecision?.decision === "accepted";

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
            {approved ? (
              <span
                className="inline-flex items-center gap-1 rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-0.5 text-xs font-medium text-emerald-800"
                data-testid="strategy-approved-badge"
              >
                <CheckCircle2 className="h-3.5 w-3.5" aria-hidden />
                Approved
              </span>
            ) : null}
          </div>
          <CardTitle className="mt-3 text-lg">{rec.title}</CardTitle>
          <CardDescription>
            Generated {formatDateTime(rec.created_at)}
          </CardDescription>
        </div>
        {rec.review_required && canApprove ? (
          <div
            className="flex flex-wrap items-center gap-2"
            data-testid="strategy-approval-bar"
          >
            <Button
              size="sm"
              data-testid="strategy-approve"
              onClick={() => onDecision("accepted")}
              disabled={decisionPending}
            >
              {pendingDecision === "accepted" ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                  Approving…
                </>
              ) : (
                <>
                  <ThumbsUp className="h-4 w-4" aria-hidden />
                  Approve
                </>
              )}
            </Button>
            <Button
              size="sm"
              variant="outline"
              data-testid="strategy-request-changes"
              onClick={() => onDecision("edited")}
              disabled={decisionPending}
            >
              {pendingDecision === "edited" ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                  Submitting…
                </>
              ) : (
                <>
                  <Undo2 className="h-4 w-4" aria-hidden />
                  Request changes
                </>
              )}
            </Button>
          </div>
        ) : null}
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
              {payload.next_best_actions.map((nba, idx) => (
                <li
                  key={`${nba.action}-${idx}`}
                  className="flex items-start gap-2"
                >
                  <span className="flex-1">
                    {nba.action}
                    {/* Round-2 P1 #4: surface unverified items so the
                        partner-reviewer knows which procedural claims
                        the corpus could not back. */}
                    {nba.unverified ? (
                      <span
                        className="ml-2 inline-flex items-center gap-1 rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-amber-800"
                        data-testid="strategy-nba-unverified"
                      >
                        Unverified
                      </span>
                    ) : null}
                  </span>
                </li>
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

function StrategyEntryRow({
  entry,
  canManage,
  isDeleting,
  onEdit,
  onDelete,
}: {
  entry: MatterStrategyEntry;
  canManage: boolean;
  isDeleting: boolean;
  onEdit: () => void;
  onDelete: () => void;
}) {
  return (
    <article
      className="grid gap-3 py-3 md:grid-cols-[minmax(0,1fr)_auto]"
      data-testid="strategy-entry-row"
    >
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={entry.status === "active" ? "success" : "neutral"}>
            {entry.entry_type}
          </Badge>
          <StatusBadge status={entry.status} />
          <span className="text-xs text-[var(--color-mute-2)]">
            Updated {formatDateTime(entry.updated_at)}
          </span>
        </div>
        <h3 className="mt-2 text-sm font-semibold text-[var(--color-ink)]">
          {entry.title}
        </h3>
        <p className="mt-1 whitespace-pre-line text-sm leading-relaxed text-[var(--color-ink-2)]">
          {entry.body}
        </p>
        <p className="mt-2 text-xs text-[var(--color-mute-2)]">
          Owner: {entry.owner_name ?? "Unassigned"} | Last updated by:{" "}
          {entry.updated_by_name ?? entry.created_by_name ?? "Unknown"}
        </p>
      </div>
      {canManage ? (
        <div className="flex items-start gap-2">
          <Button
            size="sm"
            variant="outline"
            onClick={onEdit}
            data-testid="strategy-entry-edit"
          >
            <Pencil className="h-4 w-4" aria-hidden />
            Edit
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={onDelete}
            disabled={isDeleting}
            data-testid="strategy-entry-delete"
          >
            {isDeleting ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            ) : (
              <Trash2 className="h-4 w-4" aria-hidden />
            )}
            Delete
          </Button>
        </div>
      ) : null}
    </article>
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
              {step.unverified ? (
                <span
                  className="inline-flex items-center gap-1 rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-amber-800"
                  data-testid={`strategy-forum-step-unverified-${idx}`}
                >
                  Unverified
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
            {step.supporting_citations.length > 0 ? (
              <p className="mt-1 text-xs text-[var(--color-mute)]">
                <span className="font-semibold">Cited:</span>{" "}
                {step.supporting_citations.join(", ")}
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
        {flag.unverified ? (
          <span
            className="inline-flex items-center gap-1 rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-amber-800"
            data-testid="strategy-limitation-flag-unverified"
          >
            Unverified
          </span>
        ) : null}
      </div>
      <p className="mt-1 text-sm leading-relaxed">{flag.description}</p>
      {flag.statutory_basis ? (
        <p className="mt-1 text-xs">
          <span className="font-semibold">Basis:</span> {flag.statutory_basis}
        </p>
      ) : null}
      {flag.supporting_citations.length > 0 ? (
        <p className="mt-1 text-xs">
          <span className="font-semibold">Cited:</span>{" "}
          {flag.supporting_citations.join(", ")}
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
        {risk.unverified ? (
          <span
            className="inline-flex items-center gap-1 rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-amber-800"
            data-testid="strategy-risk-unverified"
          >
            Unverified
          </span>
        ) : null}
      </div>
      <p className="mt-1 text-sm leading-relaxed">{risk.description}</p>
      {risk.mitigation ? (
        <p className="mt-1 text-xs">
          <span className="font-semibold">Mitigation:</span> {risk.mitigation}
        </p>
      ) : null}
      {risk.supporting_citations.length > 0 ? (
        <p className="mt-1 text-xs">
          <span className="font-semibold">Cited:</span>{" "}
          {risk.supporting_citations.join(", ")}
        </p>
      ) : null}
    </li>
  );
}
