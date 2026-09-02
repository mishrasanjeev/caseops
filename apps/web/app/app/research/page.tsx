"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import {
  Bookmark,
  FileCheck2,
  LibraryBig,
  Loader2,
  Scale,
  Search,
  SlidersHorizontal,
} from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { toast } from "sonner";

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
import { PageHeader } from "@/components/ui/PageHeader";
import { SourceAction } from "@/components/app/SourceAction";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/Select";
import { ApiError, apiErrorMessage } from "@/lib/api/config";
import {
  type AuthorityDocumentType,
  type AuthorityForumLevel,
  type AuthoritySearchMode,
  type AuthoritySearchOutcome,
  type AuthoritySearchResult,
  type IndianKanoonSearchResult,
  type IndianKanoonReadiness,
  createAuthorityResearchReport,
  createAuthorityAnnotation,
  fetchIndianKanoonReadiness,
  searchAuthorities,
  searchIndianKanoon,
} from "@/lib/api/endpoints";
import { useCapability } from "@/lib/capabilities";
import { formatLegalDate } from "@/lib/dates";

type ForumFilter = "any" | AuthorityForumLevel;
type DocTypeFilter = "any" | AuthorityDocumentType;
type ResearchSource = "caseops_corpus" | "indian_kanoon";
type SearchCriteria = {
  query: string;
  forumLevel: ForumFilter;
  courtName: string;
  documentType: DocTypeFilter;
  language: "en" | "any";
  searchMode: AuthoritySearchMode;
};

export default function ResearchPage() {
  const canSearch = useCapability("authorities:search");
  const canAnnotate = useCapability("authorities:annotate");
  const searchParams = useSearchParams();
  const initialQuery = searchParams?.get("q")?.trim() ?? "";
  const initialMode = parseAuthoritySearchMode(searchParams?.get("mode"));
  const [query, setQuery] = useState(initialQuery);
  const [forumLevel, setForumLevel] = useState<ForumFilter>("any");
  const [courtName, setCourtName] = useState("");
  const [documentType, setDocumentType] = useState<DocTypeFilter>("any");
  const [searchMode, setSearchMode] =
    useState<AuthoritySearchMode>(initialMode);
  const [researchSource, setResearchSource] =
    useState<ResearchSource>("caseops_corpus");
  // PG-110 (2026-05-01): language filter + pagination. Default "en"
  // because the 2026-04-28 ingest sweep dropped the EN-only filter,
  // so without a default users were seeing Garo / Hindi / Tamil
  // titles dominate top results. PAGE_SIZE matches the new server-side
  // limit ceiling step.
  const PAGE_SIZE = 10;
  const [language, setLanguage] = useState<"en" | "any">("en");
  const [page, setPage] = useState(0);
  const [searchCriteria, setSearchCriteria] = useState<SearchCriteria | null>(
    initialQuery.length >= 2
      ? {
          query: initialQuery,
          forumLevel: "any",
          courtName: "",
          documentType: "any",
          language: "en",
          searchMode: initialMode,
        }
      : null,
  );

  // When the user arrives via the topbar search (?q=...), re-sync local
  // state + fire the query if a new ?q= lands while we're on the page.
  useEffect(() => {
    const nextQ = searchParams?.get("q")?.trim() ?? "";
    const nextMode = parseAuthoritySearchMode(searchParams?.get("mode"));
    if (nextQ && nextQ !== searchCriteria?.query) {
      setQuery(nextQ);
      setSearchMode(nextMode);
      if (nextQ.length >= 2) {
        setPage(0);
        setSearchCriteria({
          query: nextQ,
          forumLevel,
          courtName,
          documentType,
          language,
          searchMode: nextMode,
        });
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);
  const [savedAuthorityIds, setSavedAuthorityIds] = useState<Set<string>>(
    () => new Set(),
  );

  const searchQuery = useQuery({
    queryKey: [
      "authorities",
      "search",
      {
        criteria: searchCriteria,
        page,
      },
    ],
    queryFn: () => {
      if (!searchCriteria) {
        throw new Error(
          "Search criteria are required before authority search.",
        );
      }
      return searchAuthorities({
        query: searchCriteria.query,
        mode: searchCriteria.searchMode,
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
        language: searchCriteria.language,
        forumLevel:
          searchCriteria.forumLevel === "any"
            ? null
            : searchCriteria.forumLevel,
        courtName: searchCriteria.courtName.trim() || null,
        documentType:
          searchCriteria.documentType === "any"
            ? null
            : searchCriteria.documentType,
      });
    },
    enabled:
      canSearch &&
      researchSource === "caseops_corpus" &&
      (searchCriteria?.query.trim().length ?? 0) >= 2,
  });

  const licensedReadinessQuery = useQuery({
    queryKey: ["authorities", "providers", "indian-kanoon", "readiness"],
    queryFn: fetchIndianKanoonReadiness,
    enabled: canSearch && researchSource === "indian_kanoon",
  });

  const licensedSearchQuery = useQuery({
    queryKey: [
      "authorities",
      "providers",
      "indian-kanoon",
      "search",
      searchCriteria?.query,
    ],
    queryFn: () => {
      if (!searchCriteria) {
        throw new Error("Search criteria are required before provider search.");
      }
      return searchIndianKanoon({
        query: searchCriteria.query,
        maxResults: 20,
      });
    },
    enabled:
      canSearch &&
      researchSource === "indian_kanoon" &&
      licensedReadinessQuery.data?.external_calls_enabled === true &&
      (searchCriteria?.query.trim().length ?? 0) >= 2,
  });

  const saveMutation = useMutation({
    mutationFn: (input: AuthoritySearchResult) =>
      createAuthorityAnnotation({
        authorityId: input.authority_document_id,
        kind: "flag",
        title: searchCriteria?.query
          ? `Research: ${searchCriteria.query.slice(0, 200)}`
          : input.title.slice(0, 200),
        body: input.snippet.slice(0, 2000),
      }),
    onSuccess: (_result, input) => {
      setSavedAuthorityIds((prev) => {
        const next = new Set(prev);
        next.add(input.authority_document_id);
        return next;
      });
      toast.success("Saved to your research notebook");
    },
    onError: (err) => {
      toast.error(apiErrorMessage(err, "Could not save that authority."));
    },
  });

  const reportMutation = useMutation({
    mutationFn: () => {
      if (!searchCriteria || results.length === 0) {
        throw new Error("Run a search with results before saving a report.");
      }
      return createAuthorityResearchReport({
        name: `Research: ${searchCriteria.query.slice(0, 160)}`,
        query: searchCriteria.query,
        mode: searchCriteria.searchMode,
        resultIds: results.map((result) => result.authority_document_id),
        criteria: {
          forum_level: searchCriteria.forumLevel,
          court_name: searchCriteria.courtName || null,
          document_type: searchCriteria.documentType,
          language: searchCriteria.language,
          offset: page * PAGE_SIZE,
        },
      });
    },
    onSuccess: () =>
      toast.success("Research report saved as an immutable snapshot"),
    onError: (error) =>
      toast.error(
        apiErrorMessage(error, "Could not save this research report."),
      ),
  });

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    const trimmed = query.trim();
    if (trimmed.length < 2) {
      toast.error("Type at least two characters to search.");
      return;
    }
    setPage(0); // PG-110: reset pagination on a new query
    setSearchCriteria({
      query: trimmed,
      forumLevel,
      courtName,
      documentType,
      language,
      searchMode,
    });
  };

  const results = searchQuery.data?.results ?? [];
  const visibleResults = results.filter(
    (result) => !isUnreadableAuthorityResult(result),
  );
  const contextualPlan = searchQuery.data?.contextual_plan ?? null;
  const coverageNotice = searchQuery.data?.coverage_notice ?? null;
  const searchOutcome = searchQuery.data?.outcome ?? null;
  const corpusCoverage = searchQuery.data?.corpus_coverage ?? null;
  const totalAfterFilter = searchQuery.data?.total_after_filter ?? 0;
  const hasSearched = Boolean(searchCriteria?.query);
  const unreadableOnlyResults =
    results.length > 0 && visibleResults.length === 0;
  const hasNextPage = (page + 1) * PAGE_SIZE < totalAfterFilter;
  const hasPrevPage = page > 0;
  const licensedReady =
    licensedReadinessQuery.data?.external_calls_enabled === true;
  const activeSearchFetching =
    researchSource === "indian_kanoon"
      ? licensedSearchQuery.isFetching
      : searchQuery.isFetching;
  const canSubmitSearch =
    canSearch &&
    query.trim().length >= 2 &&
    !activeSearchFetching &&
    (researchSource === "caseops_corpus" || licensedReady);

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Research"
        title="Grounded legal research"
        description={
          corpusCoverage
            ? `Searching ${corpusCoverage.document_count.toLocaleString()} judgments across SC + HCs. Every result links to source.`
            : "Hybrid retrieval across statutes, judgments, and your own precedents — every answer cited and traceable."
        }
        actions={
          <Link href="/app/research/saved">
            <Button
              variant="outline"
              size="sm"
              data-testid="research-open-saved"
            >
              <Bookmark className="mr-1 h-3.5 w-3.5" />
              Saved research
            </Button>
          </Link>
        }
      />

      <Card>
        <CardHeader>
          <CardTitle as="h2" className="text-base">
            Find authorities
          </CardTitle>
          <CardDescription>
            {researchSource === "indian_kanoon"
              ? "Search the workspace-approved licensed source."
              : "Use natural language. Filters narrow by court, forum, and document type."}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="flex flex-col gap-3">
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <Label className="text-xs text-[var(--color-mute-2)]">
                Source
              </Label>
              <div
                className="flex w-full min-w-0 rounded-md border border-[var(--color-line)] bg-white sm:w-auto"
                data-testid="research-source-toggle"
              >
                {(
                  [
                    ["caseops_corpus", "CaseOps corpus"],
                    ["indian_kanoon", "Indian Kanoon"],
                  ] as const
                ).map(([value, label]) => (
                  <button
                    key={value}
                    type="button"
                    onClick={() => {
                      setResearchSource(value);
                      setSearchCriteria(null);
                      setPage(0);
                    }}
                    data-testid={`research-source-${value.replace("_", "-")}`}
                    className={`min-w-0 flex-1 px-3 py-1 text-xs font-medium sm:flex-none ${
                      researchSource === value
                        ? "bg-[var(--color-ink)] text-white"
                        : "text-[var(--color-ink-2)]"
                    }`}
                    aria-pressed={researchSource === value}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
            {researchSource === "indian_kanoon" ? (
              <div
                className={`rounded-md border px-3 py-2 text-xs ${
                  licensedReady
                    ? "border-[var(--color-success-600)]/30 bg-[var(--color-success-50)] text-[var(--color-success-700)]"
                    : "border-[var(--color-warn-600)]/30 bg-[var(--color-warn-50)] text-[var(--color-warn-700)]"
                }`}
                data-testid="research-indian-kanoon-readiness"
              >
                {licensedReadinessQuery.isPending
                  ? "Checking licensed-source readiness…"
                  : licensedReady
                    ? "Powered by Indian Kanoon. Licensed access is active for this workspace."
                    : indianKanoonReadinessMessage(licensedReadinessQuery.data)}
              </div>
            ) : null}
            {researchSource === "caseops_corpus" ? (
              <div className="flex flex-wrap items-center gap-2">
                <Label className="text-xs text-[var(--color-mute-2)]">
                  Mode
                </Label>
                <div
                  className="flex w-full min-w-0 flex-wrap rounded-md border border-[var(--color-line)] bg-white sm:w-auto"
                  data-testid="research-mode-toggle"
                >
                  {(
                    [
                      ["keyword", "Keyword"],
                      ["contextual", "Context"],
                      ["exact_citation", "Citation"],
                      ["party", "Party"],
                      ["court", "Court"],
                      ["judge", "Judge"],
                      ["act_section", "Act / section"],
                    ] as const
                  ).map(([value, label]) => (
                    <button
                      key={value}
                      type="button"
                      onClick={() => setSearchMode(value)}
                      data-testid={`research-mode-${value.replace("_", "-")}`}
                      className={`min-w-0 flex-1 px-3 py-1 text-xs font-medium sm:flex-none ${
                        searchMode === value
                          ? "bg-[var(--color-ink)] text-white"
                          : "text-[var(--color-ink-2)]"
                      }`}
                      aria-pressed={searchMode === value}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>
            ) : null}
            <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-center">
              <Search
                className="h-4 w-4 text-[var(--color-mute)]"
                aria-hidden
              />
              <Input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder={
                  searchMode === "contextual"
                    ? "Cheque bounced due to insufficient funds and notice was sent after 35 days"
                    : "Triple test for bail under BNSS s.483; parity; custody duration"
                }
                aria-label="Research query"
                data-testid="research-query-input"
                className="min-w-0 flex-1"
              />
              <Button
                type="submit"
                size="sm"
                disabled={!canSubmitSearch}
                data-testid="research-query-submit"
                className="w-full sm:w-auto"
              >
                {activeSearchFetching ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" aria-hidden />{" "}
                    Searching…
                  </>
                ) : (
                  <>
                    <Search className="h-4 w-4" aria-hidden /> Search
                  </>
                )}
              </Button>
            </div>
            {researchSource === "caseops_corpus" ? (
              <div className="grid gap-3 md:grid-cols-3">
                <div className="flex flex-col gap-1">
                  <Label htmlFor="forum-filter" className="text-xs">
                    <SlidersHorizontal
                      className="mr-1 inline h-3 w-3"
                      aria-hidden
                    />{" "}
                    Forum
                  </Label>
                  <Select
                    value={forumLevel}
                    onValueChange={(value) =>
                      setForumLevel(value as ForumFilter)
                    }
                  >
                    <SelectTrigger
                      id="forum-filter"
                      data-testid="research-filter-forum"
                    >
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="any">Any forum</SelectItem>
                      <SelectItem value="supreme_court">
                        Supreme Court
                      </SelectItem>
                      <SelectItem value="high_court">High Court</SelectItem>
                      <SelectItem value="tribunal">Tribunal</SelectItem>
                      <SelectItem value="lower_court">Lower court</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex flex-col gap-1">
                  <Label htmlFor="court-filter" className="text-xs">
                    Court name contains
                  </Label>
                  <Input
                    id="court-filter"
                    value={courtName}
                    onChange={(event) => setCourtName(event.target.value)}
                    placeholder="Delhi, Bombay, Supreme…"
                    data-testid="research-filter-court"
                  />
                </div>
                <div className="flex flex-col gap-1">
                  <Label htmlFor="doctype-filter" className="text-xs">
                    Document type
                  </Label>
                  <Select
                    value={documentType}
                    onValueChange={(value) =>
                      setDocumentType(value as DocTypeFilter)
                    }
                  >
                    <SelectTrigger
                      id="doctype-filter"
                      data-testid="research-filter-doctype"
                    >
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="any">Any type</SelectItem>
                      <SelectItem value="judgment">Judgment</SelectItem>
                      <SelectItem value="order">Order</SelectItem>
                      <SelectItem value="statute">Statute</SelectItem>
                      <SelectItem value="regulation">Regulation</SelectItem>
                      <SelectItem value="other">Other</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>
            ) : null}
            {/* PG-110 (2026-05-01): language filter. Default English so
                Garo / Hindi / Tamil judgments pulled by the 2026-04-28
                ingest sweep don't dominate top results. */}
            {researchSource === "caseops_corpus" ? (
              <div className="flex flex-wrap items-center gap-2">
                <Label className="text-xs text-[var(--color-mute-2)]">
                  Language
                </Label>
                <div
                  className="inline-flex rounded-md border border-[var(--color-line)] bg-white"
                  data-testid="research-language-toggle"
                >
                  <button
                    type="button"
                    onClick={() => setLanguage("en")}
                    data-testid="research-language-en"
                    className={`px-3 py-1 text-xs font-medium ${
                      language === "en"
                        ? "bg-[var(--color-ink)] text-white"
                        : "text-[var(--color-ink-2)]"
                    }`}
                    aria-pressed={language === "en"}
                  >
                    English
                  </button>
                  <button
                    type="button"
                    onClick={() => setLanguage("any")}
                    data-testid="research-language-any"
                    className={`px-3 py-1 text-xs font-medium ${
                      language === "any"
                        ? "bg-[var(--color-ink)] text-white"
                        : "text-[var(--color-ink-2)]"
                    }`}
                    aria-pressed={language === "any"}
                  >
                    All languages
                  </button>
                </div>
              </div>
            ) : null}
          </form>
        </CardContent>
      </Card>

      {researchSource === "caseops_corpus" && corpusCoverage ? (
        <div
          className="rounded-lg border border-[var(--color-line)] bg-[var(--color-bg-2)] px-4 py-3 text-xs text-[var(--color-ink-2)]"
          data-testid="research-corpus-coverage"
        >
          <span className="font-semibold text-[var(--color-ink)]">
            Corpus scope
          </span>{" "}
          {corpusCoverage.scope_summary}.{" "}
          {corpusCoverage.document_count.toLocaleString()} documents; index{" "}
          {corpusCoverage.index_state}.
          {corpusCoverage.last_ingested_at
            ? ` Latest ingest ${formatLegalDate(corpusCoverage.last_ingested_at, { day: "2-digit", month: "short", year: "numeric" })}.`
            : " No completed ingest timestamp is available."}
        </div>
      ) : null}

      {!canSearch ? (
        <EmptyState
          icon={LibraryBig}
          title="You don't have access to authority search"
          description="Ask a workspace admin to grant the authorities:search capability."
        />
      ) : !hasSearched ? (
        <EmptyState
          icon={Scale}
          title="Start with a natural-language query"
          description="Example: ‘triple test for bail under BNSS s.483’, ‘res judicata in HC writs’, or ‘limitation period for arbitration award enforcement’."
        />
      ) : (
          researchSource === "caseops_corpus"
            ? searchQuery.isPending || searchQuery.isFetching
            : licensedSearchQuery.isFetching
        ) ? (
        <EmptyState
          icon={Loader2}
          title={
            researchSource === "indian_kanoon"
              ? "Searching Indian Kanoon…"
              : "Searching the corpus…"
          }
          description={
            researchSource === "indian_kanoon"
              ? "Running one bounded licensed-provider query."
              : "Hybrid retrieval across judgments, statutes, and your tenant overlay."
          }
        />
      ) : (
          researchSource === "indian_kanoon"
            ? licensedSearchQuery.isError
            : searchQuery.isError
        ) ? (
        <EmptyState
          icon={Scale}
          title={
            researchErrorCopy(
              researchSource === "indian_kanoon"
                ? licensedSearchQuery.error
                : searchQuery.error,
            ).title
          }
          description={
            researchErrorCopy(
              researchSource === "indian_kanoon"
                ? licensedSearchQuery.error
                : searchQuery.error,
            ).description
          }
          action={
            <Button
              size="sm"
              onClick={() =>
                researchSource === "indian_kanoon"
                  ? licensedSearchQuery.refetch()
                  : searchQuery.refetch()
              }
              data-testid="research-search-retry"
            >
              Retry search
            </Button>
          }
        />
      ) : researchSource === "indian_kanoon" ? (
        <IndianKanoonResults
          results={licensedSearchQuery.data?.results ?? []}
          call={licensedSearchQuery.data?.call ?? null}
          disclaimer={licensedSearchQuery.data?.disclaimer ?? null}
        />
      ) : visibleResults.length === 0 ? (
        <EmptyState
          icon={Scale}
          title={
            researchOutcomeCopy(searchOutcome, unreadableOnlyResults).title
          }
          description={
            unreadableOnlyResults
              ? researchOutcomeCopy(searchOutcome, true).description
              : (coverageNotice ??
                researchOutcomeCopy(searchOutcome, false).description)
          }
        />
      ) : (
        <>
          {contextualPlan ? (
            <div
              className="rounded-lg border border-[var(--color-line)] bg-[var(--color-bg-2)] px-4 py-3 text-xs text-[var(--color-ink-2)]"
              data-testid="research-contextual-plan"
            >
              <span className="font-semibold text-[var(--color-ink)]">
                Context extracted
              </span>
              <div className="mt-2 flex flex-wrap gap-2">
                {[
                  ...contextualPlan.statutes_or_sections,
                  ...contextualPlan.likely_issues,
                  ...contextualPlan.key_facts,
                  ...contextualPlan.timing_signals,
                ]
                  .slice(0, 8)
                  .map((item) => (
                    <span
                      key={item}
                      className="rounded-full border border-[var(--color-line)] bg-white px-2 py-0.5"
                    >
                      {item}
                    </span>
                  ))}
              </div>
            </div>
          ) : null}
          {coverageNotice ? (
            <div
              className="rounded-lg border border-[var(--color-warn-600)]/30 bg-[var(--color-warn-50)] px-4 py-3 text-xs text-[var(--color-warn-700)]"
              data-testid="research-coverage-notice"
            >
              {coverageNotice}
            </div>
          ) : null}
          <div className="flex w-full min-w-0 flex-wrap justify-end gap-2">
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={reportMutation.isPending}
              onClick={() => reportMutation.mutate()}
              data-testid="research-save-report"
              className="w-full sm:w-auto"
            >
              {reportMutation.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              ) : (
                <FileCheck2 className="h-4 w-4" aria-hidden />
              )}
              Save report
            </Button>
          </div>
          <ul className="flex flex-col gap-3" data-testid="research-results">
            {visibleResults.map((result) => (
              <AuthorityCard
                key={result.authority_document_id}
                result={result}
                saved={savedAuthorityIds.has(result.authority_document_id)}
                canAnnotate={canAnnotate}
                onSave={() => saveMutation.mutate(result)}
                saving={
                  saveMutation.isPending &&
                  saveMutation.variables?.authority_document_id ===
                    result.authority_document_id
                }
              />
            ))}
          </ul>
          {/* PG-110 (2026-05-01): paginate over the language-filtered
              result set. total_after_filter comes from the server. */}
          {totalAfterFilter > PAGE_SIZE ? (
            <div
              className="flex items-center justify-between gap-3 rounded-lg border border-[var(--color-line)] bg-[var(--color-bg-2)] px-4 py-3 text-sm"
              data-testid="research-pagination"
            >
              <span className="text-[var(--color-mute)]">
                Showing {page * PAGE_SIZE + 1}–
                {Math.min((page + 1) * PAGE_SIZE, totalAfterFilter)} of{" "}
                {totalAfterFilter}
                {searchCriteria?.language === "en"
                  ? " English-language matches"
                  : " matches across all languages"}
              </span>
              <div className="flex gap-2">
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  disabled={!hasPrevPage}
                  onClick={() => setPage((p) => Math.max(0, p - 1))}
                  data-testid="research-page-prev"
                >
                  Prev
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  disabled={!hasNextPage}
                  onClick={() => setPage((p) => p + 1)}
                  data-testid="research-page-next"
                >
                  Next
                </Button>
              </div>
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}

function IndianKanoonResults({
  results,
  call,
  disclaimer,
}: {
  results: IndianKanoonSearchResult[];
  call: {
    cached: boolean;
    stale: boolean;
    freshness_warning: string | null;
    retrieved_at: string;
    estimated_cost_minor: number;
    currency: "INR";
    cost_basis: "verified_actual" | "fresh_cache" | "stale_cache";
  } | null;
  disclaimer: string | null;
}) {
  if (results.length === 0) {
    return (
      <EmptyState
        icon={Scale}
        title="No licensed-source matches"
        description="Indian Kanoon returned no documents for this exact query. Revise the terms or search the CaseOps corpus."
      />
    );
  }
  return (
    <div
      className="flex min-w-0 flex-col gap-3"
      data-testid="research-indian-kanoon-results"
    >
      <div
        className={`flex flex-col items-start gap-2 rounded-md border px-4 py-3 text-xs ${
          call?.stale
            ? "border-[var(--color-warn-600)]/30 bg-[var(--color-warn-50)] text-[var(--color-warn-700)]"
            : "border-[var(--color-line)] bg-[var(--color-bg-2)] text-[var(--color-ink-2)]"
        }`}
        data-testid="research-indian-kanoon-attribution"
      >
        <picture data-testid="research-indian-kanoon-official-attribution">
          <source
            media="(max-width: 639px)"
            srcSet="https://api.indiankanoon.org/static/pics/ikanoon_mobile_powered_transparent.png"
          />
          {/* The provider's terms require this supplied logo to remain unaltered. */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src="https://api.indiankanoon.org/static/pics/ikanoon6_powered_transparent.png"
            alt="Powered by IKanoon"
            width={150}
            height={61}
            referrerPolicy="no-referrer"
          />
        </picture>
        {call ? (
          <span>
            {` · ${call.cached ? "Cached response" : "Licensed API response"}`}
            {call.estimated_cost_minor > 0
              ? ` · estimated provider cost ₹${(call.estimated_cost_minor / 100).toFixed(2)}`
              : " · no new provider charge"}
          </span>
        ) : null}
        {call?.freshness_warning ? (
          <p className="mt-1">{call.freshness_warning}</p>
        ) : null}
        {disclaimer ? <p className="mt-1">{disclaimer}</p> : null}
      </div>
      <ul className="flex flex-col gap-3">
        {results.map((result) => (
          <li
            key={result.document_id}
            className="rounded-lg border border-[var(--color-line)] bg-white p-4"
            data-testid={`research-indian-kanoon-result-${result.document_id}`}
          >
            <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2 text-xs text-[var(--color-mute)]">
                  <span className="font-medium text-[var(--color-ink-2)]">
                    {result.publisher}
                  </span>
                  <span>{result.document_type.replace(/_/g, " ")}</span>
                  {result.decision_or_publication_date ? (
                    <span>
                      {formatLegalDate(result.decision_or_publication_date, {
                        day: "2-digit",
                        month: "short",
                        year: "numeric",
                      })}
                    </span>
                  ) : null}
                  {result.canonical_citation ? (
                    <span className="font-mono">
                      {result.canonical_citation}
                    </span>
                  ) : null}
                </div>
                <h3 className="mt-1 text-base font-semibold text-[var(--color-ink)]">
                  {result.title}
                </h3>
                {result.headline ? (
                  <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-[var(--color-ink-2)]">
                    {result.headline}
                  </p>
                ) : null}
                <p className="mt-2 text-xs text-[var(--color-mute)]">
                  {result.authority_status.replace(/_/g, " ")} ·{" "}
                  {result.binding_status.replace(/_/g, " ")}
                </p>
              </div>
              <div className="shrink-0">
                <SourceAction
                  action={result.source_action}
                  compact
                  originSurface="research"
                />
              </div>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

function indianKanoonReadinessMessage(
  readiness: IndianKanoonReadiness | undefined,
): string {
  if (!readiness) {
    return "Licensed-source readiness could not be determined.";
  }
  if (readiness.state === "blocked_disabled") {
    const missing = indianKanoonMissingSetup(readiness);
    return missing.length
      ? `Indian Kanoon search is disabled because setup is incomplete: ${missing.join(", ")}. No provider call will be made.`
      : "Indian Kanoon search is disabled by the runtime switch. No provider call will be made.";
  }
  if (readiness.state === "blocked_missing_config") {
    const missing = indianKanoonMissingSetup(readiness);
    return `Indian Kanoon search setup is incomplete: ${missing.join(", ") || "provider settings"}. No provider call will be made.`;
  }
  if (readiness.state === "blocked_terms") {
    return `Licensed access has invalid or expired terms metadata: ${readiness.invalid_terms_config.join(", ") || "terms dates"}.`;
  }
  if (readiness.state === "blocked_costs") {
    return `Licensed access is missing verified cost profiles: ${readiness.missing_cost_categories.join(", ")}.`;
  }
  if (readiness.state === "blocked_budget") {
    return "Licensed access has exhausted its configured machine budget.";
  }
  return "Licensed-source readiness could not be determined.";
}

function indianKanoonMissingSetup(readiness: IndianKanoonReadiness): string[] {
  const names = readiness.missing_config_names;
  const categories: string[] = [];
  if (names.some((name) => name.includes("TOKEN"))) {
    categories.push("provider credentials");
  }
  if (names.some((name) => name.includes("TERMS_"))) {
    categories.push("contractual terms");
  }
  if (names.some((name) => name.includes("PERMITTED_USES"))) {
    categories.push("permitted uses");
  }
  if (names.some((name) => name.includes("RETENTION"))) {
    categories.push("retention policy");
  }
  if (names.some((name) => name.includes("BUDGET"))) {
    categories.push("machine budgets");
  }
  if (readiness.missing_cost_categories.length > 0) {
    categories.push("verified cost profiles");
  }
  return categories;
}

function researchErrorCopy(error: unknown): {
  title: string;
  description: string;
} {
  if (error instanceof DOMException && error.name === "AbortError") {
    return {
      title: "Request timed out",
      description:
        "The committed query and filters are still here. Retry the same search or narrow its scope.",
    };
  }
  if (error instanceof ApiError && error.status === 403) {
    return {
      title: "Permission denied",
      description:
        "Your account cannot search this source scope. Ask a workspace admin to review authorities:search access.",
    };
  }
  if (error instanceof ApiError && error.status === 422) {
    return {
      title: "Query invalid",
      description:
        "Review the query and filters, then submit again. Your last committed search has not been replaced.",
    };
  }
  if (error instanceof ApiError && error.status === 503) {
    return {
      title: "Provider unavailable",
      description:
        "The research provider is temporarily unavailable. Your committed query was preserved; retry later.",
    };
  }
  return {
    title: "Search failed",
    description:
      error instanceof ApiError
        ? error.detail
        : "The workspace API could not complete the search. Your committed query was preserved; retry when connectivity is restored.",
  };
}

function parseAuthoritySearchMode(
  value: string | null | undefined,
): AuthoritySearchMode {
  const modes: AuthoritySearchMode[] = [
    "keyword",
    "contextual",
    "exact_citation",
    "party",
    "court",
    "judge",
    "act_section",
  ];
  return modes.includes(value as AuthoritySearchMode)
    ? (value as AuthoritySearchMode)
    : "keyword";
}

function researchOutcomeCopy(
  outcome: AuthoritySearchOutcome | null,
  unreadableOnlyResults: boolean,
): { title: string; description: string } {
  if (unreadableOnlyResults || outcome === "unreadable_filtered") {
    return {
      title: "Matching documents are unreadable",
      description:
        "Matching records were omitted because their extracted title or text is not readable enough to preview. Review official source records before relying on them.",
    };
  }
  if (outcome === "corpus_unavailable") {
    return {
      title: "Corpus unavailable",
      description:
        "No searchable authority corpus is available. Retry after corpus health is restored.",
    };
  }
  if (outcome === "index_stale") {
    return {
      title: "Index stale",
      description:
        "The index is behind corpus evidence, so zero matches is not conclusive. Retry after indexing is reconciled.",
    };
  }
  if (outcome === "provider_unavailable") {
    return {
      title: "Provider unavailable",
      description:
        "The configured provider is unavailable. Retry the preserved query later.",
    };
  }
  if (outcome === "offset_out_of_range") {
    return {
      title: "Page no longer available",
      description:
        "The result set changed. Return to the previous page or rerun the search.",
    };
  }
  return {
    title: "No matching documents",
    description:
      "No indexed document matched this committed query and scope. Broaden filters or refine the query.",
  };
}

/**
 * BUG-021 (Ram 2026-04-26) + BUG-026 (Ram 2026-04-27 reopen): detect
 * snippets where OCR has degraded to mojibake.
 *
 * Real prod failure samples (added 2026-04-27 after BUG-026 reopen):
 *   "120-?J, '>2> 420, 427, 488 $O 477 .*J.:J."  ← ASCII mojibake
 *   "( $ &  Y P 9>'>(   "                          ← ASCII mojibake
 *
 * Original v1 detector (\uFFFD + control chars + single-letter density)
 * missed all of these because they use plain ASCII in nonsense
 * patterns. v2 adds:
 *  - High punctuation-to-letter ratio
 *  - High percentage of tokens with non-alphanumeric characters
 *  - Density of mid-token punctuation (`?J`, `$O`, `:J`, `>2>`)
 *
 * Tuned conservatively but ALL three v2 heuristics fire on the prod
 * failure samples above. Verified by tests/e2e/ram-batch-2026-04-26-prod.spec.ts.
 */
export function isGarbledSnippet(text: string | null | undefined): boolean {
  if (!text) return false;
  if (text.length < 40) return false;
  // v1: Replacement char (U+FFFD) is an unambiguous decoding failure.
  const replacementChars = (text.match(/\uFFFD/g) ?? []).length;
  if (replacementChars / text.length > 0.02) return true;
  // v1: Box-drawing / private-use / weird-symbol density.
  const oddChars = (
    text.match(/[\u2500-\u259F\uE000-\uF8FF\u2630-\u2BFF]/g) ?? []
  ).length;
  if (oddChars / text.length > 0.05) return true;
  // v1: Single-letter density (broken-ligature OCR fragments).
  const tokens = text.split(/\s+/).filter(Boolean);
  if (tokens.length >= 20) {
    const singletons = tokens.filter((t) => t.length === 1).length;
    if (singletons / tokens.length > 0.4) return true;
  }
  // v2 (BUG-026 reopen): ASCII-mojibake heuristics.
  // The letter-to-punctuation ratio. Real legal text is letter-heavy
  // (>0.7 letters/total). Mojibake is punctuation-heavy.
  const letters = (text.match(/[A-Za-z]/g) ?? []).length;
  const letterRatio = letters / text.length;
  if (letterRatio < 0.45 && text.length >= 60) return true;
  // Tokens containing non-alphanumeric mid-token chars (e.g. `?J`,
  // `$O`, `:J`, `>2>`, `120-?J`). Real legal text has clean tokens.
  if (tokens.length >= 8) {
    const dirtyTokens = tokens.filter(
      (t) =>
        /[^A-Za-z0-9.,;:()\-'/&]/.test(t) ||
        // Mid-token punctuation that isn't a comma/period at the end.
        /[A-Za-z]\?[A-Za-z]/.test(t) ||
        /[A-Za-z]\$[A-Za-z]/.test(t) ||
        /[A-Za-z]>[A-Za-z]/.test(t),
    ).length;
    if (dirtyTokens / tokens.length > 0.3) return true;
  }
  const alphaTokens = tokens.filter((t) => /[A-Za-z]/.test(t));
  if (alphaTokens.length >= 12) {
    const suspiciousTokens = alphaTokens.filter(looksLikeOcrFragment).length;
    if (suspiciousTokens / alphaTokens.length > 0.35) return true;
  }
  return false;
}

const COMMON_LEGAL_ACRONYMS = new Set([
  "ai",
  "arb",
  "bns",
  "bnss",
  "bsa",
  "cbi",
  "cpc",
  "crl",
  "crpc",
  "drat",
  "drt",
  "fir",
  "hc",
  "ipc",
  "llp",
  "ltd",
  "nclat",
  "nclt",
  "ni",
  "pdf",
  "sc",
  "slp",
  "wpc",
]);

function looksLikeOcrFragment(token: string): boolean {
  const stripped = token.replace(/^[.,;:()[\]{}"'`]+|[.,;:()[\]{}"'`]+$/g, "");
  if (stripped.length < 3 || !/[A-Za-z]/.test(stripped)) return false;
  if (/[A-Za-z]\d|\d[A-Za-z]/.test(stripped)) return true;

  const letters = stripped.replace(/[^A-Za-z]/g, "");
  if (letters.length < 3) return false;
  const lowered = letters.toLowerCase();
  if (COMMON_LEGAL_ACRONYMS.has(lowered)) return false;
  if (letters.length >= 4 && /([A-Za-z])\1{3,}/.test(letters)) return true;
  if (letters.length >= 4 && !/[aeiouAEIOU]/.test(letters)) return true;
  if (/[a-z][A-Z]{2,}|[A-Z][a-z][A-Z]/.test(stripped)) return true;
  if (letters.length <= 5 && /[A-Za-z].*[.:~].*[A-Za-z]/.test(stripped)) {
    return true;
  }
  return false;
}

function isUnreadableAuthorityResult(result: AuthoritySearchResult): boolean {
  const previewParts = [result.title, result.summary, result.snippet];
  return (
    previewParts.some((part) => isGarbledSnippet(part)) ||
    isGarbledSnippet(previewParts.join("\n"))
  );
}

function AuthorityCard({
  result,
  saved,
  canAnnotate,
  onSave,
  saving,
}: {
  result: AuthoritySearchResult;
  saved: boolean;
  canAnnotate: boolean;
  onSave: () => void;
  saving: boolean;
}) {
  const dateLabel = formatLegalDate(result.decision_date, {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
  return (
    <li className="rounded-xl border border-[var(--color-line)] bg-white p-4">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2 text-xs text-[var(--color-mute)]">
            <span className="inline-flex items-center rounded-full border border-[var(--color-line)] bg-[var(--color-bg-2)] px-2 py-0.5 font-medium text-[var(--color-ink-2)]">
              {result.forum_level.replace(/_/g, " ")}
            </span>
            <span>{result.court_name}</span>
            {result.bench_name ? <span>· {result.bench_name}</span> : null}
            <span>· {dateLabel}</span>
            {result.case_reference ? (
              <span className="font-mono">· {result.case_reference}</span>
            ) : null}
            {result.neutral_citation ? (
              <span className="font-mono">· {result.neutral_citation}</span>
            ) : null}
            <span>· Publisher: {result.source}</span>
            <span>· score {result.score}</span>
          </div>
          {/* PG-006 Phase 1B (2026-05-01) — good-law badge. Renders only
              when an authority has at least one adverse incoming
              citation in the corpus. Tone matches severity (overruled =
              red-strong, reversed = red-soft, doubted = amber). The
              count tells lawyers how widely the criticism has spread. */}
          {result.worst_treatment ? (
            <TreatmentBadge
              treatment={result.worst_treatment}
              count={result.adverse_count}
            />
          ) : null}
          <h3 className="mt-1 text-base font-semibold text-[var(--color-ink)]">
            {result.title}
          </h3>
          {result.summary ? (
            <p className="mt-1 text-xs italic text-[var(--color-mute)]">
              {result.summary}
            </p>
          ) : null}
          {result.relevance_reason ? (
            <p
              className="mt-2 rounded-[var(--radius-md)] border border-[var(--color-line)] bg-[var(--color-bg-2)] px-3 py-2 text-xs text-[var(--color-ink-2)]"
              data-testid="research-result-relevance"
            >
              {result.relevance_reason}
            </p>
          ) : null}
          {/* BUG-021 (Ram 2026-04-26): older HC PDFs in our corpus
              have low-quality OCR producing mojibake (replacement
              chars, control bytes, mixed-script garbage). Rendering
              raw makes the result look broken. Detect garbled
              snippets and render an actionable placeholder instead.
              The corpus-side fix (rapidocr re-ingest) is queued
              separately. */}
          {isGarbledSnippet(result.snippet) ? (
            <p
              className="mt-2 rounded-[var(--radius-md)] border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900"
              data-testid="research-result-garbled"
            >
              The source PDF text isn&apos;t legible enough to preview here
              (low-quality OCR on the original). Open the source link below to
              read the authoritative text.
            </p>
          ) : (
            <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-[var(--color-ink-2)]">
              {result.snippet}
            </p>
          )}
          {result.matched_terms.length > 0 ? (
            <div className="mt-2 flex flex-wrap gap-1">
              {result.matched_terms.slice(0, 8).map((term) => (
                <span
                  key={term}
                  className="inline-flex items-center rounded-full bg-[var(--color-brand-50)] px-2 py-0.5 text-[11px] font-medium text-[var(--color-brand-700)]"
                >
                  {term}
                </span>
              ))}
            </div>
          ) : null}
        </div>
        <div className="flex flex-col gap-2">
          <SourceAction
            action={result.source_action}
            compact
            originSurface="research"
          />
          {canAnnotate ? (
            <Button
              size="sm"
              variant={saved ? "secondary" : "outline"}
              disabled={saved || saving}
              onClick={onSave}
              data-testid={`research-save-${result.authority_document_id}`}
            >
              {saving ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              ) : (
                <Bookmark className="h-4 w-4" aria-hidden />
              )}
              {saved ? "Saved" : "Save"}
            </Button>
          ) : null}
        </div>
      </div>
    </li>
  );
}

function TreatmentBadge({
  treatment,
  count,
}: {
  treatment: NonNullable<AuthoritySearchResult["worst_treatment"]>;
  count: number;
}) {
  const tone =
    treatment === "overruled"
      ? "border-red-300 bg-red-50 text-red-800"
      : treatment === "reversed"
        ? "border-red-300 bg-red-50 text-red-800"
        : "border-amber-300 bg-amber-50 text-amber-900";

  const label =
    treatment === "overruled"
      ? "Overruled"
      : treatment === "reversed"
        ? "Reversed"
        : "Doubted";

  return (
    <span
      data-testid={`research-treatment-${treatment}`}
      className={`mt-1 inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide ${tone}`}
      title={`${label} by ${count} later case${count === 1 ? "" : "s"} in the indexed corpus. Verify before relying on the holding.`}
    >
      {label}
      <span className="rounded-full bg-white/70 px-1.5 py-0 text-[10px] font-medium">
        {count}
      </span>
    </span>
  );
}
