"use client";

import { useQuery } from "@tanstack/react-query";
import { Bookmark, FileCheck2, Loader2, ScanSearch } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

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
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { SourceAction } from "@/components/app/SourceAction";
import {
  fetchSavedAuthorityAnnotations,
  fetchAuthorityResearchReports,
  type AuthorityResearchReport,
  type SavedAuthorityAnnotation,
} from "@/lib/api/endpoints";
import { formatLegalDate } from "@/lib/dates";

export default function SavedResearchPage() {
  const [includeArchived, setIncludeArchived] = useState(false);
  const savedQuery = useQuery({
    queryKey: ["authorities", "saved", { includeArchived }],
    queryFn: () =>
      fetchSavedAuthorityAnnotations({ includeArchived, limit: 200 }),
  });
  const reportsQuery = useQuery({
    queryKey: ["authorities", "research-reports"],
    queryFn: fetchAuthorityResearchReports,
  });

  const annotations: SavedAuthorityAnnotation[] =
    savedQuery.data?.annotations ?? [];

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Research"
        title="Saved research"
        description="Every authority you've flagged, noted, or tagged. Newest first."
        actions={
          <Link href="/app/research">
            <Button variant="outline" size="sm">
              Back to search
            </Button>
          </Link>
        }
      />

      <div className="flex items-center justify-between">
        <Button
          size="sm"
          variant={includeArchived ? "primary" : "outline"}
          onClick={() => setIncludeArchived((v) => !v)}
          data-testid="saved-research-toggle-archived"
        >
          {includeArchived ? "Hide archived" : "Show archived"}
        </Button>
        {savedQuery.isFetching ? (
          <span className="flex items-center gap-2 text-xs text-[var(--color-ink-2)]">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            Loading
          </span>
        ) : (
          <span className="text-xs text-[var(--color-ink-2)]">
            {annotations.length} saved
          </span>
        )}
      </div>

      {savedQuery.isError ? (
        <QueryErrorState
          error={savedQuery.error}
          title="Could not load saved research"
          onRetry={() => savedQuery.refetch()}
        />
      ) : null}

      <section className="flex flex-col gap-3" aria-labelledby="saved-reports-title">
        <div className="flex min-w-0 flex-wrap items-end justify-between gap-2">
          <div className="min-w-0">
            <h2 id="saved-reports-title" className="text-base font-semibold text-[var(--color-ink)]">
              Frozen reports
            </h2>
            <p className="text-xs text-[var(--color-mute)]">
              Immutable result IDs, source metadata, and analysis version captured when saved.
            </p>
          </div>
          <span className="text-xs text-[var(--color-mute)]">
            {reportsQuery.data?.reports.length ?? 0} reports
          </span>
        </div>
        {reportsQuery.isError ? (
          <QueryErrorState
            error={reportsQuery.error}
            title="Could not load frozen research reports"
            onRetry={() => reportsQuery.refetch()}
          />
        ) : null}
        {!reportsQuery.isError && !reportsQuery.isLoading && (reportsQuery.data?.reports.length ?? 0) === 0 ? (
          <EmptyState
            icon={FileCheck2}
            title="No frozen reports yet"
            description="Run a search and choose Save report to preserve its result set and source metadata."
          />
        ) : null}
        <div className="grid gap-3">
          {(reportsQuery.data?.reports ?? []).map((report) => (
            <SavedResearchReportCard key={report.id} report={report} />
          ))}
        </div>
      </section>

      {!savedQuery.isError && !savedQuery.isLoading && annotations.length === 0 ? (
        <EmptyState
          icon={Bookmark}
          title={
            includeArchived
              ? "No saved research yet, archived or otherwise."
              : "Nothing saved yet."
          }
          description="Use Save on any search result to add it here. Saved research is private to your workspace."
          action={
            <Link href="/app/research">
              <Button>Open research</Button>
            </Link>
          }
        />
      ) : null}

      <div className="grid gap-3">
        {annotations.map((ann) => (
          <SavedAnnotationCard key={ann.id} annotation={ann} />
        ))}
      </div>
    </div>
  );
}

function SavedResearchReportCard({ report }: { report: AuthorityResearchReport }) {
  const query = new URLSearchParams({ q: report.query, mode: report.mode });
  return (
    <Card data-testid={`saved-research-report-${report.id}`}>
      <CardHeader className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <CardTitle className="break-words text-base">{report.name}</CardTitle>
          <CardDescription className="mt-1 break-words">
            {report.query}
          </CardDescription>
        </div>
        <div className="flex w-full min-w-0 flex-col gap-2 sm:w-auto sm:flex-row sm:flex-wrap">
          <Link href={`/app/research?${query.toString()}`} className="w-full sm:w-auto">
            <Button size="sm" variant="outline" className="w-full sm:w-auto">
              Refine search
            </Button>
          </Link>
          <Link
            href={`/app/research/reviews?report=${encodeURIComponent(report.id)}`}
            className="w-full sm:w-auto"
          >
            <Button size="sm" className="w-full sm:w-auto">
              <ScanSearch className="h-4 w-4" aria-hidden />
              Start intelligent review
            </Button>
          </Link>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 text-sm">
        <div className="flex flex-wrap gap-2 text-xs text-[var(--color-mute)]">
          <Badge tone="neutral">{report.mode.replace(/_/g, " ")}</Badge>
          <span>{report.results.length} frozen results</span>
          <span>Analysis {report.analysis_version}</span>
          <span>Saved {formatLegalDate(report.created_at)}</span>
        </div>
        <ul className="grid gap-2">
          {report.results.map((result) => (
            <li
              key={result.authority_document_id}
              className="flex min-w-0 flex-col gap-2 rounded-md border border-[var(--color-line)] p-3 sm:flex-row sm:items-start sm:justify-between"
            >
              <div className="min-w-0">
                <p className="break-words font-medium text-[var(--color-ink)]">{result.title}</p>
                <p className="text-xs text-[var(--color-mute)]">
                  {[result.court_name, result.neutral_citation, result.case_reference]
                    .filter(Boolean)
                    .join(" · ")}
                </p>
              </div>
              <SourceAction action={result.source_action} compact />
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

function SavedAnnotationCard({
  annotation: a,
}: {
  annotation: SavedAuthorityAnnotation;
}) {
  const decision = a.authority_decision_date
    ? formatLegalDate(a.authority_decision_date)
    : null;
  const courtTone =
    a.authority_forum_level === "supreme_court" ? "brand" : "neutral";
  return (
    <Card data-testid={`saved-research-row-${a.id}`}>
      <CardHeader className="min-w-0 items-stretch gap-3 sm:flex-row sm:items-start sm:justify-between sm:gap-4">
        <div className="flex w-full min-w-0 flex-col gap-1 sm:flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={courtTone}>{a.authority_court_name}</Badge>
            <Badge tone="neutral">{a.kind}</Badge>
            {a.is_archived ? <Badge tone="warning">Archived</Badge> : null}
          </div>
          <CardTitle className="truncate text-base">
            {a.authority_title}
          </CardTitle>
          <CardDescription className="text-xs text-[var(--color-ink-2)]">
            {[
              a.authority_neutral_citation,
              a.authority_case_reference,
              decision,
            ]
              .filter(Boolean)
              .join(" · ")}
          </CardDescription>
        </div>
        <SourceAction
          action={a.authority_source_action}
          compact
          originSurface="saved_research"
        />
      </CardHeader>
      <CardContent className="flex flex-col gap-2 text-sm">
        <p className="font-medium text-[var(--color-ink-1)]">{a.title}</p>
        {a.body ? (
          <p className="whitespace-pre-wrap text-[var(--color-ink-2)]">
            {a.body}
          </p>
        ) : null}
        <p className="text-xs text-[var(--color-ink-3)]">
          Source: {a.authority_source} · Saved {formatLegalDate(a.created_at)}
        </p>
      </CardContent>
    </Card>
  );
}
