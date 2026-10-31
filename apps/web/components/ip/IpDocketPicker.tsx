"use client";

import { keepPreviousData, useInfiniteQuery, useQuery } from "@tanstack/react-query";
import type { InfiniteData, UseInfiniteQueryResult } from "@tanstack/react-query";
import Link from "next/link";
import { useEffect, useId, useMemo, useState } from "react";
import type { ChangeEvent } from "react";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { RecordSelect } from "@/components/ui/RecordSelect";
import { isApiErrorShape } from "@/lib/api/config";
import {
  fetchIpDocket,
  fetchIpDockets,
  type IpDocket,
  type IpDocketListPage,
} from "@/lib/api/endpoints";
import { cn } from "@/lib/cn";

/**
 * Choose one IP docket from the whole visible portfolio.
 *
 * A firm can hold thousands of dockets, and GET /api/ip/dockets returns one
 * page at a time. Pickers that rendered only that first page silently hid
 * every older docket (Ram 2026-10-30, BUG-012 adjacent). This picker searches
 * on the server (mark, docket title, application or registration number),
 * pages by cursor, says how many dockets it is showing, and resolves a
 * selected id that is not on the loaded page, such as a `?docket=` deep link.
 *
 * It follows the house record-picker pattern: a search box over a native
 * select (`RecordSelect`), so the browser keeps the list inside the viewport
 * and the complete caption of the chosen docket is shown below the field.
 *
 * Props:
 * - `value` / `onChange(id, docket)`: fully controlled. The picker never
 *   selects a docket on its own; a caller that wants a default (for example a
 *   deep-linked `?docket=`) passes that id as `value`. `docket` is the loaded
 *   record when the user chose it, or null for the empty option.
 * - `label`: visible field label, default "Docket". `searchLabel` overrides
 *   the search box label (default "Find <label>").
 * - `emptyOptionLabel`: offer an explicit, selectable "no docket" choice with
 *   this caption (for example "All accessible dockets"). Without it the empty
 *   option is a disabled "Select a docket" placeholder.
 * - `error`: a field-level message from the caller (validation or API); it
 *   marks the select `aria-invalid` and is announced with it.
 * - `pageSize`: dockets per page, default 50 (server maximum 200).
 * - `id`, `required`, `disabled`, `className` behave as on a form field.
 *
 * Dockets are cached under ["ip", "dockets", ...]: invalidating
 * ["ip", "dockets"] refreshes the picker, and a selected id is read through
 * the same ["ip", "dockets", id] entry the IP docket page uses.
 */
export type IpDocketPickerProps = {
  value: string;
  onChange: (docketId: string, docket: IpDocket | null) => void;
  id?: string;
  label?: string;
  searchLabel?: string;
  emptyOptionLabel?: string;
  error?: string | null;
  pageSize?: number;
  required?: boolean;
  disabled?: boolean;
  className?: string;
};

const SEARCH_DEBOUNCE_MS = 300;

type DocketPages = UseInfiniteQueryResult<InfiniteData<IpDocketListPage, unknown>, Error>;

function errorText(error: unknown): string {
  if (isApiErrorShape(error) && error.detail.trim()) return error.detail;
  if (error instanceof Error && error.message.trim()) return error.message;
  return "Request failed.";
}

function isHidden(error: unknown): boolean {
  return isApiErrorShape(error) && (error.status === 404 || error.status === 403);
}

const RECORD_TYPE_LABELS: Record<string, string> = {
  international_registration: "International registration",
  international_designation: "International designation",
};

/** One line that tells two dockets apart: title, primary identifier, kind. */
export function ipDocketCaption(
  docket: Pick<IpDocket, "title" | "primary_identifier" | "record_type">,
): string {
  return [
    docket.title,
    docket.primary_identifier ?? "No primary identifier",
    RECORD_TYPE_LABELS[docket.record_type],
  ]
    .filter(Boolean)
    .join(" · ");
}

export function IpDocketPicker({
  value,
  onChange,
  id,
  label = "Docket",
  searchLabel,
  emptyOptionLabel,
  error,
  pageSize = 50,
  required,
  disabled,
  className,
}: IpDocketPickerProps) {
  const generatedId = useId();
  const selectId = id ?? `ip-docket-picker-${generatedId.replace(/:/g, "")}`;
  const searchId = `${selectId}-search`;
  const statusId = `${selectId}-status`;
  const errorId = `${selectId}-error`;
  const lookupErrorId = `${selectId}-selected-error`;

  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  useEffect(() => {
    const handle = window.setTimeout(() => setQuery(search.trim()), SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(handle);
  }, [search]);

  const results = useInfiniteQuery({
    queryKey: ["ip", "dockets", "picker", { query, pageSize }],
    queryFn: ({ pageParam, signal }) =>
      fetchIpDockets({ query, cursor: pageParam, limit: pageSize, signal }),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor ?? null,
    placeholderData: keepPreviousData,
  });
  const loaded = useMemo(
    () => results.data?.pages.flatMap((page) => page.dockets) ?? [],
    [results.data],
  );
  const pages = results.data?.pages ?? [];
  const lastPage = pages[pages.length - 1];
  const total = results.data?.pages[0]?.total_count ?? loaded.length;

  // The chosen docket stays an option when a later search no longer returns it.
  const [chosen, setChosen] = useState<IpDocket | null>(null);
  const loadedSelection = value ? loaded.find((docket) => docket.id === value) : undefined;
  const lookupNeeded = Boolean(value) && !loadedSelection && chosen?.id !== value;
  const lookup = useQuery({
    queryKey: ["ip", "dockets", value],
    queryFn: () => fetchIpDocket(value),
    enabled: lookupNeeded,
  });
  const selected =
    loadedSelection ??
    (chosen?.id === value ? chosen : null) ??
    (value && lookup.data?.id === value ? lookup.data : null);

  const dockets = selected && !loaded.some((docket) => docket.id === selected.id)
    ? [selected, ...loaded]
    : loaded;
  const firstLoad = results.isPending;
  const lookupPending = lookupNeeded && lookup.isPending;
  const lookupFailed = lookupNeeded && lookup.isError;
  const options = [
    {
      value: "",
      label: emptyOptionLabel ?? (firstLoad ? "Loading dockets…" : "Select a docket"),
      disabled: !emptyOptionLabel,
    },
    ...(lookupPending ? [{ value, label: "Loading the selected docket…", disabled: true }] : []),
    ...dockets.map((docket) => ({ value: docket.id, label: ipDocketCaption(docket) })),
  ];
  const nothingToChoose = dockets.length === 0 && !emptyOptionLabel;

  const handleChange = (event: ChangeEvent<HTMLSelectElement>) => {
    const next = event.target.value;
    const docket = dockets.find((row) => row.id === next) ?? null;
    if (docket) setChosen(docket);
    onChange(next, docket);
  };

  const describedBy = [statusId, lookupFailed ? lookupErrorId : null, error ? errorId : null]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={cn("flex min-w-0 flex-col gap-2", className)} data-testid="ip-docket-picker">
      <div className="flex min-w-0 flex-col gap-1.5">
        <Label htmlFor={searchId}>{searchLabel ?? `Find ${label.toLowerCase()}`}</Label>
        <Input
          id={searchId}
          type="search"
          value={search}
          disabled={disabled}
          autoComplete="off"
          placeholder="Mark, docket title, or application number"
          aria-controls={selectId}
          onChange={(event) => setSearch(event.target.value)}
        />
      </div>

      <RecordSelect
        id={selectId}
        label={label}
        value={value}
        options={options}
        required={required}
        disabled={disabled || firstLoad || nothingToChoose}
        aria-invalid={error || lookupFailed ? true : undefined}
        aria-describedby={describedBy}
        onChange={handleChange}
        className="h-10 w-full min-w-0 rounded-md border border-[var(--color-line)] bg-white px-3 text-sm text-[var(--color-ink)] disabled:cursor-not-allowed disabled:opacity-60 aria-[invalid=true]:border-[var(--color-danger-500)]"
      />

      <PickerStatus
        id={statusId}
        results={results}
        loadedCount={loaded.length}
        total={total}
        query={query}
        hasMore={Boolean(lastPage?.next_cursor)}
        searching={results.isPlaceholderData || (search.trim() !== query)}
      />

      {lookupFailed ? (
        <div role="alert" className="flex min-w-0 flex-wrap items-center gap-2 text-sm text-[var(--color-danger-500)]">
          <span id={lookupErrorId} className="min-w-0 break-words">
            {isHidden(lookup.error)
              ? "The selected docket is not available to you or no longer exists."
              : `The selected docket could not be loaded: ${errorText(lookup.error)}`}
          </span>
          {isHidden(lookup.error) ? null : (
            <Button type="button" size="sm" variant="outline" onClick={() => lookup.refetch()}>
              Retry
            </Button>
          )}
          <Button type="button" size="sm" variant="ghost" onClick={() => onChange("", null)}>
            Clear selection
          </Button>
        </div>
      ) : null}

      {error ? (
        <p id={errorId} className="min-w-0 break-words text-sm text-[var(--color-danger-500)]">
          {error}
        </p>
      ) : null}
    </div>
  );
}

function PickerStatus({
  id,
  results,
  loadedCount,
  total,
  query,
  hasMore,
  searching,
}: {
  id: string;
  results: DocketPages;
  loadedCount: number;
  total: number;
  query: string;
  hasMore: boolean;
  searching: boolean;
}) {
  if (results.isPending) {
    return (
      <p id={id} role="status" className="text-sm text-[var(--color-mute)]">
        Loading dockets…
      </p>
    );
  }
  if (results.isError && !results.isFetchNextPageError) {
    return (
      <div id={id} role="alert" className="flex min-w-0 flex-wrap items-center gap-2 text-sm text-[var(--color-danger-500)]">
        <span className="min-w-0 break-words">
          Dockets could not be loaded: {errorText(results.error)}
        </span>
        <Button type="button" size="sm" variant="outline" onClick={() => results.refetch()}>
          Retry
        </Button>
      </div>
    );
  }
  if (loadedCount === 0 && !query) {
    return (
      <div id={id} role="status" className="flex min-w-0 flex-col gap-1 text-sm text-[var(--color-mute)]">
        <span>
          No trademark dockets are visible to you. Dockets restricted to other teams are not
          listed.
        </span>
        <span className="flex flex-wrap gap-x-3 gap-y-1">
          <Link className="font-semibold text-[var(--color-brand-700)]" href="/app/ip">
            Create one in the trademark docket
          </Link>
          <Link className="font-semibold text-[var(--color-brand-700)]" href="/app/ip/portfolio/imports">
            Import a portfolio
          </Link>
        </span>
      </div>
    );
  }
  if (loadedCount === 0) {
    return (
      <p id={id} role="status" className="min-w-0 break-words text-sm text-[var(--color-mute)]">
        {searching
          ? "Searching dockets…"
          : `No visible docket matches “${query}”. Search by mark, docket title, or the full application or registration number.`}
      </p>
    );
  }
  const count = loadedCount.toLocaleString("en-IN");
  const of = total.toLocaleString("en-IN");
  return (
    <div id={id} role="status" className="flex min-w-0 flex-wrap items-center gap-2 text-sm text-[var(--color-mute)]">
      <span className="min-w-0 break-words">
        {searching
          ? "Searching dockets…"
          : hasMore
            ? `Showing ${count} of ${of} dockets — refine your search or load more.`
            : query
              ? `${of} matching ${total === 1 ? "docket" : "dockets"}.`
              : `${of} ${total === 1 ? "docket" : "dockets"}.`}
      </span>
      {hasMore ? (
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={results.isFetchingNextPage}
          onClick={() => results.fetchNextPage()}
        >
          {results.isFetchingNextPage ? "Loading…" : "Load more"}
        </Button>
      ) : null}
      {results.isFetchNextPageError ? (
        <span role="alert" className="min-w-0 break-words text-[var(--color-danger-500)]">
          More dockets could not be loaded: {errorText(results.error)}
        </span>
      ) : null}
    </div>
  );
}
