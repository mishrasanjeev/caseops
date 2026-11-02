"use client";

import { keepPreviousData, useInfiniteQuery } from "@tanstack/react-query";
import { ArrowUpRight, type LucideIcon } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { listMatters } from "@/lib/api/endpoints";
import type { Matter } from "@/lib/api/schemas";

const SEARCH_DEBOUNCE_MS = 300;
const PAGE_SIZE = 50;

/**
 * Every Matter the user can see, to open one in a module (drafting,
 * recommendations). The hubs used to read one page of 200 and filter it in
 * the browser, so older Matters silently disappeared (B4-ADJ-03). This list
 * searches on the server (`q`: code, title, client, parties, case numbers),
 * pages by cursor, and says when more Matters exist than are shown.
 */
export function MatterHubList({
  scope,
  hrefFor,
  testIdPrefix,
  emptyIcon,
  noMattersText,
}: {
  /** Distinguishes this hub's cache entry. */
  scope: string;
  hrefFor: (matter: Matter) => string;
  testIdPrefix: string;
  emptyIcon: LucideIcon;
  noMattersText: string;
}) {
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  useEffect(() => {
    const handle = window.setTimeout(() => setQuery(search.trim()), SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(handle);
  }, [search]);

  const results = useInfiniteQuery({
    queryKey: ["matters", scope, { query }],
    queryFn: ({ pageParam }) =>
      listMatters({ q: query || undefined, cursor: pageParam ?? undefined, limit: PAGE_SIZE }),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor ?? null,
    placeholderData: keepPreviousData,
  });
  const matters = useMemo(() => {
    const seen = new Map<string, Matter>();
    for (const page of results.data?.pages ?? []) for (const matter of page.matters) seen.set(matter.id, matter);
    return [...seen.values()];
  }, [results.data]);
  const hasMore = Boolean(results.hasNextPage);
  const searching = results.isPlaceholderData || search.trim() !== query;
  const searchId = `${testIdPrefix}-search`;

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <div className="flex min-w-0 flex-col gap-1.5">
        <Label htmlFor={searchId}>Search matters</Label>
        <Input
          id={searchId}
          type="search"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Matter code, title, client or case number"
          data-testid={`${testIdPrefix}-filter`}
        />
      </div>

      {results.isPending ? (
        <div className="flex flex-col gap-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </div>
      ) : results.isError && !results.isFetchNextPageError ? (
        <QueryErrorState title="Could not load matters" error={results.error} onRetry={() => results.refetch()} />
      ) : matters.length === 0 ? (
        <EmptyState
          icon={emptyIcon}
          title={query ? "No matter matches" : "No matters yet"}
          description={
            query
              ? `No matter you can see matches “${query}”. Search by matter code, title, client or case number.`
              : noMattersText
          }
        />
      ) : (
        <>
          <ul className="divide-y divide-[var(--color-line-2)]">
            {matters.map((matter) => (
              <li key={matter.id} className="py-3">
                <Link
                  href={hrefFor(matter)}
                  className="flex min-w-0 items-center justify-between gap-3 rounded-md px-2 py-1.5 transition-colors hover:bg-[var(--color-bg-2)]"
                  data-testid={`${testIdPrefix}-open-${matter.matter_code}`}
                >
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium text-[var(--color-ink)]">{matter.title}</div>
                    <div className="truncate text-xs text-[var(--color-mute)]">
                      {matter.matter_code}
                      {matter.practice_area ? ` · ${matter.practice_area}` : ""}
                      {matter.client_name ? ` · ${matter.client_name}` : ""}
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    <StatusBadge status={matter.status} />
                    <ArrowUpRight className="h-4 w-4 text-[var(--color-mute)]" aria-hidden />
                  </div>
                </Link>
              </li>
            ))}
          </ul>
          <div className="flex min-w-0 flex-wrap items-center gap-2 text-sm text-[var(--color-mute)]">
            <span role="status" className="min-w-0 break-words" data-testid={`${testIdPrefix}-count`}>
              {searching
                ? "Searching matters…"
                : hasMore
                  ? `Showing the ${matters.length} most recently updated matters${query ? ` matching “${query}”` : ""}. Search, or load more.`
                  : `${matters.length} ${matters.length === 1 ? "matter" : "matters"}${query ? ` matching “${query}”` : ""}.`}
            </span>
            {hasMore && !searching ? (
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={results.isFetchingNextPage}
                onClick={() => results.fetchNextPage()}
              >
                {results.isFetchingNextPage ? "Loading…" : "Load more matters"}
              </Button>
            ) : null}
            {results.isFetchNextPageError ? (
              <span role="alert" className="flex min-w-0 flex-wrap items-center gap-2 text-[var(--color-danger-500)]">
                <span className="min-w-0 break-words">More matters could not be loaded.</span>
                <Button type="button" size="sm" variant="outline" onClick={() => results.fetchNextPage()}>
                  Retry
                </Button>
              </span>
            ) : null}
          </div>
        </>
      )}
    </div>
  );
}
