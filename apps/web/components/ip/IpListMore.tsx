"use client";

import { Button } from "@/components/ui/Button";

/**
 * Footer for an offset-paged IP list: states how many of the server's rows are
 * shown and reads the next page on request, so older records stay reachable.
 */
export function IpListMore({
  shown,
  total,
  noun,
  hasMore,
  loading,
  failed,
  onMore,
}: {
  shown: number;
  total: number;
  noun: string;
  hasMore: boolean;
  loading: boolean;
  failed: boolean;
  onMore: () => void;
}) {
  if (!total) return null;
  return (
    <div className="flex min-w-0 flex-wrap items-center justify-between gap-2 px-1 py-2 text-sm text-[var(--color-mute)]">
      <span role="status">Showing {shown} of {total} {noun}</span>
      {hasMore ? (
        <Button type="button" size="sm" variant="outline" disabled={loading} onClick={onMore}>
          {loading ? "Loading…" : `Load more ${noun}`}
        </Button>
      ) : null}
      {failed ? (
        <span role="alert" className="w-full text-[var(--color-danger-500)]">
          Could not load more {noun}. Try Load more again.
        </span>
      ) : null}
    </div>
  );
}
