"use client";

import { keepPreviousData, useInfiniteQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useEffect, useId, useMemo, useState } from "react";
import type { ChangeEvent } from "react";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { RecordSelect } from "@/components/ui/RecordSelect";
import { isApiErrorShape } from "@/lib/api/config";
import { listMatters } from "@/lib/api/endpoints";
import type { Matter } from "@/lib/api/schemas";
import { cn } from "@/lib/cn";

/**
 * Choose one Matter from every Matter the user can see.
 *
 * GET /api/matters/ is tenant- and ethical-wall-scoped, searches matter code,
 * title, client, opposing party, court and case numbers (`q`), and pages by
 * cursor, most recently updated first. A firm holds hundreds of Matters, so
 * pickers that rendered one unsearchable page of them overflowed the screen
 * and hid every older Matter (Ram 2026-10-30, BUG-007).
 *
 * House record-picker pattern: a search box over a native select
 * (`RecordSelect`), so the browser keeps the list inside the viewport (a
 * native sheet on phones), and the complete caption of the chosen Matter is
 * shown under the field.
 *
 * - `value` / `onChange(id, matter)`: controlled; the picker never selects a
 *   Matter by itself. The chosen Matter stays an option when a later search
 *   no longer returns it.
 * - `disabledReason(matter)`: the caller's copy of its API validator. A
 *   Matter the write would reject is listed, disabled, with the reason, so
 *   the picker never offers a value the API refuses.
 * - `error`: a field-level message (validation or API); it sets
 *   `aria-invalid` and is announced with the field.
 */
export type MatterPickerProps = {
  value: string;
  onChange: (matterId: string, matter: Matter | null) => void;
  id?: string;
  label?: string;
  searchLabel?: string;
  disabledReason?: (matter: Matter) => string | null;
  error?: string | null;
  pageSize?: number;
  required?: boolean;
  disabled?: boolean;
  className?: string;
};

const SEARCH_DEBOUNCE_MS = 300;

/** One line that tells two Matters apart. */
export function matterCaption(matter: Pick<Matter, "matter_code" | "title" | "client_name">): string {
  return [matter.matter_code, matter.title, matter.client_name].filter(Boolean).join(" · ");
}

function errorText(error: unknown): string {
  if (isApiErrorShape(error) && error.detail.trim()) return error.detail;
  if (error instanceof Error && error.message.trim()) return error.message;
  return "Request failed.";
}

export function MatterPicker({
  value,
  onChange,
  id,
  label = "Matter",
  searchLabel,
  disabledReason,
  error,
  pageSize = 50,
  required,
  disabled,
  className,
}: MatterPickerProps) {
  const generatedId = useId();
  const selectId = id ?? `matter-picker-${generatedId.replace(/:/g, "")}`;
  const searchId = `${selectId}-search`;
  const statusId = `${selectId}-status`;
  const errorId = `${selectId}-error`;

  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  useEffect(() => {
    const handle = window.setTimeout(() => setQuery(search.trim()), SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(handle);
  }, [search]);

  const results = useInfiniteQuery({
    queryKey: ["matters", "picker", { query, pageSize }],
    queryFn: ({ pageParam }) =>
      listMatters({ q: query || undefined, cursor: pageParam ?? undefined, limit: pageSize }),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor ?? null,
    placeholderData: keepPreviousData,
  });
  const loaded = useMemo(
    () => results.data?.pages.flatMap((page) => page.matters) ?? [],
    [results.data],
  );
  const hasMore = Boolean(results.hasNextPage);

  const [chosen, setChosen] = useState<Matter | null>(null);
  const selected =
    (value ? loaded.find((matter) => matter.id === value) : undefined) ??
    (chosen?.id === value ? chosen : null);
  const matters = selected && !loaded.some((matter) => matter.id === selected.id)
    ? [selected, ...loaded]
    : loaded;
  const options = [
    { value: "", label: results.isPending ? "Loading Matters…" : "Select a Matter", disabled: true },
    ...matters.map((matter) => {
      const reason = disabledReason?.(matter) ?? null;
      return {
        value: matter.id,
        label: reason ? `${matterCaption(matter)} — ${reason}` : matterCaption(matter),
        disabled: Boolean(reason) && matter.id !== value,
      };
    }),
  ];
  const choosable = options.filter((option) => option.value && !option.disabled).length;
  const searching = results.isPlaceholderData || search.trim() !== query;

  const handleChange = (event: ChangeEvent<HTMLSelectElement>) => {
    const next = event.target.value;
    const matter = matters.find((row) => row.id === next) ?? null;
    if (matter) setChosen(matter);
    onChange(next, matter);
  };

  return (
    <div className={cn("flex min-w-0 flex-col gap-2", className)} data-testid="matter-picker">
      <div className="flex min-w-0 flex-col gap-1.5">
        <Label htmlFor={searchId}>{searchLabel ?? `Search ${label}s`}</Label>
        <Input
          id={searchId}
          type="search"
          value={search}
          disabled={disabled}
          autoComplete="off"
          placeholder="Matter code, title, client or case number"
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
        disabled={disabled || results.isPending || (choosable === 0 && !value)}
        aria-invalid={error ? true : undefined}
        aria-describedby={[statusId, error ? errorId : null].filter(Boolean).join(" ")}
        onChange={handleChange}
        className="h-10 w-full min-w-0 rounded-md border border-[var(--color-line)] bg-white px-3 text-sm text-[var(--color-ink)] disabled:cursor-not-allowed disabled:opacity-60 aria-[invalid=true]:border-[var(--color-danger-500)]"
      />

      <div id={statusId} role={results.isError && !results.isFetchNextPageError ? "alert" : "status"}
        className="flex min-w-0 flex-wrap items-center gap-2 text-sm text-[var(--color-mute)]">
        {results.isPending ? (
          <span>Loading Matters…</span>
        ) : results.isError && !results.isFetchNextPageError ? (
          <>
            <span className="min-w-0 break-words text-[var(--color-danger-500)]">
              Matters could not be loaded: {errorText(results.error)}
            </span>
            <Button type="button" size="sm" variant="outline" onClick={() => results.refetch()}>
              Retry
            </Button>
          </>
        ) : loaded.length === 0 && searching ? (
          <span>Searching Matters…</span>
        ) : loaded.length === 0 && !query ? (
          <>
            <span className="min-w-0 break-words">
              No Matters are visible to you yet. Matters behind an ethical wall are not listed.
            </span>
            <Link className="font-semibold text-[var(--color-brand-700)] hover:underline" href="/app/matters">
              Create a Matter
            </Link>
          </>
        ) : loaded.length === 0 ? (
          <span className="min-w-0 break-words">
            No Matter you can see matches “{query}”. Search by matter code, title, client or case
            number.
          </span>
        ) : choosable === 0 ? (
          <span className="min-w-0 break-words">
            None of these Matters can be chosen; each one lists the reason.
          </span>
        ) : (
          <>
            <span className="min-w-0 break-words">
              {searching
                ? "Searching Matters…"
                : hasMore
                  ? `Showing the ${loaded.length} most recently updated Matters${query ? ` matching “${query}”` : ""} — refine the search or load more.`
                  : `${loaded.length} ${loaded.length === 1 ? "Matter" : "Matters"}${query ? ` matching “${query}”` : ""}.`}
            </span>
            {hasMore ? (
              <Button
                type="button"
                size="sm"
                variant="outline"
                aria-label="Load more Matters"
                disabled={results.isFetchingNextPage}
                onClick={() => results.fetchNextPage()}
              >
                {results.isFetchingNextPage ? "Loading…" : "Load more"}
              </Button>
            ) : null}
          </>
        )}
        {results.isFetchNextPageError ? (
          <span className="flex min-w-0 flex-wrap items-center gap-2 text-[var(--color-danger-500)]" role="alert">
            More Matters could not be loaded: {errorText(results.error)}
            <Button type="button" size="sm" variant="outline" onClick={() => results.fetchNextPage()}>
              Retry
            </Button>
          </span>
        ) : null}
      </div>

      {error ? (
        <p id={errorId} className="min-w-0 break-words text-sm text-[var(--color-danger-500)]">
          {error}
        </p>
      ) : null}
    </div>
  );
}
