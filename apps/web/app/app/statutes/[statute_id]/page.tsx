"use client";

/**
 * MOD-TS-017 Slice S2 (2026-04-25). One Act → list of its sections.
 *
 * Each section row shows section_number + section_label + a click-
 * through to the detail view. Section text isn't rendered here
 * (lazily fetched on the detail page) so this list stays compact.
 */
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, ExternalLink } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";

import { Badge } from "@/components/ui/Badge";
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
import { Skeleton } from "@/components/ui/Skeleton";
import {
  fetchStatuteAmendmentHistory,
  listStatuteSections,
} from "@/lib/api/endpoints";

export default function StatuteDetailPage() {
  const params = useParams<{ statute_id: string }>();
  const statuteId = params.statute_id;
  const query = useQuery({
    queryKey: ["statutes", statuteId, "sections"],
    queryFn: () => listStatuteSections(statuteId),
    enabled: Boolean(statuteId),
    staleTime: 30 * 60_000,
  });
  const history = useQuery({
    queryKey: ["statutes", statuteId, "amendment-history"],
    queryFn: () => fetchStatuteAmendmentHistory(statuteId),
    enabled: Boolean(statuteId),
    staleTime: 5 * 60_000,
  });

  if (query.isPending) {
    return (
      <div className="flex flex-col gap-3">
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }
  if (query.isError) {
    return (
      <QueryErrorState
        title="Could not load this Act"
        error={query.error}
        onRetry={() => query.refetch()}
      />
    );
  }
  const data = query.data;
  if (!data) return null;
  const { statute, sections } = data;

  return (
    <div className="flex flex-col gap-6">
      <Link
        href="/app/statutes"
        className="inline-flex items-center gap-1.5 text-xs font-medium text-[var(--color-mute)] hover:text-[var(--color-ink)]"
      >
        <ArrowLeft className="h-3.5 w-3.5" aria-hidden /> Back to all
        statutes
      </Link>

      <PageHeader
        eyebrow={statute.short_name}
        title={statute.long_name}
        description={
          statute.enacted_year
            ? `Enacted ${statute.enacted_year} · ${sections.length} independently verified sections available`
            : `${sections.length} independently verified sections available`
        }
        actions={
          statute.source_url ? (
            <a
              href={statute.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 rounded-md border border-[var(--color-line)] bg-white px-3 py-1.5 text-sm font-medium text-[var(--color-ink-2)] hover:bg-[var(--color-bg-2)]"
            >
              Act landing page
              <ExternalLink className="h-3.5 w-3.5" aria-hidden />
            </a>
          ) : undefined
        }
      />

      <Card data-testid="statute-amendment-history">
        <CardHeader>
          <CardTitle>Amendment history</CardTitle>
          <CardDescription>
            Source-backed legal update events and summaries for lawyer review.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {history.isLoading ? (
            <Skeleton className="h-20 w-full" />
          ) : history.isError ? (
            <p className="text-sm text-[var(--color-mute)]">
              Amendment history could not be loaded.
            </p>
          ) : history.data?.events.length ? (
            <ul className="divide-y divide-[var(--color-line-2)]">
              {history.data.events.map((event) => (
                <li key={event.id} className="space-y-2 py-3">
                  <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
                    <div>
                      <p className="text-sm font-medium text-[var(--color-ink)]">
                        {event.title}
                      </p>
                      <div className="mt-1 flex flex-wrap gap-1.5">
                        <Badge tone="brand">{event.change_type}</Badge>
                        <Badge tone="neutral">Source-backed</Badge>
                      </div>
                    </div>
                    <a
                      href={event.source_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 text-xs font-medium text-[var(--color-brand-600)] hover:underline"
                    >
                      Source
                      <ExternalLink className="h-3 w-3" aria-hidden />
                    </a>
                  </div>
                  {event.summary ? (
                    <p className="text-xs text-[var(--color-ink-2)]">
                      {event.summary}
                    </p>
                  ) : null}
                  {event.sections_changed.length ? (
                    <p className="text-xs text-[var(--color-mute)]">
                      Sections: {event.sections_changed.join(", ")}
                    </p>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState
              title="No amendment history yet"
              description="Run a legal update source sync to populate Act change events."
            />
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Sections</CardTitle>
          <CardDescription>
            Click a section for the bare text (when indexed) and recent
            authorities interpreting it.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {sections.length === 0 ? (
            <EmptyState
              title="No verified sections available"
              description="Catalog entries remain hidden until exact source provenance and independent legal review are complete."
            />
          ) : (
            <ul
              className="divide-y divide-[var(--color-line-2)]"
              data-testid="statute-sections-list"
            >
              {sections.map((s) => (
                <li
                  key={s.id}
                  className="py-2.5"
                  data-testid={`statute-section-${s.id}`}
                >
                  <Link
                    href={`/app/statutes/${statute.id}/sections/${encodeURIComponent(s.section_number)}`}
                    className="block hover:text-[var(--color-brand-600)]"
                  >
                    <div className="text-sm font-mono font-semibold text-[var(--color-ink)]">
                      {s.section_number}
                    </div>
                    {s.section_label ? (
                      <div className="text-xs text-[var(--color-mute)]">
                        {s.section_label}
                      </div>
                    ) : null}
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
