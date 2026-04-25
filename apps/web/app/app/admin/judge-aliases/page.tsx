"use client";

/**
 * Slice D admin surface (MOD-TS-001-E, 2026-04-25 follow-up).
 *
 * Read-only listing of every judge alias the catalog has, grouped by
 * (court_short_name, judge_full_name). Lets a workspace admin audit
 * the matcher's behaviour without DB access — useful when a bench
 * resolution unexpectedly fails or matches the wrong judge.
 *
 * v1 is read-only. Add / remove alias is a separate scope (would
 * need POST/DELETE endpoints + admin role gate); flag the gap in the
 * empty state copy.
 */
import { useQuery } from "@tanstack/react-query";
import { Languages } from "lucide-react";
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
import { listJudgeAliases, type JudgeAliasRecord } from "@/lib/api/endpoints";

export default function JudgeAliasesAdminPage() {
  const query = useQuery({
    queryKey: ["admin", "judge-aliases"],
    queryFn: listJudgeAliases,
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
        title="Could not load judge aliases"
        error={query.error}
        onRetry={() => query.refetch()}
      />
    );
  }
  const data = query.data;
  if (!data) return null;

  // Group rows by judge for display.
  const grouped = new Map<string, JudgeAliasRecord[]>();
  for (const a of data.aliases) {
    const key = `${a.court_short_name}\u2003${a.judge_full_name}`;
    const list = grouped.get(key) ?? [];
    list.push(a);
    grouped.set(key, list);
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Admin"
        title="Judge aliases"
        description={
          `Every alternative spelling the resolver knows for each ` +
          `judge in the catalog. Used by the bench-name resolver ` +
          `(/app/matters → hearings) and bench-aware appeal drafting. ` +
          `${data.alias_count} aliases across ${data.judge_count} judges.`
        }
      />

      {grouped.size === 0 ? (
        <EmptyState
          icon={Languages}
          title="No aliases recorded yet"
          description="Run the backfill-judge-aliases Cloud Run Job to seed canonical aliases for the current judges catalog."
        />
      ) : (
        <ul
          className="flex flex-col gap-3"
          data-testid="judge-aliases-list"
        >
          {Array.from(grouped.entries()).map(([key, aliases]) => {
            const first = aliases[0];
            return (
              <Card key={key} data-testid={`judge-aliases-card-${first.judge_id}`}>
                <CardHeader>
                  <CardTitle className="flex items-baseline justify-between gap-3 text-base">
                    <Link
                      href={`/app/courts/judges/${first.judge_id}`}
                      className="hover:text-[var(--color-brand-600)] hover:underline"
                    >
                      {first.judge_full_name}
                    </Link>
                    <span className="text-xs font-mono text-[var(--color-mute)]">
                      {first.court_short_name}
                    </span>
                  </CardTitle>
                  <CardDescription>
                    {aliases.length} aliases · sources:{" "}
                    {Array.from(new Set(aliases.map((a) => a.source))).join(", ")}
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <ul className="flex flex-wrap gap-1.5">
                    {aliases.map((a) => (
                      <li
                        key={a.id}
                        className="rounded-md border border-[var(--color-line)] bg-white px-2 py-1 text-xs"
                        title={`source: ${a.source}`}
                      >
                        <span className="text-[var(--color-ink-2)]">
                          {a.alias_text}
                        </span>
                        <span className="ml-1.5 text-[10px] text-[var(--color-mute-2)]">
                          ({a.source})
                        </span>
                      </li>
                    ))}
                  </ul>
                </CardContent>
              </Card>
            );
          })}
        </ul>
      )}
    </div>
  );
}
