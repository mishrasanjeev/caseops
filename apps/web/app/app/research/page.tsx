"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import {
  Bookmark,
  LibraryBig,
  Loader2,
  Scale,
  Search,
  SlidersHorizontal,
} from "lucide-react";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/Select";
import { ApiError } from "@/lib/api/config";
import {
  type AuthorityDocumentType,
  type AuthorityForumLevel,
  type AuthoritySearchResult,
  createAuthorityAnnotation,
  fetchAuthorityCorpusStats,
  searchAuthorities,
} from "@/lib/api/endpoints";
import { useCapability } from "@/lib/capabilities";
import { formatLegalDate } from "@/lib/dates";

type ForumFilter = "any" | AuthorityForumLevel;
type DocTypeFilter = "any" | AuthorityDocumentType;

export default function ResearchPage() {
  const canSearch = useCapability("authorities:search");
  const canAnnotate = useCapability("authorities:annotate");
  const searchParams = useSearchParams();
  const initialQuery = searchParams?.get("q")?.trim() ?? "";
  const [query, setQuery] = useState(initialQuery);
  const [pendingQuery, setPendingQuery] = useState(
    initialQuery.length >= 2 ? initialQuery : "",
  );

  // When the user arrives via the topbar search (?q=...), re-sync local
  // state + fire the query if a new ?q= lands while we're on the page.
  useEffect(() => {
    const nextQ = searchParams?.get("q")?.trim() ?? "";
    if (nextQ && nextQ !== pendingQuery) {
      setQuery(nextQ);
      if (nextQ.length >= 2) setPendingQuery(nextQ);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);
  const [forumLevel, setForumLevel] = useState<ForumFilter>("any");
  const [courtName, setCourtName] = useState("");
  const [documentType, setDocumentType] = useState<DocTypeFilter>("any");
  const [savedAuthorityIds, setSavedAuthorityIds] = useState<Set<string>>(
    () => new Set(),
  );

  const statsQuery = useQuery({
    queryKey: ["authorities", "stats"],
    queryFn: () => fetchAuthorityCorpusStats(),
    enabled: canSearch,
    staleTime: 5 * 60 * 1000,
  });

  const searchQuery = useQuery({
    queryKey: [
      "authorities",
      "search",
      { q: pendingQuery, forumLevel, courtName, documentType },
    ],
    queryFn: () =>
      searchAuthorities({
        query: pendingQuery,
        limit: 10,
        forumLevel: forumLevel === "any" ? null : forumLevel,
        courtName: courtName.trim() || null,
        documentType: documentType === "any" ? null : documentType,
      }),
    enabled: canSearch && pendingQuery.trim().length >= 2,
  });

  const saveMutation = useMutation({
    mutationFn: (input: AuthoritySearchResult) =>
      createAuthorityAnnotation({
        authorityId: input.authority_document_id,
        kind: "flag",
        title:
          pendingQuery.length > 0
            ? `Research: ${pendingQuery.slice(0, 200)}`
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
      toast.error(err instanceof ApiError ? err.detail : "Could not save that authority.");
    },
  });

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    const trimmed = query.trim();
    if (trimmed.length < 2) {
      toast.error("Type at least two characters to search.");
      return;
    }
    setPendingQuery(trimmed);
  };

  const results = searchQuery.data?.results ?? [];
  const hasSearched = pendingQuery.length > 0;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Research"
        title="Grounded legal research"
        description={
          statsQuery.data
            ? `Searching ${statsQuery.data.document_count.toLocaleString()} judgments across SC + HCs. Every result links to source.`
            : "Hybrid retrieval across statutes, judgments, and your own precedents — every answer cited and traceable."
        }
      />

      <Card>
        <CardHeader>
          <CardTitle as="h2" className="text-base">
            Find authorities
          </CardTitle>
          <CardDescription>
            Use natural language. Filters narrow by court, forum, and document type.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="flex flex-col gap-3">
            <div className="flex items-center gap-2">
              <Search className="h-4 w-4 text-[var(--color-mute)]" aria-hidden />
              <Input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Triple test for bail under BNSS s.483; parity; custody duration"
                aria-label="Research query"
                data-testid="research-query-input"
                className="flex-1"
              />
              <Button
                type="submit"
                size="sm"
                disabled={!canSearch || searchQuery.isFetching}
                data-testid="research-query-submit"
              >
                {searchQuery.isFetching ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Searching…
                  </>
                ) : (
                  <>
                    <Search className="h-4 w-4" aria-hidden /> Search
                  </>
                )}
              </Button>
            </div>
            <div className="grid gap-3 md:grid-cols-3">
              <div className="flex flex-col gap-1">
                <Label htmlFor="forum-filter" className="text-xs">
                  <SlidersHorizontal className="mr-1 inline h-3 w-3" aria-hidden /> Forum
                </Label>
                <Select
                  value={forumLevel}
                  onValueChange={(value) => setForumLevel(value as ForumFilter)}
                >
                  <SelectTrigger id="forum-filter">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="any">Any forum</SelectItem>
                    <SelectItem value="supreme_court">Supreme Court</SelectItem>
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
                  onValueChange={(value) => setDocumentType(value as DocTypeFilter)}
                >
                  <SelectTrigger id="doctype-filter">
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
          </form>
        </CardContent>
      </Card>

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
      ) : searchQuery.isPending || searchQuery.isFetching ? (
        <EmptyState
          icon={Loader2}
          title="Searching the corpus…"
          description="Hybrid retrieval across judgments, statutes, and your tenant overlay."
        />
      ) : searchQuery.isError ? (
        <EmptyState
          icon={Scale}
          title="Search failed"
          description={
            searchQuery.error instanceof ApiError
              ? searchQuery.error.detail
              : "Try again in a moment."
          }
        />
      ) : results.length === 0 ? (
        <EmptyState
          icon={Scale}
          title="No authorities matched"
          description="Broaden your filters or rephrase the query. The corpus is still growing."
        />
      ) : (
        <ul className="flex flex-col gap-3" data-testid="research-results">
          {results.map((result) => (
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
      )}
    </div>
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
            <span>· score {result.score}</span>
          </div>
          <h3 className="mt-1 text-base font-semibold text-[var(--color-ink)]">
            {result.title}
          </h3>
          {result.summary ? (
            <p className="mt-1 text-xs italic text-[var(--color-mute)]">
              {result.summary}
            </p>
          ) : null}
          <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-[var(--color-ink-2)]">
            {result.snippet}
          </p>
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
