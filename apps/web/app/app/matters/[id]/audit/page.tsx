"use client";

import { useQuery } from "@tanstack/react-query";
import { Download, Filter, ScrollText } from "lucide-react";
import { useParams } from "next/navigation";
import { useMemo, useState } from "react";

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
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import {
  listMatterAuditEvents,
  matterAuditExportUrl,
  type MatterAuditFilters,
} from "@/lib/api/endpoints";
import type { MatterAuditEvent } from "@/lib/api/schemas";
import { useCapability } from "@/lib/capabilities";

function formatDateTime(value: string): string {
  try {
    return new Date(value).toLocaleString(undefined, {
      day: "2-digit",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return value;
  }
}

function metadataPreview(event: MatterAuditEvent): string | null {
  const metadata = event.metadata ?? {};
  const entries = Object.entries(metadata).filter(([, value]) => value != null);
  if (entries.length === 0) return null;
  return entries
    .slice(0, 4)
    .map(([key, value]) => `${key}: ${String(value)}`)
    .join(" | ");
}

export default function MatterAuditPage() {
  const params = useParams<{ id: string }>();
  const matterId = params.id;
  const canExport = useCapability("audit:export");
  const [filters, setFilters] = useState<MatterAuditFilters>({
    limit: 50,
    offset: 0,
  });

  const cleanFilters = useMemo(
    () => ({
      ...filters,
      limit: filters.limit ?? 50,
      offset: filters.offset ?? 0,
    }),
    [filters],
  );

  const query = useQuery({
    queryKey: ["matters", matterId, "audit-events", cleanFilters],
    queryFn: () => listMatterAuditEvents(matterId, cleanFilters),
    enabled: Boolean(matterId),
  });

  const updateFilter = (key: keyof MatterAuditFilters, value: string) => {
    const normalized =
      key === "since" && value
        ? `${value}T00:00:00Z`
        : key === "until" && value
          ? `${value}T23:59:59Z`
          : value || undefined;
    setFilters((current) => ({
      ...current,
      [key]: normalized,
      offset: 0,
    }));
  };

  const exportJsonl = matterAuditExportUrl(matterId, {
    ...cleanFilters,
    format: "jsonl",
  });
  const exportCsv = matterAuditExportUrl(matterId, {
    ...cleanFilters,
    format: "csv",
  });

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader className="flex-row items-start justify-between gap-4">
          <div>
            <CardTitle>Matter audit</CardTitle>
            <CardDescription>
              AuditEvent-backed history scoped to this matter and your matter visibility.
            </CardDescription>
          </div>
          {canExport ? (
            <div className="flex flex-wrap gap-2">
              <Button
                href={exportJsonl}
                size="sm"
                variant="outline"
                data-testid="matter-audit-export-jsonl"
              >
                <Download className="h-4 w-4" aria-hidden />
                JSONL
              </Button>
              <Button
                href={exportCsv}
                size="sm"
                variant="outline"
                data-testid="matter-audit-export-csv"
              >
                <Download className="h-4 w-4" aria-hidden />
                CSV
              </Button>
            </div>
          ) : null}
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-5">
          <div className="space-y-1.5">
            <Label htmlFor="audit-since">From</Label>
            <Input
              id="audit-since"
              type="date"
              data-testid="audit-filter-since"
              onChange={(event) => updateFilter("since", event.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="audit-until">To</Label>
            <Input
              id="audit-until"
              type="date"
              data-testid="audit-filter-until"
              onChange={(event) => updateFilter("until", event.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="audit-actor">Actor</Label>
            <Input
              id="audit-actor"
              data-testid="audit-filter-actor"
              placeholder="Name or membership ID"
              onChange={(event) => updateFilter("actor", event.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="audit-action">Action</Label>
            <Input
              id="audit-action"
              data-testid="audit-filter-action"
              placeholder="matter.updated"
              onChange={(event) => updateFilter("action", event.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="audit-keyword">Search</Label>
            <Input
              id="audit-keyword"
              data-testid="audit-filter-keyword"
              placeholder="Keyword"
              onChange={(event) => updateFilter("keyword", event.target.value)}
            />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex-row items-center justify-between gap-4">
          <div>
            <CardTitle className="flex items-center gap-2">
              <Filter className="h-4 w-4" aria-hidden />
              Events
            </CardTitle>
            <CardDescription>
              {query.data ? `${query.data.total} matching event(s)` : "Filtered audit rows"}
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          {query.isPending ? (
            <Skeleton className="h-44 w-full" data-testid="audit-loading" />
          ) : query.isError ? (
            <QueryErrorState
              title="Could not load audit events"
              error={query.error}
              onRetry={() => query.refetch()}
            />
          ) : query.data.events.length === 0 ? (
            <EmptyState
              icon={ScrollText}
              title="No audit events match"
              description="Adjust the filters or export from the admin audit console for broader history."
            />
          ) : (
            <ol className="flex flex-col divide-y divide-[var(--color-line)]">
              {query.data.events.map((event) => {
                const preview = metadataPreview(event);
                return (
                  <li
                    key={event.id}
                    className="grid gap-2 py-3 text-sm md:grid-cols-[minmax(0,1fr)_12rem]"
                    data-testid="matter-audit-row"
                  >
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-semibold text-[var(--color-ink)]">
                          {event.action}
                        </span>
                        <Badge tone="neutral">{event.result}</Badge>
                        <span className="text-xs text-[var(--color-mute-2)]">
                          {event.target_type}
                          {event.target_id ? `:${event.target_id}` : ""}
                        </span>
                      </div>
                      {preview ? (
                        <p className="mt-1 truncate text-xs text-[var(--color-mute)]">
                          {preview}
                        </p>
                      ) : null}
                      <p className="mt-1 text-xs text-[var(--color-mute-2)]">
                        {event.actor_label ?? "system"}
                        {event.actor_membership_id ? ` | ${event.actor_membership_id}` : ""}
                      </p>
                    </div>
                    <time className="text-xs text-[var(--color-mute-2)] md:text-right">
                      {formatDateTime(event.created_at)}
                    </time>
                  </li>
                );
              })}
            </ol>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
