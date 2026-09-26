"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Archive,
  Bell,
  BellOff,
  Bookmark,
  ExternalLink,
  Link2,
  RefreshCw,
  Search,
} from "lucide-react";
import { useSearchParams } from "next/navigation";
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
import { API_BASE_URL, apiErrorMessage } from "@/lib/api/config";
import {
  createCaseTrackingBookmark,
  fetchCaseTrackingSupportMatrix,
  fetchCaseTrackingStatus,
  listCaseTrackingBookmarks,
  listCaseTrackingUpdates,
  refreshCaseTrackingBookmark,
  searchTrackedCases,
  updateCaseTrackingBookmark,
  type CaseTrackingBookmarkRecord,
  type CaseTrackingSearchInput,
  type CaseTrackingUpdateRecord,
} from "@/lib/api/endpoints";
import {
  linkMatterCase,
  resolveMatterCase,
  searchMatterCases,
  type MatterAwareSearchResponse,
  type MatterAwareSearchResult,
} from "@/lib/api/case-tracking-matter-resolution";

export default function CaseTrackingPage() {
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const matterId = searchParams.get("matterId");
  const [query, setQuery] = useState(searchParams.get("query") ?? "");
  const [cnr, setCnr] = useState(searchParams.get("cnr") ?? "");
  const [caseNumber, setCaseNumber] = useState(searchParams.get("caseNumber") ?? "");
  const [courtCode, setCourtCode] = useState(searchParams.get("courtCode") ?? "");
  const initialCourtName = searchParams.get("court");
  const [selectedBookmarkId, setSelectedBookmarkId] = useState<string | null>(null);
  const [linkedCandidateToken, setLinkedCandidateToken] = useState<string | null>(null);

  const status = useQuery({
    queryKey: ["case-tracking", "status"],
    queryFn: fetchCaseTrackingStatus,
    staleTime: 60_000,
  });
  const bookmarks = useQuery({
    queryKey: ["case-tracking", "bookmarks"],
    queryFn: listCaseTrackingBookmarks,
    staleTime: 30_000,
  });
  const updates = useQuery({
    queryKey: ["case-tracking", "updates", selectedBookmarkId],
    queryFn: () => listCaseTrackingUpdates(selectedBookmarkId as string),
    enabled: Boolean(selectedBookmarkId),
    staleTime: 30_000,
  });
  const supportMatrix = useQuery({
    queryKey: ["case-tracking", "support-matrix"],
    queryFn: fetchCaseTrackingSupportMatrix,
    staleTime: 300_000,
  });

  const searchMutation = useMutation({
    mutationFn: (input: CaseTrackingSearchInput): Promise<MatterAwareSearchResponse> =>
      matterId ? searchMatterCases({ matterId, input }) : searchTrackedCases(input),
  });
  const matterResolution = useMutation({
    mutationFn: resolveMatterCase,
    onMutate: () => {
      setLinkedCandidateToken(null);
      matterLink.reset();
    },
  });
  const matterLink = useMutation({
    mutationFn: linkMatterCase,
    onSuccess: (bookmark, selection) => {
      setLinkedCandidateToken(selection.linkToken);
      setSelectedBookmarkId(bookmark.id);
      queryClient.invalidateQueries({ queryKey: ["case-tracking", "bookmarks"] });
    },
  });
  const bookmarkMutation = useMutation({
    mutationFn: createCaseTrackingBookmark,
    onSuccess: (bookmark) => {
      setSelectedBookmarkId(bookmark.id);
      queryClient.invalidateQueries({ queryKey: ["case-tracking", "bookmarks"] });
    },
  });
  const refreshMutation = useMutation({
    mutationFn: refreshCaseTrackingBookmark,
    onSuccess: async (response) => {
      setSelectedBookmarkId(response.bookmark.id);
      await queryClient.cancelQueries({ queryKey: ["matters"] });
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["case-tracking"] }),
        queryClient.invalidateQueries({ queryKey: ["matters"] }),
      ]);
    },
    // A failed refresh still records provider health, the error and the
    // recovery window on the tracked case; reload it so the row is not stale.
    onError: () => queryClient.invalidateQueries({ queryKey: ["case-tracking"] }),
  });
  const updateMutation = useMutation({
    mutationFn: ({
      bookmarkId,
      input,
    }: {
      bookmarkId: string;
      input: { notification_enabled?: boolean; is_archived?: boolean };
    }) => updateCaseTrackingBookmark(bookmarkId, input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["case-tracking"] });
    },
  });

  const configured = Boolean(status.data?.enabled && status.data.configured);
  const hasSearchInput = Boolean(query.trim() || cnr.trim() || caseNumber.trim());
  const canSearch = configured && hasSearchInput;

  if (status.isPending || bookmarks.isPending) {
    return (
      <div className="flex flex-col gap-3">
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }
  if (status.isError) {
    return (
      <QueryErrorState
        title="Could not load case tracking"
        error={status.error}
        onRetry={() => status.refetch()}
      />
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Case tracking"
        title="CNR and case-number tracking"
        description="Bookmark provider-normalized court cases and receive durable in-app notifications when orders, judgments, hearings, or status change."
      />

      {!configured ? (
        <Card data-testid="case-tracking-disabled">
          <CardHeader>
            <CardTitle>Provider configuration required</CardTitle>
            <CardDescription>
              {status.data?.reason ??
                "Enable case tracking and configure the provider token to search court cases."}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Badge tone="neutral">No provider calls made</Badge>
          </CardContent>
        </Card>
      ) : null}

      {status.data?.scheduled_sync_eligible !== undefined ? (
        <section aria-label="Scheduled hearing updates" className="space-y-2 border-y border-[var(--color-line)] py-3">
          <p className="text-sm font-medium">
            Scheduled hearing updates: {status.data.scheduled_sync_local_time}{status.data.scheduled_sync_window_end_local_time ? `-${status.data.scheduled_sync_window_end_local_time}` : ""} ({status.data.scheduled_sync_timezone})
          </p>
          <p className="text-sm text-[var(--color-ink-2)]">
            {status.data.scheduled_sync_eligible
              ? "Eligible for scheduled updates from uniquely matched court records."
              : status.data.scheduled_sync_disabled_reason === "configured_test_tenant" || status.data.scheduled_sync_disabled_reason === "synthetic_test_tenant"
                ? "Scheduled paid updates are excluded for this test workspace. Human-initiated search and refresh remain available within the workspace budget."
                : "Scheduled updates are unavailable until the provider is enabled and configured."}
          </p>
        </section>
      ) : null}

      {matterId || initialCourtName ? (
        <Card data-testid="matter-case-resolution">
          <CardHeader>
            <CardTitle as="h2" className="text-base">Find this Matter on eCourts</CardTitle>
            <CardDescription>
              {initialCourtName
                ? `${initialCourtName}. CaseOps checks the saved Matter identifiers before showing a match.`
                : "CaseOps checks the saved Matter identifiers before showing a match."}
            </CardDescription>
          </CardHeader>
          {matterId ? (
            <CardContent className="space-y-3">
              <Button
                type="button"
                disabled={!configured || matterResolution.isPending}
                onClick={() => matterResolution.mutate(matterId)}
                data-testid="matter-case-resolve-submit"
              >
                <Search className="h-4 w-4" aria-hidden />
                Find matching case
              </Button>
              {matterResolution.isError ? (
                <p role="alert" className="text-sm text-[var(--color-danger)]">
                  {apiErrorMessage(matterResolution.error, "eCourts lookup is unavailable. Try again later.")}
                </p>
              ) : null}
              {matterResolution.data?.status === "insufficient_identifiers" ? (
                <p role="status">Insufficient case identifiers. Add a valid CNR, or a case number with year and court, to the Matter.</p>
              ) : null}
              {matterResolution.data?.status === "no_match" ? (
                <p role="status">No matching eCourts case found. Check the Matter identifiers or use the search below.</p>
              ) : null}
              {matterResolution.data?.status === "multiple_matches" ? (
                <p role="status">Multiple verified candidates remain. Review their case details; CaseOps will not choose one automatically.</p>
              ) : null}
              {matterResolution.data?.status === "matched" ? (
                <p role="status">One case matches the Matter identifiers.</p>
              ) : null}
              {matterLink.isError ? (
                <p role="alert" className="text-sm text-[var(--color-danger)]" data-testid="matter-case-link-error">
                  {apiErrorMessage(matterLink.error, "Could not link this case. Find it again and retry.")}
                </p>
              ) : null}
              {matterResolution.data?.results.map((result, index) => (
                <div key={`${result.cnr_number ?? result.case_number}-${index}`} className="border-t border-[var(--color-line)] pt-3" data-testid="matter-case-candidate">
                  <CaseSummary
                    title={result.case_title}
                    court={result.court_name}
                    status={result.current_status}
                    stage={result.current_stage}
                    nextHearing={result.next_hearing_on}
                  />
                  <p className="mt-1 text-xs text-[var(--color-mute)]">{result.cnr_number ?? result.case_number}</p>
                  {linkedCandidateToken === result.link_token ? (
                    <p role="status" className="mt-2 flex flex-wrap items-center gap-2 text-sm" data-testid="matter-case-linked">
                      Linked to this Matter.
                      <Link href={`/app/matters/${encodeURIComponent(matterId)}`} className="font-medium text-[var(--color-brand-600)] hover:underline">View Matter</Link>
                    </p>
                  ) : (
                    <Button
                      type="button"
                      variant="secondary"
                      className="mt-2"
                      disabled={matterLink.isPending}
                      onClick={() => matterLink.mutate({ matterId, linkToken: result.link_token })}
                      data-testid="matter-case-link-submit"
                    >
                      <Link2 className="h-4 w-4" aria-hidden />
                      Link to Matter
                    </Button>
                  )}
                </div>
              ))}
            </CardContent>
          ) : null}
        </Card>
      ) : null}

      <Card data-testid="case-tracking-support-matrix">
        <CardHeader>
          <CardTitle as="h2" className="text-base">Court support matrix</CardTitle>
          <CardDescription>
            Availability, lookup method, freshness, and usage constraints shown before tracking.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {supportMatrix.isPending ? (
            <Skeleton className="h-24 w-full" />
          ) : supportMatrix.data?.rows.length ? (
            <div className="overflow-x-auto">
              <table className="min-w-full text-left text-sm">
                <thead className="border-b border-[var(--color-line)] text-xs uppercase text-[var(--color-mute)]">
                  <tr>
                    <th className="py-2 pr-4">Court</th>
                    <th className="py-2 pr-4">Provider</th>
                    <th className="py-2 pr-4">Lookup</th>
                    <th className="py-2 pr-4">Freshness</th>
                    <th className="py-2 pr-4">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {supportMatrix.data.rows.map((row) => (
                    <tr key={row.id} className="border-b border-[var(--color-line-2)]">
                      <td className="py-3 pr-4 font-medium">
                        {[row.court, row.bench_jurisdiction].filter(Boolean).join(" / ")}
                      </td>
                      <td className="py-3 pr-4">{row.provider}</td>
                      <td className="py-3 pr-4">{row.lookup_method}</td>
                      <td className="py-3 pr-4">{row.freshness_sla ?? "-"}</td>
                      <td className="py-3 pr-4">
                        <Badge tone={row.enabled ? "success" : "warning"}>
                          {row.enabled ? "supported" : "disabled"}
                        </Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-sm text-[var(--color-mute)]">
              No tenant-visible court support rows are published yet.
            </p>
          )}
        </CardContent>
      </Card>

      <Card data-testid="case-tracking-search">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Search className="h-4 w-4" aria-hidden />
            Search case
          </CardTitle>
          <CardDescription>
            eCourtsIndia is used only through a configured provider adapter.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <form
            className="grid gap-2 md:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_minmax(0,1fr)_minmax(0,.8fr)_auto]"
            onSubmit={(event) => {
              event.preventDefault();
              if (!canSearch || searchMutation.isPending) return;
              setLinkedCandidateToken(null);
              matterLink.reset();
              searchMutation.mutate({
                query: query.trim() || null,
                cnr_number: cnr.trim() || null,
                case_number: caseNumber.trim() || null,
                court_code: courtCode.trim() || null,
              });
            }}
          >
            <Input
              aria-label="Case name or party search"
              data-testid="case-tracking-query"
              placeholder="Case name, party, advocate, or keyword"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
            <Input
              aria-label="CNR number"
              data-testid="case-tracking-cnr"
              placeholder="CNR number"
              value={cnr}
              onChange={(event) => setCnr(event.target.value)}
            />
            <Input
              aria-label="Case number"
              data-testid="case-tracking-case-number"
              placeholder="Case number"
              value={caseNumber}
              onChange={(event) => setCaseNumber(event.target.value)}
            />
            <Input
              aria-label="Court code"
              data-testid="case-tracking-court-code"
              placeholder="Court code"
              value={courtCode}
              onChange={(event) => setCourtCode(event.target.value)}
            />
            <Button
              type="submit"
              disabled={!canSearch || searchMutation.isPending}
              data-testid="case-tracking-search-submit"
            >
              <Search className="h-4 w-4" aria-hidden />
              Search
            </Button>
          </form>

          {searchMutation.isError ? (
            <p
              className="text-sm text-[var(--color-danger)]"
              data-testid="case-tracking-search-error"
            >
              {apiErrorMessage(
                searchMutation.error,
                "Search could not be completed. Check your connection and try again.",
              )}
            </p>
          ) : null}
          {bookmarkMutation.isError ? (
            <p
              className="text-sm text-[var(--color-danger)]"
              data-testid="case-tracking-bookmark-error"
            >
              {apiErrorMessage(
                bookmarkMutation.error,
                "Could not bookmark this case. Try again.",
              )}
            </p>
          ) : null}
          {matterLink.isError && !matterResolution.data?.results.some(
            (result) => result.link_token === matterLink.variables?.linkToken,
          ) ? (
            <p role="alert" className="text-sm text-[var(--color-danger)]" data-testid="matter-search-link-error">
              {apiErrorMessage(matterLink.error, "Could not link this case. Find it again and retry.")}
            </p>
          ) : null}
          {searchMutation.isSuccess ? (
            searchMutation.data.results.length ? (
              <div className="divide-y divide-[var(--color-line)] rounded-md border border-[var(--color-line)]">
                {searchMutation.data.results.map((result) => (
                  <SearchResultRow
                    key={`${result.provider}:${result.cnr_number ?? result.case_number}`}
                    result={result}
                    busy={bookmarkMutation.isPending || matterLink.isPending}
                    matterContext={Boolean(matterId)}
                    scopeMatterId={matterId ?? null}
                    linked={
                      result.linked_to_matter ||
                      Boolean(result.link_token && linkedCandidateToken === result.link_token)
                    }
                    onLink={result.link_token && matterId
                      ? () => matterLink.mutate({ matterId, linkToken: result.link_token as string })
                      : undefined}
                    onBookmark={() =>
                      bookmarkMutation.mutate({
                        provider: result.provider,
                        cnr_number: result.cnr_number,
                        case_number: result.case_number,
                        court_code: result.court_code,
                        court_name: result.court_name,
                        case_title: result.case_title,
                        party_names: result.party_names,
                        current_status: result.current_status,
                        current_stage: result.current_stage,
                        next_hearing_on: result.next_hearing_on,
                        matter_id: null,
                        notification_enabled: true,
                        metadata: {},
                      })
                    }
                  />
                ))}
              </div>
            ) : (
              <p
                className="text-sm text-[var(--color-mute)]"
                data-testid="case-tracking-search-empty"
              >
                No cases matched your search. Check the CNR, case number, court
                code, or party name and try again.
              </p>
            )
          ) : null}
        </CardContent>
      </Card>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <Card data-testid="case-tracking-bookmarks">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Bookmark className="h-4 w-4" aria-hidden />
              Bookmarks
            </CardTitle>
            <CardDescription>In-app only notifications for bookmarked cases.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {refreshMutation.isError ? (
              <p
                className="text-sm text-[var(--color-danger)]"
                role="alert"
                data-testid="case-tracking-refresh-error"
              >
                {apiErrorMessage(
                  refreshMutation.error,
                  "Could not refresh this case. Check your connection and try again.",
                )}
              </p>
            ) : null}
            {updateMutation.isError ? (
              <p
                className="text-sm text-[var(--color-danger)]"
                role="alert"
                data-testid="case-tracking-bookmark-update-error"
              >
                {apiErrorMessage(updateMutation.error, "Could not update this bookmark. Try again.")}
              </p>
            ) : null}
            {bookmarks.data?.bookmarks.length ? (
              <div className="divide-y divide-[var(--color-line)] rounded-md border border-[var(--color-line)]">
                {bookmarks.data.bookmarks.map((bookmark) => (
                  <BookmarkRow
                    key={bookmark.id}
                    bookmark={bookmark}
                    selected={selectedBookmarkId === bookmark.id}
                    busy={refreshMutation.isPending || updateMutation.isPending}
                    onSelect={() => setSelectedBookmarkId(bookmark.id)}
                    onRefresh={() => refreshMutation.mutate(bookmark.id)}
                    onToggleNotifications={() =>
                      updateMutation.mutate({
                        bookmarkId: bookmark.id,
                        input: {
                          notification_enabled: !bookmark.notification_enabled,
                        },
                      })
                    }
                    onArchive={() =>
                      updateMutation.mutate({
                        bookmarkId: bookmark.id,
                        input: { is_archived: true },
                      })
                    }
                  />
                ))}
              </div>
            ) : (
              <EmptyState
                title="No tracked cases yet"
                description="Search by CNR or case number and bookmark a result."
              />
            )}
          </CardContent>
        </Card>

        <Card data-testid="case-tracking-updates">
          <CardHeader>
            <CardTitle>Updates</CardTitle>
            <CardDescription>
              Orders, judgments, hearing changes, and status changes detected by polling.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {!selectedBookmarkId ? (
              <p className="text-sm text-[var(--color-mute)]">
                Select a bookmark to view updates.
              </p>
            ) : updates.isLoading ? (
              <Skeleton className="h-24 w-full" />
            ) : updates.data?.updates.length ? (
              <div className="divide-y divide-[var(--color-line)] rounded-md border border-[var(--color-line)]">
                {updates.data.updates.map((update) => (
                  <UpdateRow key={update.id} update={update} />
                ))}
              </div>
            ) : (
              <p className="text-sm text-[var(--color-mute)]">
                No updates detected for this bookmark yet.
              </p>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function SearchResultRow({
  result,
  busy,
  matterContext,
  scopeMatterId,
  linked,
  onLink,
  onBookmark,
}: {
  result: MatterAwareSearchResult;
  busy: boolean;
  matterContext: boolean;
  scopeMatterId: string | null;
  linked: boolean;
  onLink?: () => void;
  onBookmark: () => void;
}) {
  // Server-owned: visible Matters that already record this case's CNR. The
  // scoped Matter itself is represented by the linked / link states above.
  const existing = result.existing_matters.filter((matter) => matter.matter_id !== scopeMatterId);
  return (
    <div className="flex flex-col gap-3 p-3 md:flex-row md:items-center md:justify-between">
      <div className="min-w-0">
        <CaseSummary
          title={result.case_title}
          court={result.court_name}
          status={result.current_status}
          stage={result.current_stage}
          nextHearing={result.next_hearing_on}
        />
        <p className="mt-1 text-xs text-[var(--color-mute)]">{result.cnr_number ?? result.case_number}</p>
        {existing.length ? (
          <ul aria-label="Existing matters for this case" className="mt-2 flex flex-col gap-1 text-xs">
            {existing.map((matter) => (
              <li key={matter.matter_id} className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span className="text-[var(--color-mute)]">Existing matter:</span>
                <span className="font-medium">{matter.matter_code ? `${matter.matter_code} - ` : ""}{matter.title}</span>
                <Link
                  href={`/app/matters/${matter.matter_id}`}
                  className="font-medium text-[var(--color-brand-600)] hover:underline"
                  data-testid={`existing-matter-open-${matter.matter_id}`}
                >
                  Open matter
                </Link>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
      {linked ? (
        <p role="status" className="text-sm font-medium" data-testid="matter-search-linked">Linked to this Matter</p>
      ) : onLink ? (
        <Button type="button" variant="secondary" onClick={onLink} disabled={busy} data-testid="matter-search-link-submit">
          <Link2 className="h-4 w-4" aria-hidden />
          Link to Matter
        </Button>
      ) : matterContext ? (
        <p className="text-xs text-[var(--color-mute)]" data-testid="matter-search-unmatched">Does not match this Matter</p>
      ) : (
        <Button type="button" variant="secondary" onClick={onBookmark} disabled={busy}>
          <Bookmark className="h-4 w-4" aria-hidden />
          Bookmark
        </Button>
      )}
    </div>
  );
}

function BookmarkRow({
  bookmark,
  selected,
  busy,
  onSelect,
  onRefresh,
  onToggleNotifications,
  onArchive,
}: {
  bookmark: CaseTrackingBookmarkRecord;
  selected: boolean;
  busy: boolean;
  onSelect: () => void;
  onRefresh: () => void;
  onToggleNotifications: () => void;
  onArchive: () => void;
}) {
  const tracking = bookmark.tracked_case;
  const refreshDisabled = busy || !tracking.manual_refresh_allowed;
  const formatTimestamp = (value: string | null) =>
    value ? new Date(value).toLocaleString() : "Never";
  return (
    <div
      className="space-y-3 p-3"
      data-testid={`case-tracking-bookmark-${bookmark.id}`}
    >
      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <button type="button" className="min-w-0 text-left" onClick={onSelect}>
          <CaseSummary
            title={bookmark.name || bookmark.tracked_case.case_title}
            court={bookmark.tracked_case.court_name}
            status={bookmark.tracked_case.current_status}
            stage={bookmark.tracked_case.current_stage}
            nextHearing={bookmark.tracked_case.next_hearing_on}
          />
        </button>
        <div className="flex w-full min-w-0 flex-wrap gap-2 md:w-auto">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={onRefresh}
            disabled={refreshDisabled}
            title={tracking.manual_refresh_disabled_reason ?? undefined}
          >
            <RefreshCw className="h-4 w-4" aria-hidden />
            Refresh
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={onToggleNotifications}
            disabled={busy}
            title={bookmark.notification_enabled ? "Disable notifications" : "Enable notifications"}
          >
            {bookmark.notification_enabled ? (
              <Bell className="h-4 w-4" aria-hidden />
            ) : (
              <BellOff className="h-4 w-4" aria-hidden />
            )}
          </Button>
          <Button type="button" variant="ghost" size="sm" onClick={onArchive} disabled={busy}>
            <Archive className="h-4 w-4" aria-hidden />
          </Button>
        </div>
      </div>
      <div className="flex flex-wrap gap-1.5">
        <Badge tone={selected ? "brand" : "neutral"}>{bookmark.update_count} updates</Badge>
        <Badge tone="neutral">In-app only</Badge>
        <Badge tone={tracking.provider_health === "healthy" ? "success" : "warning"}>
          {tracking.provider} · {tracking.provider_health}
        </Badge>
        <Badge tone={tracking.freshness_status === "fresh" ? "success" : "warning"}>
          {tracking.freshness_status.replaceAll("_", " ")}
        </Badge>
        <Badge tone="neutral">Attempted {formatTimestamp(tracking.last_provider_attempted_at)}</Badge>
        <Badge tone="neutral">Last good {formatTimestamp(tracking.last_provider_successful_at)}</Badge>
        <Badge tone="neutral">Next {formatTimestamp(tracking.next_provider_refresh_at)}</Badge>
        <Badge tone="neutral">
          Refresh cost {tracking.refresh_currency} {(tracking.refresh_cost_minor / 100).toFixed(2)}
        </Badge>
        {tracking.response_class ? <Badge tone="neutral">{tracking.response_class}</Badge> : null}
      </div>
      {tracking.last_error || tracking.manual_refresh_disabled_reason ? (
        <p className="text-xs text-amber-800" role="status">
          {tracking.last_error ?? tracking.manual_refresh_disabled_reason} Evidence remains available;
          use manual docketing while provider health is degraded.
        </p>
      ) : null}
    </div>
  );
}

function UpdateRow({ update }: { update: CaseTrackingUpdateRecord }) {
  const sourceHref = update.source_url
    ? update.source_url.startsWith("/api/")
      ? `${API_BASE_URL}${update.source_url}`
      : update.source_url
    : null;
  return (
    <div
      className="space-y-2 p-3"
      data-testid={`case-tracking-update-${update.id}`}
    >
      <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
        <div>
          <p className="text-sm font-medium text-[var(--color-ink)]">{update.title}</p>
          <div className="mt-1 flex flex-wrap gap-1.5">
            <Badge tone="brand">{update.update_type}</Badge>
            <Badge tone="neutral">AI summary for lawyer review</Badge>
          </div>
        </div>
        {sourceHref ? (
          <a
            href={sourceHref}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-xs font-medium text-[var(--color-brand-600)] hover:underline"
          >
            Source
            <ExternalLink className="h-3 w-3" aria-hidden />
          </a>
        ) : null}
      </div>
      {update.summary ? (
        <p className="text-xs text-[var(--color-ink-2)]">{update.summary}</p>
      ) : null}
      <p className="text-xs text-[var(--color-mute)]">
        {update.order_date ?? update.hearing_date ?? update.created_at}
      </p>
    </div>
  );
}

function CaseSummary({
  title,
  court,
  status,
  stage,
  nextHearing,
}: {
  title: string;
  court: string | null;
  status: string | null;
  stage: string | null;
  nextHearing: string | null;
}) {
  return (
    <div className="min-w-0">
      <p className="truncate text-sm font-medium text-[var(--color-ink)]">{title}</p>
      <p className="text-xs text-[var(--color-mute)]">
        {[court, status, stage].filter(Boolean).join(" / ") || "Provider-normalized case"}
      </p>
      {nextHearing ? (
        <p className="text-xs text-[var(--color-ink-2)]">Next hearing: {nextHearing}</p>
      ) : null}
    </div>
  );
}
