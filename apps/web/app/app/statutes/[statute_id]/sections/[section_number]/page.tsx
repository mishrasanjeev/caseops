"use client";

/**
 * MOD-TS-017 Slice S2 (2026-04-25). One section's bare text +
 * parent/children cross-refs.
 *
 * v1: section_text is nullable (Slice S3 backfill populates it from
 * the source). When NULL, render an empty state pointing at the
 * source URL so the lawyer can verify the bare text directly.
 */
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, ExternalLink, FileText } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";

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
import { fetchStatuteSection } from "@/lib/api/endpoints";

export default function StatuteSectionDetailPage() {
  const params = useParams<{
    statute_id: string;
    section_number: string;
  }>();
  const statuteId = params.statute_id;
  const sectionNumber = decodeURIComponent(params.section_number);

  const query = useQuery({
    queryKey: ["statutes", statuteId, "section", sectionNumber],
    queryFn: () => fetchStatuteSection(statuteId, sectionNumber),
    enabled: Boolean(statuteId && sectionNumber),
    staleTime: 30 * 60_000,
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
        title="Could not load this section"
        error={query.error}
        onRetry={() => query.refetch()}
      />
    );
  }
  const data = query.data;
  if (!data) return null;
  const { statute, section, parent_section, child_sections } = data;

  return (
    <div className="flex flex-col gap-6">
      <Link
        href={`/app/statutes/${statute.id}`}
        className="inline-flex items-center gap-1.5 text-xs font-medium text-[var(--color-mute)] hover:text-[var(--color-ink)]"
      >
        <ArrowLeft className="h-3.5 w-3.5" aria-hidden /> Back to{" "}
        {statute.short_name}
      </Link>

      <PageHeader
        eyebrow={`${statute.short_name} · ${statute.long_name}`}
        title={section.section_number}
        description={section.section_label ?? "Section of the Act"}
        actions={
          section.section_url ? (
            <a
              href={section.section_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 rounded-md border border-[var(--color-line)] bg-white px-3 py-1.5 text-sm font-medium text-[var(--color-ink-2)] hover:bg-[var(--color-bg-2)]"
            >
              indiacode.nic.in
              <ExternalLink className="h-3.5 w-3.5" aria-hidden />
            </a>
          ) : undefined
        }
      />

      <Card data-testid="statute-section-text-card">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <FileText className="h-4 w-4" aria-hidden /> Bare text
          </CardTitle>
          <CardDescription>
            Sourced from indiacode.nic.in (Government of India, public
            domain). Verify at the source link above.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {section.section_text ? (
            <pre
              className="whitespace-pre-wrap text-sm text-[var(--color-ink)]"
              data-testid="statute-section-text"
            >
              {section.section_text}
            </pre>
          ) : (
            <EmptyState
              icon={FileText}
              title="Bare text not yet indexed"
              description={
                section.section_url
                  ? `Section number + label are indexed but the bare text hasn't been fetched yet. The source URL above takes you to the official indiacode.nic.in page for ${section.section_number}.`
                  : "Bare text indexing is pending for this section. Slice S3 will populate it."
              }
            />
          )}
        </CardContent>
      </Card>

      {parent_section ? (
        <Card>
          <CardHeader>
            <CardTitle>Parent section</CardTitle>
          </CardHeader>
          <CardContent>
            <Link
              href={`/app/statutes/${statute.id}/sections/${encodeURIComponent(parent_section.section_number)}`}
              className="block hover:text-[var(--color-brand-600)] hover:underline"
            >
              <div className="font-mono text-sm font-semibold">
                {parent_section.section_number}
              </div>
              {parent_section.section_label ? (
                <div className="text-xs text-[var(--color-mute)]">
                  {parent_section.section_label}
                </div>
              ) : null}
            </Link>
          </CardContent>
        </Card>
      ) : null}

      {child_sections.length > 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>Sub-sections</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="divide-y divide-[var(--color-line-2)]">
              {child_sections.map((c) => (
                <li key={c.id} className="py-2.5">
                  <Link
                    href={`/app/statutes/${statute.id}/sections/${encodeURIComponent(c.section_number)}`}
                    className="block hover:text-[var(--color-brand-600)]"
                  >
                    <div className="font-mono text-sm font-semibold">
                      {c.section_number}
                    </div>
                    {c.section_label ? (
                      <div className="text-xs text-[var(--color-mute)]">
                        {c.section_label}
                      </div>
                    ) : null}
                  </Link>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
