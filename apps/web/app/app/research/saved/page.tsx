"use client";

import { useQuery } from "@tanstack/react-query";
import { Bookmark, ExternalLink, Loader2 } from "lucide-react";
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
import {
  fetchSavedAuthorityAnnotations,
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
      <CardHeader className="flex flex-row items-start justify-between gap-4">
        <div className="flex min-w-0 flex-col gap-1">
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
        <Link href={`/app/research?q=${encodeURIComponent(a.authority_title)}`}>
          <Button variant="outline" size="sm">
            <ExternalLink className="mr-1 h-3.5 w-3.5" />
            Open
          </Button>
        </Link>
      </CardHeader>
      <CardContent className="flex flex-col gap-2 text-sm">
        <p className="font-medium text-[var(--color-ink-1)]">{a.title}</p>
        {a.body ? (
          <p className="whitespace-pre-wrap text-[var(--color-ink-2)]">
            {a.body}
          </p>
        ) : null}
        <p className="text-xs text-[var(--color-ink-3)]">
          Saved {formatLegalDate(a.created_at)}
        </p>
      </CardContent>
    </Card>
  );
}
