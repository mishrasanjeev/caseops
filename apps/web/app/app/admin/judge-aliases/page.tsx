"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Combine, Gavel, Languages, RefreshCw, ShieldAlert, Split } from "lucide-react";
import Link from "next/link";
import { useDeferredValue, useId, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Input";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/Tabs";
import { Textarea } from "@/components/ui/Textarea";
import {
  type BenchIdentityRecord,
  createBenchAlias,
  createJudgeAlias,
  listCuratorBenches,
  listCuratorJudges,
  listJudgeAliases,
  listJudgeMappingReviews,
  mergeJudgeIdentities,
  reprocessJudgeAuthority,
  resolveJudgeMappingReview,
  type JudgeAliasRecord,
  type JudgeIdentityRecord,
  type JudgeMappingReview,
} from "@/lib/api/endpoints";
import { apiErrorMessage } from "@/lib/api/config";
import { useCapability } from "@/lib/capabilities";

const FIELD_CLASS =
  "flex min-w-0 flex-col gap-1 text-xs font-medium text-[var(--color-ink-2)]";
const SELECT_CLASS =
  "h-10 w-full min-w-0 rounded-md border border-[var(--color-line)] bg-white px-3 text-sm text-[var(--color-ink)]";

export default function JudgeAliasesAdminPage() {
  const canCurate = useCapability("court_sync:run");
  const queryClient = useQueryClient();
  const [judgeCatalogSearch, setJudgeCatalogSearch] = useState("");
  const [benchCatalogSearch, setBenchCatalogSearch] = useState("");
  const deferredJudgeSearch = useDeferredValue(judgeCatalogSearch.trim());
  const deferredBenchSearch = useDeferredValue(benchCatalogSearch.trim());
  const aliasesQuery = useQuery({
    queryKey: ["admin", "judge-aliases"],
    queryFn: listJudgeAliases,
    staleTime: 5 * 60_000,
  });
  const reviewsQuery = useQuery({
    queryKey: ["admin", "judge-mapping-reviews", "open"],
    queryFn: () => listJudgeMappingReviews("open", 100),
    enabled: canCurate,
  });
  const judgesQuery = useQuery({
    queryKey: ["admin", "judge-curator-catalog", deferredJudgeSearch],
    queryFn: () =>
      listCuratorJudges({ q: deferredJudgeSearch || undefined, limit: 200 }),
    enabled: canCurate,
    staleTime: 5 * 60_000,
  });
  const benchesQuery = useQuery({
    queryKey: ["admin", "bench-curator-catalog", deferredBenchSearch],
    queryFn: () =>
      listCuratorBenches({ q: deferredBenchSearch || undefined, limit: 200 }),
    enabled: canCurate,
    staleTime: 5 * 60_000,
  });

  const refreshCuratorData = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["admin", "judge-aliases"] }),
      queryClient.invalidateQueries({ queryKey: ["admin", "judge-mapping-reviews"] }),
      queryClient.invalidateQueries({ queryKey: ["admin", "judge-curator-catalog"] }),
      queryClient.invalidateQueries({ queryKey: ["admin", "bench-curator-catalog"] }),
    ]);
  };

  if (aliasesQuery.isPending) {
    return (
      <div className="flex flex-col gap-3">
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }
  if (aliasesQuery.isError) {
    return (
      <QueryErrorState
        title="Could not load judge aliases"
        error={aliasesQuery.error}
        onRetry={() => aliasesQuery.refetch()}
      />
    );
  }
  const aliases = aliasesQuery.data;
  if (!aliases) return null;

  const grouped = new Map<string, JudgeAliasRecord[]>();
  for (const alias of aliases.aliases) {
    const key = `${alias.court_short_name}\u2003${alias.judge_full_name}`;
    grouped.set(key, [...(grouped.get(key) ?? []), alias]);
  }

  return (
    <div className="flex min-w-0 flex-col gap-6">
      <PageHeader
        eyebrow="Admin · Mapping curator"
        title="Judge aliases"
        description={`${aliases.alias_count} aliases across ${aliases.judge_count} canonical judges, with collision review and reprocessing controls.`}
      />

      {!canCurate ? (
        <div className="flex min-w-0 flex-col gap-6">
          <EmptyState
            icon={ShieldAlert}
            title="Curator access required"
            description="The alias catalog is available for audit. Mapping changes require the court sync capability."
          />
          <AliasCatalog grouped={grouped} />
        </div>
      ) : (
        <Tabs defaultValue="reviews" className="min-w-0">
          <TabsList className="h-auto w-full min-w-0 flex-wrap justify-start">
            <TabsTrigger value="reviews">Review queue</TabsTrigger>
            <TabsTrigger value="aliases">Aliases</TabsTrigger>
            <TabsTrigger value="merge">Merge duplicates</TabsTrigger>
            <TabsTrigger value="reprocess">Reprocess</TabsTrigger>
          </TabsList>

          <TabsContent value="reviews">
            <ReviewQueue
              reviews={reviewsQuery.data?.reviews ?? []}
              isPending={reviewsQuery.isPending}
              error={reviewsQuery.error}
              onRetry={() => reviewsQuery.refetch()}
              onChanged={refreshCuratorData}
            />
          </TabsContent>

          <TabsContent value="aliases" className="flex min-w-0 flex-col gap-6">
            <AliasForms
              judges={judgesQuery.data?.judges ?? []}
              benches={benchesQuery.data?.benches ?? []}
              judgeStatus={catalogStatus(judgesQuery, deferredJudgeSearch)}
              benchStatus={{
                ...catalogStatus(benchesQuery, deferredBenchSearch),
                courtsWithoutEntries: benchesQuery.data?.courts_without_benches ?? [],
                courtsWithoutEntriesTotal: benchesQuery.data?.courts_without_benches_total ?? 0,
              }}
              judgeSearch={judgeCatalogSearch}
              benchSearch={benchCatalogSearch}
              onJudgeSearch={setJudgeCatalogSearch}
              onBenchSearch={setBenchCatalogSearch}
              onChanged={refreshCuratorData}
            />
            <AliasCatalog grouped={grouped} />
          </TabsContent>

          <TabsContent value="merge">
            <MergeForm
              judges={judgesQuery.data?.judges ?? []}
              status={catalogStatus(judgesQuery, deferredJudgeSearch)}
              search={judgeCatalogSearch}
              onSearch={setJudgeCatalogSearch}
              onChanged={refreshCuratorData}
            />
          </TabsContent>

          <TabsContent value="reprocess">
            <ReprocessForm onChanged={refreshCuratorData} />
          </TabsContent>
        </Tabs>
      )}
    </div>
  );
}

function ReviewQueue({
  reviews,
  isPending,
  error,
  onRetry,
  onChanged,
}: {
  reviews: JudgeMappingReview[];
  isPending: boolean;
  error: unknown;
  onRetry: () => void;
  onChanged: () => Promise<void>;
}) {
  const [selections, setSelections] = useState<Record<string, string>>({});
  const [notes, setNotes] = useState<Record<string, string>>({});
  const mutation = useMutation({
    mutationFn: (review: JudgeMappingReview) =>
      resolveJudgeMappingReview(review.id, {
        judge_id: selections[review.id] ?? "",
        expected_record_version: review.record_version,
        note: notes[review.id] ?? "",
      }),
    onSuccess: async () => {
      toast.success("Mapping evidence resolved.");
      await onChanged();
    },
    onError: (mutationError) =>
      toast.error(apiErrorMessage(mutationError, "Could not resolve mapping evidence.")),
  });

  if (isPending) return <Skeleton className="h-64 w-full" />;
  if (error) {
    return (
      <QueryErrorState
        title="Could not load mapping reviews"
        error={error}
        onRetry={onRetry}
      />
    );
  }
  if (reviews.length === 0) {
    return (
      <EmptyState
        icon={Gavel}
        title="No open mapping reviews"
        description="Unresolved names and alias collisions will appear here."
      />
    );
  }
  return (
    <ul className="divide-y divide-[var(--color-line)] border-y border-[var(--color-line)]">
      {reviews.map((review) => (
        <li
          key={review.id}
          className="grid min-w-0 gap-4 py-5 lg:grid-cols-[minmax(0,1fr)_minmax(18rem,0.8fr)]"
        >
          <div className="min-w-0">
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <span className="text-sm font-semibold text-[var(--color-ink)]">
                {review.raw_judge_name}
              </span>
              <span className="rounded border border-[var(--color-line)] px-1.5 py-0.5 text-[10px] uppercase text-[var(--color-mute)]">
                {review.reason.replace(/_/g, " ")}
              </span>
            </div>
            <div className="mt-1 text-sm text-[var(--color-ink-2)]">
              {review.authority_title}
            </div>
            <div className="mt-1 flex flex-wrap gap-2 text-xs text-[var(--color-mute)]">
              <span>{review.court_name ?? "Court unresolved"}</span>
              <span>Evidence slot {review.source_ordinal + 1}</span>
              <span>Version {review.record_version}</span>
            </div>
          </div>
          <div className="grid min-w-0 gap-3">
            <ReviewJudgeSelect
              review={review}
              value={selections[review.id] ?? ""}
              onChange={(value) =>
                setSelections((current) => ({ ...current, [review.id]: value }))
              }
            />
            <label className={FIELD_CLASS}>
              Resolution note
              <Textarea
                value={notes[review.id] ?? ""}
                onChange={(event) =>
                  setNotes((current) => ({
                    ...current,
                    [review.id]: event.target.value,
                  }))
                }
                minLength={8}
                maxLength={1000}
              />
            </label>
            <div className="flex justify-end">
              <Button
                type="button"
                disabled={
                  mutation.isPending ||
                  !selections[review.id] ||
                  (notes[review.id]?.trim().length ?? 0) < 8
                }
                onClick={() => mutation.mutate(review)}
              >
                <Split className="h-4 w-4" aria-hidden /> Resolve evidence
              </Button>
            </div>
          </div>
        </li>
      ))}
    </ul>
  );
}

function ReviewJudgeSelect({
  review,
  value,
  onChange,
}: {
  review: JudgeMappingReview;
  value: string;
  onChange: (value: string) => void;
}) {
  const [search, setSearch] = useState("");
  const deferredSearch = useDeferredValue(search.trim());
  const catalogQuery = useQuery({
    queryKey: [
      "admin",
      "judge-review-catalog",
      review.court_id,
      deferredSearch,
    ],
    queryFn: () =>
      listCuratorJudges({
        courtId: review.court_id ?? undefined,
        q: deferredSearch,
        limit: 100,
      }),
    enabled: Boolean(review.court_id && deferredSearch.length >= 2),
  });
  const options = new Map<string, { id: string; label: string }>();
  for (const candidate of review.candidates) {
    options.set(candidate.id, { id: candidate.id, label: candidate.full_name });
  }
  for (const judge of catalogQuery.data?.judges ?? []) {
    options.set(judge.id, { id: judge.id, label: judge.full_name });
  }
  return (
    <div className="grid min-w-0 gap-2">
      <label className={FIELD_CLASS}>
        Search canonical judges
        <Input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          maxLength={120}
          disabled={!review.court_id}
        />
      </label>
      <CatalogSelect
        label="Canonical judge"
        value={value}
        onChange={onChange}
        options={Array.from(options.values())}
        status={
          catalogQuery.data || catalogQuery.error || catalogQuery.fetchStatus !== "idle"
            ? catalogStatus(catalogQuery, deferredSearch)
            : {
                // Nothing searched yet: the review's own candidates are the options.
                isPending: false,
                error: null,
                onRetry: () => undefined,
                search: "",
                totalCount: review.candidates.length,
                hasMore: false,
              }
        }
        noun={{
          ...JUDGE_NOUN,
          searchHint: "Type at least two letters of the name to search this court's judges.",
          emptyCatalog: review.court_id
            ? "No candidate judge for this evidence. Type at least two letters of the name to search this court's canonical judges."
            : "This evidence has no resolved court, so no canonical judge can be offered. Reprocess the authority once its court is catalogued.",
        }}
        testId={`review-catalog-${review.id}`}
      />
    </div>
  );
}

function AliasForms({
  judges,
  benches,
  judgeStatus,
  benchStatus,
  judgeSearch,
  benchSearch,
  onJudgeSearch,
  onBenchSearch,
  onChanged,
}: {
  judges: JudgeIdentityRecord[];
  benches: BenchIdentityRecord[];
  judgeStatus: CatalogStatus;
  benchStatus: CatalogStatus;
  judgeSearch: string;
  benchSearch: string;
  onJudgeSearch: (value: string) => void;
  onBenchSearch: (value: string) => void;
  onChanged: () => Promise<void>;
}) {
  const [judgeId, setJudgeId] = useState("");
  const [judgeAlias, setJudgeAlias] = useState("");
  const [judgeSourceUrl, setJudgeSourceUrl] = useState("");
  const [benchId, setBenchId] = useState("");
  const [benchAlias, setBenchAlias] = useState("");
  const [benchSourceUrl, setBenchSourceUrl] = useState("");
  const judgeMutation = useMutation({
    mutationFn: () =>
      createJudgeAlias(judgeId, {
        alias_text: judgeAlias,
        source: "manual_curator",
        source_url: judgeSourceUrl || null,
        source_evidence_text: "Curator-confirmed identity alias.",
      }),
    onSuccess: async () => {
      setJudgeAlias("");
      toast.success("Judge alias added.");
      await onChanged();
    },
    onError: (error) =>
      toast.error(apiErrorMessage(error, "Could not add judge alias.")),
  });
  const benchMutation = useMutation({
    mutationFn: () =>
      createBenchAlias(benchId, {
        alias_text: benchAlias,
        source: "manual_curator",
        source_url: benchSourceUrl || null,
      }),
    onSuccess: async () => {
      setBenchAlias("");
      toast.success("Bench alias added.");
      await onChanged();
    },
    onError: (error) =>
      toast.error(apiErrorMessage(error, "Could not add bench alias.")),
  });
  return (
    <div className="grid min-w-0 gap-6 lg:grid-cols-2">
      <form
        className="grid min-w-0 gap-3 border-y border-[var(--color-line)] py-5"
        onSubmit={(event) => {
          event.preventDefault();
          judgeMutation.mutate();
        }}
      >
        <h2 className="text-base font-semibold text-[var(--color-ink)]">Judge alias</h2>
        <label className={FIELD_CLASS}>
          Search judges
          <Input
            value={judgeSearch}
            onChange={(event) => onJudgeSearch(event.target.value)}
            maxLength={120}
            placeholder="Judge name or court"
          />
        </label>
        <CatalogSelect
          label="Canonical judge"
          value={judgeId}
          onChange={setJudgeId}
          options={judges.map((judge) => ({ id: judge.id, label: judgeLabel(judge) }))}
          status={judgeStatus}
          noun={JUDGE_NOUN}
          testId="judge-alias-catalog"
        />
        <label className={FIELD_CLASS}>
          Alias
          <Input
            value={judgeAlias}
            onChange={(event) => setJudgeAlias(event.target.value)}
            minLength={2}
            maxLength={255}
          />
        </label>
        <label className={FIELD_CLASS}>
          Official source URL
          <Input
            type="url"
            value={judgeSourceUrl}
            onChange={(event) => setJudgeSourceUrl(event.target.value)}
            maxLength={500}
            required
          />
        </label>
        <div className="flex justify-end">
          <Button
            type="submit"
            disabled={
              !judgeId ||
              judgeAlias.trim().length < 2 ||
              !judgeSourceUrl.trim() ||
              judgeMutation.isPending
            }
          >
            <Languages className="h-4 w-4" aria-hidden /> Add judge alias
          </Button>
        </div>
      </form>

      <form
        className="grid min-w-0 gap-3 border-y border-[var(--color-line)] py-5"
        onSubmit={(event) => {
          event.preventDefault();
          benchMutation.mutate();
        }}
      >
        <h2 className="text-base font-semibold text-[var(--color-ink)]">Bench alias</h2>
        <label className={FIELD_CLASS}>
          Search benches
          <Input
            value={benchSearch}
            onChange={(event) => onBenchSearch(event.target.value)}
            maxLength={120}
            placeholder="Court, seat city or bench"
          />
        </label>
        <CatalogSelect
          label="Canonical bench"
          value={benchId}
          onChange={setBenchId}
          options={benches.map((bench) => ({
            id: bench.id,
            label: `${bench.name} · ${bench.court_short_name}`,
          }))}
          status={benchStatus}
          noun={BENCH_NOUN}
          testId="bench-alias-catalog"
        />
        <label className={FIELD_CLASS}>
          Alias
          <Input
            value={benchAlias}
            onChange={(event) => setBenchAlias(event.target.value)}
            minLength={2}
            maxLength={255}
          />
        </label>
        <label className={FIELD_CLASS}>
          Official source URL
          <Input
            type="url"
            value={benchSourceUrl}
            onChange={(event) => setBenchSourceUrl(event.target.value)}
            maxLength={500}
            required
          />
        </label>
        <div className="flex justify-end">
          <Button
            type="submit"
            disabled={
              !benchId ||
              benchAlias.trim().length < 2 ||
              !benchSourceUrl.trim() ||
              benchMutation.isPending
            }
          >
            <Languages className="h-4 w-4" aria-hidden /> Add bench alias
          </Button>
        </div>
      </form>
    </div>
  );
}

function MergeForm({
  judges,
  status,
  search,
  onSearch,
  onChanged,
}: {
  judges: JudgeIdentityRecord[];
  status: CatalogStatus;
  search: string;
  onSearch: (value: string) => void;
  onChanged: () => Promise<void>;
}) {
  const [sourceId, setSourceId] = useState("");
  const [destinationId, setDestinationId] = useState("");
  const [reason, setReason] = useState("");
  const source = judges.find((judge) => judge.id === sourceId);
  const destination = judges.find((judge) => judge.id === destinationId);
  const mutation = useMutation({
    mutationFn: () =>
      mergeJudgeIdentities(sourceId, {
        destination_judge_id: destinationId,
        expected_source_version: source?.record_version ?? -1,
        expected_destination_version: destination?.record_version ?? -1,
        reason,
      }),
    onSuccess: async () => {
      setSourceId("");
      setDestinationId("");
      setReason("");
      toast.success("Duplicate judge identities merged.");
      await onChanged();
    },
    onError: (error) =>
      toast.error(apiErrorMessage(error, "Could not merge judge identities.")),
  });
  const options = judges.map((judge) => ({
    id: judge.id,
    label: `${judgeLabel(judge)} · v${judge.record_version}`,
  }));
  return (
    <form
      className="grid min-w-0 gap-4 border-y border-[var(--color-line)] py-6 lg:grid-cols-2"
      onSubmit={(event) => {
        event.preventDefault();
        mutation.mutate();
      }}
    >
      <label className={`${FIELD_CLASS} lg:col-span-2`}>
        Search judges
        <Input
          value={search}
          onChange={(event) => onSearch(event.target.value)}
          maxLength={120}
        />
      </label>
      <CatalogSelect
        label="Duplicate identity"
        value={sourceId}
        onChange={setSourceId}
        options={options}
        status={status}
        noun={JUDGE_NOUN}
        testId="merge-source-catalog"
      />
      <CatalogSelect
        label="Canonical destination"
        value={destinationId}
        onChange={setDestinationId}
        options={options.filter((option) => option.id !== sourceId)}
        status={status}
        noun={JUDGE_NOUN}
        testId="merge-destination-catalog"
      />
      <label className={`${FIELD_CLASS} lg:col-span-2`}>
        Merge reason
        <Textarea
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          minLength={8}
          maxLength={1000}
        />
      </label>
      <div className="flex justify-end lg:col-span-2">
        <Button
          type="submit"
          disabled={
            !source ||
            !destination ||
            source.id === destination.id ||
            reason.trim().length < 8 ||
            mutation.isPending
          }
        >
          <Combine className="h-4 w-4" aria-hidden /> Merge identities
        </Button>
      </div>
    </form>
  );
}

function ReprocessForm({ onChanged }: { onChanged: () => Promise<void> }) {
  const [authorityId, setAuthorityId] = useState("");
  const mutation = useMutation({
    mutationFn: () => reprocessJudgeAuthority(authorityId),
    onSuccess: async (result) => {
      toast.success(
        `Remapped ${result.mapped}; ${result.collisions} collisions; ${result.unresolved} unresolved.`,
      );
      await onChanged();
    },
    onError: (error) =>
      toast.error(apiErrorMessage(error, "Could not reprocess authority mapping.")),
  });
  return (
    <form
      className="grid min-w-0 gap-4 border-y border-[var(--color-line)] py-6 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end"
      onSubmit={(event) => {
        event.preventDefault();
        mutation.mutate();
      }}
    >
      <label className={FIELD_CLASS}>
        Authority document ID
        <Input
          value={authorityId}
          onChange={(event) => setAuthorityId(event.target.value)}
          maxLength={36}
        />
      </label>
      <Button type="submit" disabled={!authorityId.trim() || mutation.isPending}>
        <RefreshCw className="h-4 w-4" aria-hidden /> Reprocess mapping
      </Button>
    </form>
  );
}

function AliasCatalog({ grouped }: { grouped: Map<string, JudgeAliasRecord[]> }) {
  if (grouped.size === 0) {
    return (
      <EmptyState
        icon={Languages}
        title="No aliases recorded yet"
        description="The canonical alias catalog is empty."
      />
    );
  }
  return (
    <ul
      className="divide-y divide-[var(--color-line)] border-y border-[var(--color-line)]"
      data-testid="judge-aliases-list"
    >
      {Array.from(grouped.entries()).map(([key, aliases]) => {
        const first = aliases[0];
        return (
          <li
            key={key}
            className="grid min-w-0 gap-3 py-4 sm:grid-cols-[minmax(12rem,0.65fr)_minmax(0,1fr)]"
            data-testid={`judge-aliases-card-${first.judge_id}`}
          >
            <div className="min-w-0">
              <Link
                href={`/app/courts/judges/${first.judge_id}`}
                className="text-sm font-semibold text-[var(--color-ink)] hover:underline"
              >
                {first.judge_full_name}
              </Link>
              <div className="mt-1 text-xs text-[var(--color-mute)]">
                {first.court_short_name}
              </div>
            </div>
            <ul className="flex min-w-0 flex-wrap gap-1.5">
              {aliases.map((alias) => (
                <li
                  key={alias.id}
                  className="max-w-full rounded-md border border-[var(--color-line)] bg-white px-2 py-1 text-xs"
                >
                  <span className="break-words text-[var(--color-ink-2)]">
                    {alias.alias_text}
                  </span>
                  <span className="ml-1.5 text-[10px] text-[var(--color-mute-2)]">
                    ({alias.source})
                  </span>
                </li>
              ))}
            </ul>
          </li>
        );
      })}
    </ul>
  );
}

type CatalogStatus = {
  isPending: boolean;
  error: unknown;
  onRetry: () => void;
  search: string;
  totalCount: number;
  hasMore: boolean;
  // Bench catalogue only: courts the search names that hold no catalogued
  // seat, as reported by the server with the same search.
  courtsWithoutEntries?: { id: string; name: string }[];
  courtsWithoutEntriesTotal?: number;
};

type CatalogNoun = {
  singular: string;
  plural: string;
  searchHint: string;
  emptyCatalog: string;
  courtNotCatalogued?: string;
};

// Benches and judges are shared, server-owned catalogues. The picker states
// why it is empty (nothing catalogued, nothing matches, or a failed read) and
// how many rows the server holds, so an empty list is never a silent dead end.
const BENCH_NOUN: CatalogNoun = {
  singular: "canonical bench",
  plural: "canonical benches",
  searchHint:
    "Search by court (Delhi), seat city (Nagpur) or bench name. A court that sits " +
    "only at its principal seat lists one Principal Seat.",
  emptyCatalog:
    "No canonical benches are catalogued yet. Benches are a shared catalogue taken " +
    "from official court sources and added with platform releases; ask your platform " +
    "administrator to have the court's seats catalogued.",
  courtNotCatalogued:
    "Its seats have not been catalogued from an official court source yet, so no bench " +
    "alias can be added for it. Ask your platform administrator to have its benches " +
    "catalogued; do not record its aliases against another court's bench.",
};

const JUDGE_NOUN: CatalogNoun = {
  singular: "canonical judge",
  plural: "canonical judges",
  searchHint: "Search by judge name or court.",
  emptyCatalog:
    "No canonical judges are catalogued yet. Judge identities come from official court " +
    "rosters through the court sync and judge refresh jobs.",
};

function judgeLabel(judge: JudgeIdentityRecord): string {
  return `${judge.full_name} · ${judge.court_short_name ?? judge.court_id}`;
}

function catalogStatus(
  query: {
    isPending: boolean;
    error: unknown;
    refetch: () => unknown;
    data?: { returned_count: number; total_count?: number; has_more: boolean };
  },
  search: string,
): CatalogStatus {
  return {
    isPending: query.isPending,
    error: query.error,
    onRetry: () => void query.refetch(),
    search,
    totalCount: query.data?.total_count ?? query.data?.returned_count ?? 0,
    hasMore: query.data?.has_more ?? false,
  };
}

function uncataloguedCourtNames(status: CatalogStatus): string {
  const courts = status.courtsWithoutEntries ?? [];
  const total = Math.max(status.courtsWithoutEntriesTotal ?? 0, courts.length);
  const names = courts.map((court) => court.name).join(", ");
  return total > courts.length ? `${names} and ${total - courts.length} more` : names;
}

function catalogMessage(
  status: CatalogStatus,
  noun: CatalogNoun,
  optionCount: number,
): string {
  if (status.isPending) return `Loading ${noun.plural}…`;
  if (status.error) return `The ${noun.plural} could not be loaded.`;
  if (optionCount === 0) {
    if (noun.courtNotCatalogued && (status.courtsWithoutEntries ?? []).length > 0) {
      return `No ${noun.plural} are catalogued for ${uncataloguedCourtNames(status)} yet. ${noun.courtNotCatalogued}`;
    }
    return status.search
      ? `No ${noun.singular} matches “${status.search}”. ${noun.searchHint}`
      : noun.emptyCatalog;
  }
  if (status.hasMore) {
    return `Showing ${optionCount} of ${status.totalCount} ${noun.plural}. Refine the search to reach the rest.`;
  }
  return `${optionCount} of ${Math.max(status.totalCount, optionCount)} ${noun.plural} shown. ${noun.searchHint}`;
}

function CatalogSelect({
  label,
  value,
  onChange,
  options,
  status,
  noun,
  testId,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: { id: string; label: string }[];
  status: CatalogStatus;
  noun: CatalogNoun;
  testId: string;
}) {
  const controlId = useId();
  const statusId = useId();
  const placeholder = status.isPending
    ? `Loading ${noun.plural}…`
    : status.error
      ? `Could not load ${noun.plural}`
      : options.length === 0
        ? `No matching ${noun.plural}`
        : "Select";
  return (
    <div className={FIELD_CLASS}>
      <label htmlFor={controlId}>{label}</label>
      <select
        id={controlId}
        className={SELECT_CLASS}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        aria-describedby={statusId}
        data-testid={`${testId}-select`}
      >
        <option value="">{placeholder}</option>
        {options.map((option) => (
          <option key={option.id} value={option.id}>
            {option.label}
          </option>
        ))}
      </select>
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <p
          id={statusId}
          role="status"
          data-testid={`${testId}-status`}
          className={`min-w-0 font-normal ${
            status.error ? "text-[var(--color-danger-700)]" : "text-[var(--color-mute)]"
          }`}
        >
          {catalogMessage(status, noun, options.length)}
        </p>
        {!status.isPending &&
        !status.error &&
        options.length > 0 &&
        noun.courtNotCatalogued &&
        (status.courtsWithoutEntries ?? []).length > 0 ? (
          <p
            data-testid={`${testId}-uncatalogued`}
            className="min-w-0 font-normal text-[var(--color-mute)]"
          >
            {`No ${noun.plural} are catalogued yet for ${uncataloguedCourtNames(status)}.`}
          </p>
        ) : null}
        {status.error ? (
          <Button type="button" variant="ghost" size="sm" onClick={status.onRetry}>
            <RefreshCw className="h-3.5 w-3.5" aria-hidden /> Retry
          </Button>
        ) : null}
      </div>
    </div>
  );
}
