"use client";

/**
 * MOD-TS-017 Slice S2 (2026-04-25). Bare-acts browser index.
 *
 * Lists every Act in the catalog as a tile with section count +
 * source-URL link. Click a tile to drill into the section list.
 *
 * v1 surfaces 7 central acts seeded by `caseops-seed-statutes`
 * Cloud Run Job. State acts + amendment history are explicitly
 * out of v1 (see docs/PRD_STATUTE_MODEL_2026-04-25.md §2).
 */
import { useQuery } from "@tanstack/react-query";
import { BookOpenCheck, ExternalLink } from "lucide-react";
import Link from "next/link";

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
import { listStatutes } from "@/lib/api/endpoints";

export default function StatutesIndexPage() {
  const query = useQuery({
    queryKey: ["statutes", "list"],
    queryFn: listStatutes,
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
        title="Could not load statutes"
        error={query.error}
        onRetry={() => query.refetch()}
      />
    );
  }
  const data = query.data;
  if (!data) return null;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Statutes"
        title="Bare Acts"
        description={
          `Indian central Acts with structured section catalogs. ` +
          `${data.statutes.length} acts · ${data.total_section_count} ` +
          `sections indexed. All bare text sourced from indiacode.nic.in ` +
          `(Government of India, public domain).`
        }
      />

      {data.statutes.length === 0 ? (
        <EmptyState
          icon={BookOpenCheck}
          title="No statutes seeded yet"
          description="Run the caseops-seed-statutes Cloud Run Job to load the v1 central-acts catalog."
        />
      ) : (
        <ul
          className="grid gap-3 md:grid-cols-2 xl:grid-cols-3"
          data-testid="statutes-grid"
        >
          {data.statutes.map((s) => (
            <li key={s.id}>
              <Card data-testid={`statute-tile-${s.id}`}>
                <CardHeader>
                  <CardTitle className="flex items-baseline justify-between gap-2 text-base">
                    <Link
                      href={`/app/statutes/${s.id}`}
                      className="hover:text-[var(--color-brand-600)] hover:underline"
                    >
                      {s.short_name}
                    </Link>
                    <span className="text-xs font-mono text-[var(--color-mute)]">
                      {s.section_count} sections
                    </span>
                  </CardTitle>
                  <CardDescription>
                    {s.long_name}
                    {s.enacted_year ? ` · enacted ${s.enacted_year}` : null}
                  </CardDescription>
                </CardHeader>
                <CardContent className="flex items-center justify-between text-xs text-[var(--color-mute)]">
                  <Link
                    href={`/app/statutes/${s.id}`}
                    className="font-medium text-[var(--color-brand-600)] hover:underline"
                  >
                    Browse sections →
                  </Link>
                  {s.source_url ? (
                    <a
                      href={s.source_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 hover:text-[var(--color-ink)]"
                    >
                      indiacode.nic.in
                      <ExternalLink className="h-3 w-3" aria-hidden />
                    </a>
                  ) : null}
                </CardContent>
              </Card>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
