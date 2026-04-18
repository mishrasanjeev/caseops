"use client";

import { useQuery } from "@tanstack/react-query";
import { Gavel } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

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
import { listCourts } from "@/lib/api/endpoints";

const FORUM_LABEL: Record<string, string> = {
  supreme_court: "Supreme Court",
  high_court: "High Court",
  lower_court: "Lower court",
  tribunal: "Tribunal",
};

export default function CourtsIndexPage() {
  const [filter, setFilter] = useState("");
  const courtsQuery = useQuery({
    queryKey: ["courts", "list"],
    queryFn: () => listCourts(),
    staleTime: 10 * 60 * 1000,
  });

  const filtered = useMemo(() => {
    const courts = courtsQuery.data?.courts ?? [];
    const needle = filter.trim().toLowerCase();
    if (needle.length === 0) return courts;
    return courts.filter((court) =>
      `${court.name} ${court.short_name} ${court.jurisdiction ?? ""} ${court.seat_city ?? ""}`
        .toLowerCase()
        .includes(needle),
    );
  }, [courtsQuery.data, filter]);

  const grouped = useMemo(() => {
    const bucket = new Map<string, typeof filtered>();
    for (const court of filtered) {
      const list = bucket.get(court.forum_level) ?? [];
      list.push(court);
      bucket.set(court.forum_level, list);
    }
    const order = ["supreme_court", "high_court", "tribunal", "lower_court"];
    return order
      .map((k) => [k, bucket.get(k) ?? []] as const)
      .filter(([, items]) => items.length > 0);
  }, [filtered]);

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Courts"
        title="Court directory"
        description="Every court the catalog knows about, grouped by forum. Open a court for its judges, recent authorities, and your portfolio exposure there."
      />

      <Input
        value={filter}
        onChange={(event) => setFilter(event.target.value)}
        placeholder="Filter by name, city, or jurisdiction…"
        data-testid="courts-filter"
      />

      {courtsQuery.isPending ? (
        <Skeleton className="h-64 w-full" />
      ) : courtsQuery.isError ? (
        <QueryErrorState
          title="Could not load courts"
          error={courtsQuery.error}
          onRetry={courtsQuery.refetch}
        />
      ) : grouped.length === 0 ? (
        <EmptyState
          icon={Gavel}
          title="No matches"
          description="Clear the filter or try a different search term."
        />
      ) : (
        <div className="flex flex-col gap-5">
          {grouped.map(([forum, courts]) => (
            <Card key={forum}>
              <CardHeader>
                <CardTitle as="h2" className="text-base">
                  {FORUM_LABEL[forum] ?? forum.replace(/_/g, " ")} ({courts.length})
                </CardTitle>
                <CardDescription>
                  {forum === "supreme_court"
                    ? "Apex court of India."
                    : forum === "high_court"
                      ? "Constitutional courts at the state level."
                      : forum === "tribunal"
                        ? "Specialised forums."
                        : "Lower / subordinate courts."}
                </CardDescription>
              </CardHeader>
              <CardContent>
                <ul className="grid gap-2 md:grid-cols-2">
                  {courts.map((court) => (
                    <li key={court.id}>
                      <Link
                        href={`/app/courts/${court.id}`}
                        className="flex items-center justify-between gap-3 rounded-md border border-[var(--color-line)] px-3 py-2 transition-colors hover:bg-[var(--color-bg-2)]"
                      >
                        <div>
                          <div className="text-sm font-semibold text-[var(--color-ink)]">
                            {court.name}
                          </div>
                          <div className="text-xs text-[var(--color-mute)]">
                            {court.seat_city ?? court.jurisdiction ?? court.short_name}
                          </div>
                        </div>
                        <span className="text-xs font-mono text-[var(--color-mute)]">
                          {court.short_name}
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
