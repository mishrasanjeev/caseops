"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  ExternalLink,
  FileCheck2,
  Loader2,
  Plus,
  RefreshCw,
  Save,
  Scale,
  ScanSearch,
  Trash2,
} from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/Badge";
import { SourceAction } from "@/components/app/SourceAction";
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
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/Select";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/Tabs";
import { Textarea } from "@/components/ui/Textarea";
import { apiErrorMessage } from "@/lib/api/config";
import {
  fetchAuthorityResearchReports,
  fetchIpCoreRecords,
  fetchIpPortfolio,
  listMatters,
  type AuthorityResearchReport,
  type IpPortfolioRow,
} from "@/lib/api/endpoints";
import {
  createIntelligentReview,
  finalizeIntelligentReview,
  getIntelligentReview,
  listIntelligentReviews,
  publishIntelligentReview,
  updateIntelligentReviewAuthorities,
  type IntelligentReview,
  type IntelligentReviewAuthority,
  type IntelligentReviewFactInput,
} from "@/lib/api/intelligent-reviews";
import { can, type Capability, useResolvedCapabilities, useRole } from "@/lib/capabilities";
import { formatLegalDate } from "@/lib/dates";

type TargetKind = "matter" | "ip_docket";

const EMPTY_FACT: IntelligentReviewFactInput = { label: "", value: "", source_ref: "" };

export default function IntelligentReviewsPage() {
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const linkedReportId = searchParams.get("report") ?? "";
  const role = useRole();
  const resolvedCapabilities = useResolvedCapabilities();
  const hasCapability = (capability: Capability) =>
    resolvedCapabilities
      ? resolvedCapabilities.includes(capability)
      : can(role, capability);

  const reportsQuery = useQuery({
    queryKey: ["authorities", "research-reports"],
    queryFn: fetchAuthorityResearchReports,
  });
  const mattersQuery = useQuery({
    queryKey: ["matters", "intelligent-review-targets"],
    queryFn: () => listMatters({ limit: 100 }),
  });
  const ipQuery = useQuery({
    queryKey: ["ip", "intelligent-review-targets"],
    queryFn: () => fetchIpPortfolio({}, { limit: 100 }),
  });
  const reviewsQuery = useQuery({
    queryKey: ["research", "intelligent-reviews"],
    queryFn: () => listIntelligentReviews({ limit: 50 }),
    refetchInterval: (query) =>
      query.state.data?.reviews.some((review) =>
        ["queued", "running"].includes(review.state),
      )
        ? 2_000
        : false,
  });

  const [selectedReviewId, setSelectedReviewId] = useState<string | null>(null);
  const [reportId, setReportId] = useState(linkedReportId);
  const [targetKind, setTargetKind] = useState<TargetKind>("matter");
  const [targetId, setTargetId] = useState("");
  const [proceedingId, setProceedingId] = useState("");
  const [issue, setIssue] = useState("");
  const [facts, setFacts] = useState<IntelligentReviewFactInput[]>([{ ...EMPTY_FACT }]);
  const [documentRefs, setDocumentRefs] = useState("");
  const [sourceIds, setSourceIds] = useState<string[]>([]);
  const proceedingsQuery = useQuery({
    queryKey: ["ip", "intelligent-review-proceedings", targetId],
    queryFn: () => fetchIpCoreRecords(targetId),
    enabled: targetKind === "ip_docket" && Boolean(targetId),
  });

  const reports = reportsQuery.data?.reports ?? [];
  const selectedReport = reports.find((report) => report.id === reportId) ?? null;

  useEffect(() => {
    if (!reportId && reports.length > 0) setReportId(reports[0].id);
  }, [reportId, reports]);

  useEffect(() => {
    if (!selectedReport) return;
    setSourceIds(selectedReport.results.map((result) => result.authority_document_id));
    if (!issue.trim()) setIssue(selectedReport.query);
  }, [selectedReport?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!selectedReviewId && (reviewsQuery.data?.reviews.length ?? 0) > 0) {
      setSelectedReviewId(reviewsQuery.data?.reviews[0].id ?? null);
    }
  }, [reviewsQuery.data?.reviews, selectedReviewId]);

  const createMutation = useMutation({
    mutationFn: createIntelligentReview,
    onSuccess: async (review) => {
      setSelectedReviewId(review.id);
      await queryClient.invalidateQueries({ queryKey: ["research", "intelligent-reviews"] });
      toast.success("Intelligent review queued against the frozen sources.");
    },
    onError: (error) =>
      toast.error(apiErrorMessage(error, "Could not start the intelligent review.")),
  });

  const createReview = () => {
    const cleanFacts = facts
      .map((fact) => ({
        label: fact.label.trim(),
        value: fact.value.trim(),
        source_ref: fact.source_ref?.trim() || null,
      }))
      .filter((fact) => fact.label && fact.value);
    if (!reportId || !targetId || issue.trim().length < 3 || sourceIds.length === 0) {
      toast.error("Choose a frozen report, target, issue, and at least one authority.");
      return;
    }
    createMutation.mutate({
      issue: issue.trim(),
      sourceResearchReportId: reportId,
      matterId: targetKind === "matter" ? targetId : null,
      ipDocketId: targetKind === "ip_docket" ? targetId : null,
      ipProceedingId:
        targetKind === "ip_docket" && proceedingId ? proceedingId : null,
      facts: cleanFacts,
      documentRefs: documentRefs
        .split("\n")
        .map((value) => value.trim())
        .filter(Boolean),
      includedAuthorityIds: sourceIds,
    });
  };

  return (
    <div className="flex min-w-0 flex-col gap-6">
      <PageHeader
        eyebrow="Research"
        title="Intelligent review"
        description="Compare supporting and contrary authorities from a frozen report, then require lawyer approval before Draft handoff."
        actions={
          <Button href="/app/research/saved" variant="outline" size="sm">
            <ArrowLeft className="h-4 w-4" aria-hidden /> Saved research
          </Button>
        }
      />

      <Card data-testid="intelligent-review-create">
        <CardHeader>
          <CardTitle as="h2" className="text-base">Start from frozen research</CardTitle>
          <CardDescription>
            The report, source versions, hashes, selected target, facts, and prompt policy are frozen with the generated analysis.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex min-w-0 flex-col gap-5">
          {!hasCapability("recommendations:generate") ? (
            <Notice tone="warning">
              Your role can read permitted reviews but cannot generate a new one.
            </Notice>
          ) : null}

          {reportsQuery.isError ? (
            <QueryErrorState
              title="Could not load frozen reports"
              error={reportsQuery.error}
              onRetry={reportsQuery.refetch}
            />
          ) : reports.length === 0 && !reportsQuery.isPending ? (
            <EmptyState
              icon={FileCheck2}
              title="Freeze research first"
              description="Save a source-backed research report before starting intelligent review."
              action={<Button href="/app/research">Open research</Button>}
            />
          ) : (
            <>
              <div className="grid min-w-0 gap-4 lg:grid-cols-2">
                <Field label="Frozen research report" htmlFor="review-report">
                  <Select value={reportId} onValueChange={setReportId}>
                    <SelectTrigger id="review-report">
                      <SelectValue placeholder="Choose a report" />
                    </SelectTrigger>
                    <SelectContent>
                      {reports.map((report) => (
                        <SelectItem key={report.id} value={report.id}>{report.name}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Field>

                <div className="min-w-0">
                  <Label>Review target</Label>
                  <Tabs
                    value={targetKind}
                    onValueChange={(value) => {
                      setTargetKind(value as TargetKind);
                      setTargetId("");
                      setProceedingId("");
                    }}
                    className="mt-2 min-w-0"
                  >
                    <TabsList className="flex h-auto w-full min-w-0 flex-wrap">
                      <TabsTrigger className="min-w-0 flex-1" value="matter">Matter</TabsTrigger>
                      <TabsTrigger className="min-w-0 flex-1" value="ip_docket">IP docket</TabsTrigger>
                    </TabsList>
                    <TabsContent value="matter">
                      <TargetSelect
                        id="review-matter-target"
                        label="Matter target"
                        value={targetId}
                        onValueChange={(value) => {
                          setTargetId(value);
                          setProceedingId("");
                        }}
                        placeholder={mattersQuery.isPending ? "Loading matters" : "Choose a Matter"}
                        options={(mattersQuery.data?.matters ?? [])
                          .filter((matter) => !["closed", "disposed"].includes(matter.status))
                          .map((matter) => ({
                            id: matter.id,
                            label: `${matter.matter_code} · ${matter.title}`,
                          }))}
                      />
                    </TabsContent>
                    <TabsContent value="ip_docket">
                      <TargetSelect
                        id="review-ip-target"
                        label="IP docket target"
                        value={targetId}
                        onValueChange={setTargetId}
                        placeholder={ipQuery.isPending ? "Loading IP dockets" : "Choose an IP docket"}
                        options={(ipQuery.data?.rows ?? [])
                          .filter((row) => row.is_active)
                          .map((row) => ({ id: row.docket_id, label: ipTargetLabel(row) }))}
                      />
                      {targetId ? (
                        <div className="mt-3">
                          <TargetSelect
                            id="review-ip-proceeding"
                            label="Opposition proceeding for Draft handoff"
                            value={proceedingId}
                            onValueChange={setProceedingId}
                            placeholder={
                              proceedingsQuery.isPending
                                ? "Loading proceedings"
                                : "Docket-level review only"
                            }
                            options={(proceedingsQuery.data?.proceedings ?? [])
                              .filter((row) => row.proceeding_kind === "opposition")
                              .map((row) => ({
                                id: row.id,
                                label: `${row.side} · ${row.stage} · ${row.office}`,
                              }))}
                          />
                        </div>
                      ) : null}
                    </TabsContent>
                  </Tabs>
                </div>
              </div>

              <Field label="Issue for review" htmlFor="review-issue">
                <Textarea
                  id="review-issue"
                  value={issue}
                  onChange={(event) => setIssue(event.target.value)}
                  maxLength={1200}
                  rows={3}
                  placeholder="State the legal issue precisely."
                />
              </Field>

              <section aria-labelledby="review-facts-title" className="min-w-0 border-t border-[var(--color-line)] pt-4">
                <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
                  <div className="min-w-0">
                    <h3 id="review-facts-title" className="text-sm font-semibold">Known facts and conflicts</h3>
                    <p className="text-xs text-[var(--color-mute)]">Repeat a label with differing values to preserve the contradiction for lawyer review.</p>
                  </div>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() => setFacts((current) => [...current, { ...EMPTY_FACT }])}
                  >
                    <Plus className="h-4 w-4" aria-hidden /> Add fact
                  </Button>
                </div>
                <div className="mt-3 grid gap-3">
                  {facts.map((fact, index) => (
                    <div key={index} className="grid min-w-0 gap-2 sm:grid-cols-[minmax(0,0.8fr)_minmax(0,1.4fr)_minmax(0,1fr)_2.5rem]">
                      <Input
                        aria-label={`Fact ${index + 1} label`}
                        placeholder="Label"
                        value={fact.label}
                        maxLength={160}
                        onChange={(event) => setFact(setFacts, facts, index, "label", event.target.value)}
                      />
                      <Input
                        aria-label={`Fact ${index + 1} value`}
                        placeholder="Value"
                        value={fact.value}
                        maxLength={2000}
                        onChange={(event) => setFact(setFacts, facts, index, "value", event.target.value)}
                      />
                      <Input
                        aria-label={`Fact ${index + 1} source`}
                        placeholder="Source or document"
                        value={fact.source_ref ?? ""}
                        maxLength={500}
                        onChange={(event) => setFact(setFacts, facts, index, "source_ref", event.target.value)}
                      />
                      <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        aria-label={`Remove fact ${index + 1}`}
                        title="Remove fact"
                        disabled={facts.length === 1}
                        onClick={() => setFacts((current) => current.filter((_, item) => item !== index))}
                      >
                        <Trash2 className="h-4 w-4" aria-hidden />
                      </Button>
                    </div>
                  ))}
                </div>
              </section>

              <Field label="Document references" htmlFor="review-document-refs" hint="One existing document name or reference per line.">
                <Textarea
                  id="review-document-refs"
                  value={documentRefs}
                  onChange={(event) => setDocumentRefs(event.target.value)}
                  rows={3}
                  placeholder="Client instruction dated 12 August 2026"
                />
              </Field>

              {selectedReport ? (
                <SourceSelection
                  report={selectedReport}
                  selectedIds={sourceIds}
                  onChange={setSourceIds}
                />
              ) : null}

              <div className="flex min-w-0 flex-wrap items-center justify-between gap-3 border-t border-[var(--color-line)] pt-4">
                <p className="max-w-3xl text-xs leading-relaxed text-[var(--color-mute)]">
                  Generation is source-bounded decision support. It cannot predict a judge, guarantee a strategy, or replace current-law verification.
                </p>
                <Button
                  type="button"
                  className="w-full sm:w-auto"
                  disabled={createMutation.isPending || !hasCapability("recommendations:generate")}
                  onClick={createReview}
                >
                  {createMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <ScanSearch className="h-4 w-4" aria-hidden />}
                  Generate review
                </Button>
              </div>
            </>
          )}
        </CardContent>
      </Card>

      <section className="grid min-w-0 gap-5 xl:grid-cols-[minmax(16rem,0.34fr)_minmax(0,1fr)]" aria-labelledby="review-history-title">
        <div className="min-w-0">
          <div className="mb-3 flex min-w-0 flex-wrap items-center justify-between gap-2">
            <h2 id="review-history-title" className="text-base font-semibold">Review history</h2>
            <Button size="sm" variant="ghost" onClick={() => reviewsQuery.refetch()} aria-label="Refresh reviews" title="Refresh reviews">
              <RefreshCw className={reviewsQuery.isFetching ? "h-4 w-4 animate-spin" : "h-4 w-4"} aria-hidden />
            </Button>
          </div>
          {reviewsQuery.isError ? (
            <QueryErrorState title="Could not load reviews" error={reviewsQuery.error} onRetry={reviewsQuery.refetch} />
          ) : reviewsQuery.isPending ? (
            <p className="text-sm text-[var(--color-mute)]">Loading reviews…</p>
          ) : (reviewsQuery.data?.reviews.length ?? 0) === 0 ? (
            <EmptyState icon={Scale} title="No intelligent reviews yet" description="Start with a frozen research report above." />
          ) : (
            <div className="grid gap-2">
              {(reviewsQuery.data?.reviews ?? []).map((review) => (
                <button
                  type="button"
                  key={review.id}
                  onClick={() => setSelectedReviewId(review.id)}
                  aria-pressed={review.id === selectedReviewId}
                  className="min-w-0 rounded-md border border-[var(--color-line)] bg-white p-3 text-left transition-colors hover:bg-[var(--color-bg-2)] aria-pressed:border-[var(--color-ink-3)] aria-pressed:bg-[var(--color-bg-2)]"
                >
                  <div className="flex min-w-0 items-start justify-between gap-2">
                    <span className="line-clamp-2 min-w-0 text-sm font-medium">{review.issue}</span>
                    <StatusBadge status={review.state} />
                  </div>
                  <p className="mt-2 text-xs text-[var(--color-mute)]">{formatLegalDate(review.created_at)}</p>
                </button>
              ))}
            </div>
          )}
        </div>

        <ReviewDetail
          reviewId={selectedReviewId}
          canDecide={hasCapability("recommendations:decide")}
          canPublish={hasCapability("drafts:review")}
        />
      </section>
    </div>
  );
}

function Field({
  label,
  htmlFor,
  hint,
  children,
}: {
  label: string;
  htmlFor: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="min-w-0">
      <Label htmlFor={htmlFor}>{label}</Label>
      {hint ? <p className="mt-1 text-xs text-[var(--color-mute)]">{hint}</p> : null}
      <div className="mt-2">{children}</div>
    </div>
  );
}

function TargetSelect({
  id,
  label,
  value,
  onValueChange,
  placeholder,
  options,
}: {
  id: string;
  label: string;
  value: string;
  onValueChange: (value: string) => void;
  placeholder: string;
  options: Array<{ id: string; label: string }>;
}) {
  return (
    <Select value={value} onValueChange={onValueChange}>
      <SelectTrigger id={id} aria-label={label}><SelectValue placeholder={placeholder} /></SelectTrigger>
      <SelectContent>
        {options.map((option) => <SelectItem key={option.id} value={option.id}>{option.label}</SelectItem>)}
      </SelectContent>
    </Select>
  );
}

function SourceSelection({
  report,
  selectedIds,
  onChange,
}: {
  report: AuthorityResearchReport;
  selectedIds: string[];
  onChange: (ids: string[]) => void;
}) {
  return (
    <section aria-labelledby="review-source-title" className="min-w-0 border-t border-[var(--color-line)] pt-4">
      <div className="flex min-w-0 flex-wrap items-end justify-between gap-2">
        <div className="min-w-0">
          <h3 id="review-source-title" className="text-sm font-semibold">Frozen authority set</h3>
          <p className="text-xs text-[var(--color-mute)]">Only checked result IDs are available to the review.</p>
        </div>
        <Badge tone={selectedIds.length ? "brand" : "warning"}>{selectedIds.length} selected</Badge>
      </div>
      <div className="mt-3 grid gap-2 lg:grid-cols-2">
        {report.results.map((result) => {
          const checked = selectedIds.includes(result.authority_document_id);
          return (
            <label key={result.authority_document_id} className="flex min-w-0 cursor-pointer items-start gap-3 rounded-md border border-[var(--color-line)] p-3">
              <input
                type="checkbox"
                className="mt-1 h-4 w-4 shrink-0 accent-[var(--color-brand-700)]"
                checked={checked}
                onChange={() => onChange(checked ? selectedIds.filter((id) => id !== result.authority_document_id) : [...selectedIds, result.authority_document_id])}
              />
              <span className="min-w-0">
                <span className="block break-words text-sm font-medium">{result.title}</span>
                <span className="mt-1 block text-xs text-[var(--color-mute)]">{[result.court_name, result.neutral_citation ?? result.case_reference].filter(Boolean).join(" · ")}</span>
              </span>
            </label>
          );
        })}
      </div>
    </section>
  );
}

function ReviewDetail({
  reviewId,
  canDecide,
  canPublish,
}: {
  reviewId: string | null;
  canDecide: boolean;
  canPublish: boolean;
}) {
  const queryClient = useQueryClient();
  const reviewQuery = useQuery({
    queryKey: ["research", "intelligent-review", reviewId],
    queryFn: () => getIntelligentReview(reviewId ?? ""),
    enabled: Boolean(reviewId),
    refetchInterval: (query) =>
      ["queued", "running"].includes(query.state.data?.state ?? "") ? 1_500 : false,
  });
  const review = reviewQuery.data;
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [lawyerNotes, setLawyerNotes] = useState("");

  useEffect(() => {
    if (!review) return;
    setSelectedIds(
      [...review.supporting_authorities, ...review.contrary_authorities]
        .filter((authority) => authority.selected)
        .map((authority) => authority.authority_document_id),
    );
    setLawyerNotes(review.lawyer_notes ?? "");
  }, [review?.id, review?.updated_at]); // eslint-disable-line react-hooks/exhaustive-deps

  const sync = async (updated: IntelligentReview) => {
    queryClient.setQueryData(["research", "intelligent-review", updated.id], updated);
    await queryClient.invalidateQueries({ queryKey: ["research", "intelligent-reviews"] });
  };
  const selectionMutation = useMutation({
    mutationFn: () => updateIntelligentReviewAuthorities({ reviewId: review?.id ?? "", includedAuthorityIds: selectedIds, lawyerNotes }),
    onSuccess: async (updated) => { await sync(updated); toast.success("Authority selection saved."); },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not save the authority selection.")),
  });
  const finalizeMutation = useMutation({
    mutationFn: () => finalizeIntelligentReview({ reviewId: review?.id ?? "", lawyerNotes }),
    onSuccess: async (updated) => { await sync(updated); toast.success("Review finalized by the authorized lawyer."); },
    onError: (error) => toast.error(apiErrorMessage(error, "The review is not ready to finalize.")),
  });
  const publishMutation = useMutation({
    mutationFn: () => publishIntelligentReview({ reviewId: review?.id ?? "", title: review ? `Intelligent review · ${review.issue}` : null }),
    onSuccess: async (result) => { await sync(result.review); toast.success("Approved review published into the Draft lifecycle."); },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not publish this review to Drafts.")),
  });

  if (!reviewId) {
    return <EmptyState icon={ScanSearch} title="Select a review" description="Open a generated review from the history to inspect its source record." />;
  }
  if (reviewQuery.isError) {
    return <QueryErrorState title="Could not load this review" error={reviewQuery.error} onRetry={reviewQuery.refetch} />;
  }
  if (!review) {
    return <div className="flex min-h-48 items-center justify-center text-sm text-[var(--color-mute)]"><Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden /> Loading review</div>;
  }

  const authorities = [...review.supporting_authorities, ...review.contrary_authorities];
  const mutable = review.state === "ready";
  const draftHandoffAvailable = Boolean(review.matter_id || review.ip_proceeding_id);
  const publishedDraftHref = review.published_draft_id
    ? review.matter_id
      ? `/app/matters/${encodeURIComponent(review.matter_id)}/drafts/${encodeURIComponent(review.published_draft_id)}`
      : review.ip_docket_id && review.ip_proceeding_id
        ? `/app/ip?docket=${encodeURIComponent(review.ip_docket_id)}&view=proceedings&proceeding=${encodeURIComponent(review.ip_proceeding_id)}&draft=${encodeURIComponent(review.published_draft_id)}`
        : null
    : null;
  return (
    <Card data-testid="intelligent-review-detail" className="min-w-0">
      <CardHeader className="min-w-0">
        <div className="flex min-w-0 flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <CardTitle as="h2" className="break-words text-base">{review.issue}</CardTitle>
            <CardDescription className="mt-1">Created {formatLegalDate(review.created_at)} · {review.matter_id ? "Matter" : "IP docket"} target</CardDescription>
          </div>
          <StatusBadge status={review.state} />
        </div>
        <div className="mt-3 h-2 overflow-hidden rounded-full bg-[var(--color-bg-2)]" role="progressbar" aria-valuenow={review.progress} aria-valuemin={0} aria-valuemax={100} aria-label="Review generation progress">
          <div className="h-full bg-[var(--color-brand-700)] transition-[width]" style={{ width: `${review.progress}%` }} />
        </div>
      </CardHeader>
      <CardContent className="flex min-w-0 flex-col gap-5">
        {review.state === "abstained" || review.state === "failed" ? (
          <Notice tone="warning">
            {review.abstention_reason ?? "The review could not be completed."}{review.error_code ? ` (${review.error_code})` : ""}
          </Notice>
        ) : null}
        {review.stale_warning ? <Notice tone="warning">{review.stale_warning}</Notice> : null}
        <Notice tone="neutral">{review.non_exhaustive_disclaimer}</Notice>

        {review.state === "queued" || review.state === "running" ? (
          <div className="flex items-center gap-2 py-8 text-sm text-[var(--color-mute)]"><Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Verifying frozen sources and generating the review…</div>
        ) : authorities.length > 0 ? (
          <>
            <ReviewList title="Relevant facts" items={review.relevant_facts} />
            <AssertionList title="Applicable provisions" items={review.applicable_provisions} authorities={authorities} />

            <section aria-labelledby="review-authorities-title" className="min-w-0 border-t border-[var(--color-line)] pt-4">
              <div className="flex min-w-0 flex-wrap items-end justify-between gap-2">
                <div className="min-w-0">
                  <h3 id="review-authorities-title" className="text-sm font-semibold">Supporting and contrary authorities</h3>
                  <p className="text-xs text-[var(--color-mute)]">Every passage remains tied to its frozen source version and URL.</p>
                </div>
                <Badge tone={review.completeness.complete ? "success" : "warning"}>{review.completeness.complete ? "Complete" : "Review incomplete"}</Badge>
              </div>
              <div className="mt-3 grid min-w-0 gap-4 lg:grid-cols-2">
                <AuthorityColumn
                  title="Supporting"
                  authorities={review.supporting_authorities}
                  selectedIds={selectedIds}
                  mutable={mutable && canDecide}
                  onToggle={(id) => setSelectedIds(toggleId(selectedIds, id))}
                />
                <AuthorityColumn
                  title="Contrary"
                  authorities={review.contrary_authorities}
                  selectedIds={selectedIds}
                  mutable={mutable && canDecide}
                  onToggle={(id) => setSelectedIds(toggleId(selectedIds, id))}
                />
              </div>
            </section>

            <AssertionList title="Factual analogies" items={review.factual_analogies} authorities={authorities} />
            <div className="grid min-w-0 gap-4 lg:grid-cols-2">
              <ReviewList title="Research gaps" items={review.gaps} />
              <ReviewList title="Lawyer checks" items={review.lawyer_checks} />
            </div>
            {review.unresolved_contradictions.length ? (
              <section aria-labelledby="review-contradictions-title" className="border-l-4 border-amber-400 bg-amber-50 p-4">
                <h3 id="review-contradictions-title" className="flex items-center gap-2 text-sm font-semibold text-amber-900"><AlertTriangle className="h-4 w-4" aria-hidden /> Unresolved contradictions</h3>
                <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-amber-950">{review.unresolved_contradictions.map((item) => <li key={item}>{item}</li>)}</ul>
              </section>
            ) : null}

            <section aria-labelledby="review-approval-title" className="min-w-0 border-t border-[var(--color-line)] pt-4">
              <h3 id="review-approval-title" className="text-sm font-semibold">Lawyer approval</h3>
              <div className="mt-3">
                <Label htmlFor="review-lawyer-notes">Review notes</Label>
                <Textarea id="review-lawyer-notes" className="mt-2" rows={4} maxLength={5000} value={lawyerNotes} disabled={!mutable || !canDecide} onChange={(event) => setLawyerNotes(event.target.value)} />
              </div>
              {!review.completeness.complete ? (
                <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-amber-900">{review.completeness.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
              ) : null}
              {review.state === "finalized" && !draftHandoffAvailable ? (
                <Notice tone="warning">
                  This docket-level review has no opposition proceeding for Draft handoff.
                </Notice>
              ) : null}
              <div className="mt-4 flex min-w-0 flex-wrap justify-end gap-2">
                {mutable ? (
                  <>
                    <Button variant="outline" className="w-full sm:w-auto" disabled={!canDecide || selectionMutation.isPending} onClick={() => selectionMutation.mutate()}>
                      {selectionMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <Save className="h-4 w-4" aria-hidden />} Save selection
                    </Button>
                    <Button className="w-full sm:w-auto" disabled={!canDecide || !review.completeness.complete || finalizeMutation.isPending} onClick={() => finalizeMutation.mutate()}>
                      {finalizeMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <CheckCircle2 className="h-4 w-4" aria-hidden />} Finalize review
                    </Button>
                  </>
                ) : null}
                {review.state === "finalized" ? (
                  <Button className="w-full sm:w-auto" disabled={!canPublish || !draftHandoffAvailable || publishMutation.isPending} onClick={() => publishMutation.mutate()}>
                    {publishMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <FileCheck2 className="h-4 w-4" aria-hidden />} Publish to Drafts
                  </Button>
                ) : null}
                {publishedDraftHref ? (
                  <Button href={publishedDraftHref} variant="outline" className="w-full sm:w-auto">Open Draft <ExternalLink className="h-4 w-4" aria-hidden /></Button>
                ) : null}
              </div>
            </section>
          </>
        ) : null}

        <div className="flex min-w-0 flex-wrap gap-x-4 gap-y-1 border-t border-[var(--color-line)] pt-3 text-xs text-[var(--color-mute)]">
          <span>Freshness {review.source_freshness_at ? formatLegalDate(review.source_freshness_at) : "unavailable"}</span>
          <span>Template {review.review_template_version ?? "unavailable"}</span>
          <span>Policy {review.prompt_policy_version ?? "unavailable"}</span>
          {review.output_hash ? <span className="break-all">Output {review.output_hash}</span> : null}
        </div>
      </CardContent>
    </Card>
  );
}

function AuthorityColumn({
  title,
  authorities,
  selectedIds,
  mutable,
  onToggle,
}: {
  title: string;
  authorities: IntelligentReviewAuthority[];
  selectedIds: string[];
  mutable: boolean;
  onToggle: (id: string) => void;
}) {
  return (
    <div className="min-w-0">
      <h4 className="mb-2 text-sm font-semibold">{title}</h4>
      {authorities.length === 0 ? <p className="text-sm text-[var(--color-mute)]">No {title.toLowerCase()} authority was verified.</p> : null}
      <div className="grid gap-3">
        {authorities.map((authority) => (
          <article key={authority.authority_document_id} className="min-w-0 rounded-md border border-[var(--color-line)] p-3">
            <label className="flex min-w-0 items-start gap-3">
              <input type="checkbox" className="mt-1 h-4 w-4 shrink-0 accent-[var(--color-brand-700)]" checked={selectedIds.includes(authority.authority_document_id)} disabled={!mutable} onChange={() => onToggle(authority.authority_document_id)} />
              <span className="min-w-0">
                <span className="block break-words text-sm font-semibold">{authority.title}</span>
                <span className="mt-1 block text-xs text-[var(--color-mute)]">{[authority.citation, authority.court, authority.decision_date ? formatLegalDate(authority.decision_date) : null].filter(Boolean).join(" · ")}</span>
              </span>
            </label>
            <blockquote className="mt-3 border-l-2 border-[var(--color-line)] pl-3 text-sm leading-relaxed text-[var(--color-ink-2)]">{authority.passage}</blockquote>
            <p className="mt-3 text-sm"><span className="font-medium">Relevance:</span> {authority.relevance}</p>
            {authority.treatment ? <p className="mt-1 text-sm"><span className="font-medium">Treatment:</span> {authority.treatment}</p> : null}
            {authority.source_url ? (
              <div className="mt-3 min-w-0">
                <SourceAction
                  action={authority.source_action}
                  originSurface="intelligent_review"
                />
                <p className="mt-1 break-all text-xs text-[var(--color-mute)]">{authority.source_url}</p>
              </div>
            ) : <p className="mt-3 text-xs text-rose-700">Source cannot be opened; this authority cannot support finalization.</p>}
            <p className="mt-2 break-all text-[11px] text-[var(--color-mute-2)]">Version {authority.source_version ?? "unknown"} · {authority.content_hash ?? "hash unavailable"}</p>
          </article>
        ))}
      </div>
    </div>
  );
}

function AssertionList({
  title,
  items,
  authorities,
}: {
  title: string;
  items: IntelligentReview["applicable_provisions"];
  authorities: IntelligentReviewAuthority[];
}) {
  if (!items.length) return null;
  const citations = new Map(authorities.map((authority) => [authority.authority_document_id, authority.citation]));
  return (
    <section className="border-t border-[var(--color-line)] pt-4">
      <h3 className="text-sm font-semibold">{title}</h3>
      <ul className="mt-2 grid gap-2 text-sm">{items.map((item) => (
        <li key={`${item.text}-${item.authority_document_ids.join("-")}`}>
          <p>{item.text}</p>
          <p className="mt-1 text-xs text-[var(--color-mute)]">Cites {item.authority_document_ids.map((id) => citations.get(id) ?? id).join("; ")}</p>
        </li>
      ))}</ul>
    </section>
  );
}

function ReviewList({ title, items }: { title: string; items: string[] }) {
  if (!items.length) return null;
  return (
    <section className="border-t border-[var(--color-line)] pt-4">
      <h3 className="text-sm font-semibold">{title}</h3>
      <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-[var(--color-ink-2)]">{items.map((item) => <li key={item}>{item}</li>)}</ul>
    </section>
  );
}

function Notice({ children, tone }: { children: React.ReactNode; tone: "neutral" | "warning" }) {
  return <div className={tone === "warning" ? "border-l-4 border-amber-400 bg-amber-50 p-3 text-sm text-amber-950" : "border-l-4 border-[var(--color-line)] bg-[var(--color-bg-2)] p-3 text-sm text-[var(--color-ink-2)]"}>{children}</div>;
}

function toggleId(ids: string[], id: string) {
  return ids.includes(id) ? ids.filter((value) => value !== id) : [...ids, id];
}

function ipTargetLabel(row: IpPortfolioRow) {
  const identifier = row.primary_identifier ?? row.application_numbers[0] ?? "Identifier pending";
  return `${identifier} · ${row.docket_title}`;
}

function setFact(
  setter: React.Dispatch<React.SetStateAction<IntelligentReviewFactInput[]>>,
  facts: IntelligentReviewFactInput[],
  index: number,
  key: keyof IntelligentReviewFactInput,
  value: string,
) {
  setter(facts.map((fact, item) => item === index ? { ...fact, [key]: value } : fact));
}
