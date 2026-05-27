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
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bell,
  BookOpenCheck,
  CheckCircle2,
  ExternalLink,
  Play,
  RefreshCw,
  XCircle,
} from "lucide-react";
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
import { Input } from "@/components/ui/Input";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import {
  createLegalUpdateWatchlist,
  fetchLegalUpdateDigestPreview,
  listLegalUpdateWatchlists,
  listLegalUpdates,
  listLegalUpdateSourceRecords,
  listStatutes,
  runLegalUpdateSourceSync,
  runLegalUpdateWatchlist,
  updateLegalUpdate,
  updateLegalUpdateWatchlist,
  type LegalUpdateRecord,
  type LegalUpdateRunResponse,
  type LegalUpdateSourceRecord,
  type LegalUpdateSourceRunRecord,
  type LegalUpdateWatchlistRecord,
} from "@/lib/api/endpoints";
import { useCapability } from "@/lib/capabilities";

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

      <LegalUpdatesPanel />

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

function LegalUpdatesPanel() {
  const queryClient = useQueryClient();
  const canRunSourceSync = useCapability("notifications:manage");
  const [name, setName] = useState("");
  const [terms, setTerms] = useState("");
  const [lastRun, setLastRun] = useState<LegalUpdateRunResponse | null>(null);
  const [lastSourceRun, setLastSourceRun] =
    useState<LegalUpdateSourceRunRecord | null>(null);

  const watchlists = useQuery({
    queryKey: ["statutes", "legal-updates", "watchlists"],
    queryFn: listLegalUpdateWatchlists,
    staleTime: 60_000,
  });
  const updates = useQuery({
    queryKey: ["statutes", "legal-updates", "records"],
    queryFn: () => listLegalUpdates({ limit: 8 }),
    staleTime: 30_000,
  });
  const digest = useQuery({
    queryKey: ["statutes", "legal-updates", "digest"],
    queryFn: () => fetchLegalUpdateDigestPreview(5),
    staleTime: 30_000,
  });
  const sourceRecords = useQuery({
    queryKey: ["statutes", "legal-updates", "source-records"],
    queryFn: () => listLegalUpdateSourceRecords({ limit: 6 }),
    staleTime: 60_000,
  });

  const createMutation = useMutation({
    mutationFn: createLegalUpdateWatchlist,
    onSuccess: () => {
      setName("");
      setTerms("");
      queryClient.invalidateQueries({ queryKey: ["statutes", "legal-updates"] });
    },
  });
  const runMutation = useMutation({
    mutationFn: runLegalUpdateWatchlist,
    onSuccess: (response) => {
      setLastRun(response);
      queryClient.invalidateQueries({ queryKey: ["statutes", "legal-updates"] });
    },
  });
  const archiveMutation = useMutation({
    mutationFn: (watchlistId: string) =>
      updateLegalUpdateWatchlist(watchlistId, { is_archived: true }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["statutes", "legal-updates"] });
    },
  });
  const updateMutation = useMutation({
    mutationFn: ({ updateId, action }: { updateId: string; action: "read" | "dismiss" }) =>
      updateLegalUpdate(updateId, action),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["statutes", "legal-updates"] });
    },
  });
  const sourceSyncMutation = useMutation({
    mutationFn: runLegalUpdateSourceSync,
    onSuccess: (response) => {
      setLastSourceRun(response);
      queryClient.invalidateQueries({ queryKey: ["statutes", "legal-updates"] });
    },
  });

  const termList = terms
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean)
    .slice(0, 8);
  const canCreate = name.trim().length > 0 && termList.length > 0;

  return (
    <Card data-testid="legal-update-center">
      <CardHeader>
        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <Bell className="h-4 w-4" aria-hidden />
              Legal updates
            </CardTitle>
            <CardDescription>
              Source-backed statutory monitoring with durable in-app delivery. External channels remain disabled.
            </CardDescription>
          </div>
          <div className="flex flex-wrap gap-2">
            <Badge tone="brand">PRS source</Badge>
            <Badge tone="neutral">In-app only</Badge>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <form
          className="grid gap-2 md:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)_auto]"
          onSubmit={(event) => {
            event.preventDefault();
            if (!canCreate || createMutation.isPending) return;
            createMutation.mutate({
              name: name.trim(),
              statute_terms: termList,
              update_types: [
                "act",
                "amendment",
                "ordinance",
                "notification",
                "repeal",
                "regulation",
                "circular",
                "order",
                "practice_direction",
              ],
            });
          }}
        >
          <Input
            aria-label="Watchlist name"
            data-testid="legal-update-name"
            placeholder="Watchlist name"
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
          <Input
            aria-label="Statute or section terms"
            data-testid="legal-update-terms"
            placeholder="Act or section terms"
            value={terms}
            onChange={(event) => setTerms(event.target.value)}
          />
          <Button
            type="submit"
            variant="secondary"
            disabled={!canCreate || createMutation.isPending}
            data-testid="legal-update-create"
          >
            Create
          </Button>
        </form>

        <div className="space-y-2">
          <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
            <div>
              <h2 className="text-sm font-semibold text-[var(--color-ink)]">
                Latest legal updates
              </h2>
              <p className="text-xs text-[var(--color-mute)]">
                Source-backed summaries for lawyer review. Delivery: In-app only.
              </p>
            </div>
            {canRunSourceSync ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() =>
                  sourceSyncMutation.mutate({
                    sourceKey: "prs_acts_parliament",
                    limit: 50,
                  })
                }
                disabled={sourceSyncMutation.isPending}
                data-testid="legal-update-source-sync"
                title="Run source sync"
              >
                <RefreshCw className="h-4 w-4" aria-hidden />
                Run source sync
              </Button>
            ) : null}
          </div>
          {sourceRecords.isLoading ? (
            <Skeleton className="h-24 w-full" />
          ) : sourceRecords.data?.records.length ? (
            <div
              className="divide-y divide-[var(--color-line)] rounded-md border border-[var(--color-line)]"
              data-testid="legal-update-source-records"
            >
              {sourceRecords.data.records.map((record) => (
                <SourceRecordRow key={record.id} record={record} />
              ))}
            </div>
          ) : (
            <p className="text-sm text-[var(--color-mute)]">
              No source-backed legal updates synced yet.
            </p>
          )}
          {lastSourceRun ? (
            <p
              className="text-xs text-[var(--color-mute)]"
              data-testid="legal-update-source-run-summary"
            >
              Source sync {lastSourceRun.status}: fetched {lastSourceRun.fetched_count}; created {lastSourceRun.created_count}; changed {lastSourceRun.changed_count}.
            </p>
          ) : null}
        </div>

        <div className="grid gap-4 lg:grid-cols-2">
          <div className="space-y-2">
            <h2 className="text-sm font-semibold text-[var(--color-ink)]">
              Watchlists
            </h2>
            {watchlists.isLoading ? (
              <Skeleton className="h-20 w-full" />
            ) : watchlists.data?.watchlists.length ? (
              <div className="divide-y divide-[var(--color-line)] rounded-md border border-[var(--color-line)]">
                {watchlists.data.watchlists.map((watchlist) => (
                  <WatchlistRow
                    key={watchlist.id}
                    watchlist={watchlist}
                    onRun={() =>
                      runMutation.mutate({
                        watchlistId: watchlist.id,
                        previewOnly: false,
                        limit: 20,
                      })
                    }
                    onArchive={() => archiveMutation.mutate(watchlist.id)}
                    busy={runMutation.isPending || archiveMutation.isPending}
                  />
                ))}
              </div>
            ) : (
              <p className="text-sm text-[var(--color-mute)]">
                No watchlists configured.
              </p>
            )}
            {lastRun ? (
              <p
                className="text-xs text-[var(--color-mute)]"
                data-testid="legal-update-run-summary"
              >
                Last run matched {lastRun.matched_count}; created {lastRun.created_count} in-app records.
              </p>
            ) : null}
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <h2 className="text-sm font-semibold text-[var(--color-ink)]">
                In-app records
              </h2>
              {digest.data ? (
                <span className="text-xs text-[var(--color-mute)]">
                  {digest.data.unread_count} unread
                </span>
              ) : null}
            </div>
            {updates.isLoading ? (
              <Skeleton className="h-24 w-full" />
            ) : updates.data?.updates.length ? (
              <div className="divide-y divide-[var(--color-line)] rounded-md border border-[var(--color-line)]">
                {updates.data.updates.map((update) => (
                  <UpdateRow
                    key={update.id}
                    update={update}
                    onRead={() =>
                      updateMutation.mutate({ updateId: update.id, action: "read" })
                    }
                    onDismiss={() =>
                      updateMutation.mutate({ updateId: update.id, action: "dismiss" })
                    }
                    busy={updateMutation.isPending}
                  />
                ))}
              </div>
            ) : (
              <p className="text-sm text-[var(--color-mute)]">
                No in-app legal updates yet.
              </p>
            )}
            {digest.data ? (
              <p
                className="text-xs text-[var(--color-mute)]"
                data-testid="legal-update-digest-note"
              >
                {digest.data.delivery_note}
              </p>
            ) : null}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function SourceRecordRow({ record }: { record: LegalUpdateSourceRecord }) {
  return (
    <div className="space-y-2 p-3">
      <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-[var(--color-ink)]">
            {record.title}
          </p>
          <div className="mt-1 flex flex-wrap gap-1.5">
            <Badge tone="brand">{record.update_type}</Badge>
            <Badge tone="neutral">{record.source_category ?? record.source_key}</Badge>
            <Badge tone="neutral">{record.provenance_status}</Badge>
            <Badge tone="neutral">In-app only</Badge>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {record.statute_id ? (
            <Link
              href={`/app/statutes/${record.statute_id}`}
              className="inline-flex items-center gap-1 rounded-md border border-[var(--color-line)] px-2 py-1 text-xs font-medium text-[var(--color-ink-2)] hover:bg-[var(--color-bg-2)]"
            >
              Amendment history
            </Link>
          ) : null}
          <a
            href={record.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 rounded-md border border-[var(--color-line)] px-2 py-1 text-xs font-medium text-[var(--color-ink-2)] hover:bg-[var(--color-bg-2)]"
          >
            Source
            <ExternalLink className="h-3 w-3" aria-hidden />
          </a>
        </div>
      </div>
      {record.summary ? (
        <div className="space-y-1 text-xs">
          <p className="font-medium text-[var(--color-ink)]">
            {record.summary.review_framing}
          </p>
          <p className="text-[var(--color-ink-2)]">
            {record.summary.plain_english_summary}
          </p>
          <p className="text-[var(--color-mute)]">
            Practical impact: {record.summary.practical_legal_impact}
          </p>
          <p className="text-[var(--color-mute)]">
            Confidence: {record.summary.confidence}
          </p>
        </div>
      ) : (
        <p className="text-xs text-[var(--color-mute)]">
          Summary {record.summary_status}; open the source record for review.
        </p>
      )}
    </div>
  );
}

function WatchlistRow({
  watchlist,
  onRun,
  onArchive,
  busy,
}: {
  watchlist: LegalUpdateWatchlistRecord;
  onRun: () => void;
  onArchive: () => void;
  busy: boolean;
}) {
  return (
    <div className="flex flex-col gap-2 p-3 md:flex-row md:items-center md:justify-between">
      <div className="min-w-0">
        <p className="truncate text-sm font-medium text-[var(--color-ink)]">
          {watchlist.name}
        </p>
        <p className="text-xs text-[var(--color-mute)]">
          {watchlist.statute_terms.length
            ? watchlist.statute_terms.join(", ")
            : "Bounded filters"}{" "}
          / {watchlist.update_types.join(", ")}
        </p>
      </div>
      <div className="flex gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={onRun}
          disabled={busy || watchlist.is_archived}
          data-testid={`legal-update-run-${watchlist.id}`}
          title="Run watchlist"
        >
          <Play className="h-4 w-4" aria-hidden />
          Run
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={onArchive}
          disabled={busy || watchlist.is_archived}
          title="Archive watchlist"
        >
          Archive
        </Button>
      </div>
    </div>
  );
}

function UpdateRow({
  update,
  onRead,
  onDismiss,
  busy,
}: {
  update: LegalUpdateRecord;
  onRead: () => void;
  onDismiss: () => void;
  busy: boolean;
}) {
  return (
    <div className="space-y-2 p-3">
      <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-[var(--color-ink)]">
            {update.title}
          </p>
          <p className="text-xs text-[var(--color-mute)]">
            {update.update_type} / {update.statute_name ?? update.source_key}
            {update.section_number ? ` / ${update.section_number}` : ""}
          </p>
        </div>
        <div className="flex gap-2">
          {update.statute_id ? (
            <Link
              href={`/app/statutes/${update.statute_id}`}
              className="inline-flex items-center gap-1 rounded-md border border-[var(--color-line)] px-2 py-1 text-xs font-medium text-[var(--color-ink-2)] hover:bg-[var(--color-bg-2)]"
            >
              Act
            </Link>
          ) : null}
          {update.source_url ? (
            <a
              href={update.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 rounded-md border border-[var(--color-line)] px-2 py-1 text-xs font-medium text-[var(--color-ink-2)] hover:bg-[var(--color-bg-2)]"
            >
              Source
              <ExternalLink className="h-3 w-3" aria-hidden />
            </a>
          ) : null}
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={onRead}
            disabled={busy || update.is_read}
            title="Mark read"
          >
            <CheckCircle2 className="h-4 w-4" aria-hidden />
            Read
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={onDismiss}
            disabled={busy || Boolean(update.dismissed_at)}
            title="Dismiss"
          >
            <XCircle className="h-4 w-4" aria-hidden />
            Dismiss
          </Button>
        </div>
      </div>
      <p className="text-xs text-[var(--color-ink-2)]">
        {update.relevance_explanation}
      </p>
      {update.snippet ? (
        <p className="text-xs text-[var(--color-mute)]">{update.snippet}</p>
      ) : null}
      {update.summary ? (
        <p className="text-xs text-[var(--color-ink-2)]">
          {update.summary.review_framing}: {update.summary.plain_english_summary}
        </p>
      ) : null}
      <p className="text-xs text-[var(--color-mute)]">
        {update.source_category} / {update.provenance_status}
      </p>
    </div>
  );
}
