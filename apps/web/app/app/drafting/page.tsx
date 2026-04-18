"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight, FileSignature } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Input";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { listMatters } from "@/lib/api/endpoints";

export default function DraftingHubPage() {
  const [filter, setFilter] = useState("");
  const mattersQuery = useQuery({
    queryKey: ["matters", "drafting-hub"],
    queryFn: () => listMatters({ limit: 200 }),
  });
  const matters = mattersQuery.data?.matters ?? [];
  const filtered = matters
    .filter((m) =>
      filter.trim().length === 0
        ? true
        : `${m.title} ${m.matter_code} ${m.practice_area ?? ""} ${m.client_name ?? ""}`
            .toLowerCase()
            .includes(filter.trim().toLowerCase()),
    )
    .sort((a, b) => (b.updated_at ?? "").localeCompare(a.updated_at ?? ""));

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Drafting"
        title="Drafting studio"
        description="Drafts live inside a matter so every version keeps its facts, authorities, and approvals. Pick the matter you want to draft on."
      />

      <Card>
        <CardHeader>
          <CardTitle as="h2" className="text-base">
            Recent matters
          </CardTitle>
          <CardDescription>
            Ordered by last update. Filter by title, matter code, client, or practice area.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <Input
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
            placeholder="Filter matters…"
            data-testid="drafting-hub-filter"
          />

          {mattersQuery.isPending ? (
            <div className="flex flex-col gap-3">
              {Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : mattersQuery.isError ? (
            <QueryErrorState
              title="Could not load matters"
              error={mattersQuery.error}
              onRetry={mattersQuery.refetch}
            />
          ) : filtered.length === 0 ? (
            <EmptyState
              icon={FileSignature}
              title="No matter matches"
              description={
                matters.length === 0
                  ? "Create a matter to start drafting. Every draft is anchored to a matter for citation lineage."
                  : "Clear the filter or check a different term."
              }
            />
          ) : (
            <ul className="divide-y divide-[var(--color-line-2)]">
              {filtered.map((matter) => (
                <li key={matter.id} className="py-3">
                  <Link
                    href={`/app/matters/${matter.id}/drafts`}
                    className="flex items-center justify-between gap-3 rounded-md px-2 py-1.5 transition-colors hover:bg-[var(--color-bg-2)]"
                    data-testid={`drafting-hub-open-${matter.matter_code}`}
                  >
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium text-[var(--color-ink)]">
                        {matter.title}
                      </div>
                      <div className="truncate text-xs text-[var(--color-mute)]">
                        {matter.matter_code}
                        {matter.practice_area ? ` · ${matter.practice_area}` : ""}
                        {matter.client_name ? ` · ${matter.client_name}` : ""}
                      </div>
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      <StatusBadge status={matter.status} />
                      <ArrowUpRight
                        className="h-4 w-4 text-[var(--color-mute)]"
                        aria-hidden
                      />
                    </div>
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
