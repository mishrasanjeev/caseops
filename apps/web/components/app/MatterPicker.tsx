"use client";

import { keepPreviousData, useInfiniteQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useEffect, useId, useMemo, useState } from "react";
import type { ChangeEvent, KeyboardEvent } from "react";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { RecordSelect } from "@/components/ui/RecordSelect";
import { isApiErrorShape } from "@/lib/api/config";
import { listMatters } from "@/lib/api/endpoints";
import type { Matter } from "@/lib/api/schemas";
import { useCapability } from "@/lib/capabilities";
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
 * - `enabled`: false holds the first read back, for pages that sequence
 *   their reads.
 *
 * Enter in the search box searches at once and never submits the
 * surrounding form, which would otherwise act on the Matter chosen before
 * the new search (a portal invite granting the wrong Matter).
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
  enabled?: boolean;
  className?: string;
};

const SEARCH_DEBOUNCE_MS = 300;

// services/matter_operational_guard.py matter_is_operational: only these
// lifecycle states may take new operational work (an intelligent review, the
// operational IP link). is_active follows the status in the database
// (ck_matters_status_active_consistent), so the status alone decides.
export const OPERATIONAL_MATTER_STATUSES: ReadonlySet<string> = new Set(["intake", "active", "on_hold"]);

/** One line that tells two Matters apart. */
export function matterCaption(matter: Pick<Matter, "matter_code" | "title" | "client_name">): string {
  return [matter.matter_code, matter.title, matter.client_name].filter(Boolean).join(" · ");
}

function errorText(error: unknown): string {
  if (isApiErrorShape(error) && error.detail.trim()) return error.detail;
  if (error instanceof Error && error.message.trim()) return error.message;
  return "Request failed.";
}

/** Every reason on screen, grouped: "Already linked as Litigation: TM-1, TM-2, TM-3 and 4 more." */
function blockedSummary(blocked: ReadonlyArray<{ matter: Matter; reason: string }>): string {
  const groups = new Map<string, string[]>();
  for (const { matter, reason } of blocked) groups.set(reason, [...(groups.get(reason) ?? []), matter.matter_code]);
  return [...groups]
    .map(([reason, codes]) => {
      const more = codes.length > 3 ? ` and ${codes.length - 3} more` : "";
      return `${reason.charAt(0).toUpperCase()}${reason.slice(1)}: ${codes.slice(0, 3).join(", ")}${more}.`;
    })
    .join(" ");
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
  enabled = true,
  className,
}: MatterPickerProps) {
  const generatedId = useId();
  const selectId = id ?? `matter-picker-${generatedId.replace(/:/g, "")}`;
  const searchId = `${selectId}-search`;
  const statusId = `${selectId}-status`;
  const errorId = `${selectId}-error`;
  const canCreateMatter = useCapability("matters:create");

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
    enabled,
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
  const rows = matters.map((matter) => ({ matter, reason: disabledReason?.(matter) ?? null }));
  const options = [
    { value: "", label: results.isPending ? "Loading Matters…" : "Select a Matter", disabled: true },
    // The chosen Matter stays selectable so the field keeps showing it (with
    // its reason); the caller anchors that reason to the field.
    ...rows.map(({ matter, reason }) => ({
      value: matter.id,
      label: reason ? `${matterCaption(matter)} — ${reason}` : matterCaption(matter),
      disabled: Boolean(reason) && matter.id !== value,
    })),
  ];
  const choosable = rows.filter((row) => !row.reason).length;
  const blocked = rows.flatMap(({ matter, reason }) => (reason ? [{ matter, reason }] : []));
  const searching = results.isPlaceholderData || search.trim() !== query;
  const loadFailed = results.isError && !results.isFetchNextPageError;

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
          onKeyDown={(event: KeyboardEvent<HTMLInputElement>) => {
            if (event.key !== "Enter") return;
            event.preventDefault();
            setQuery(search.trim());
          }}
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

      {/* The text is the live region and the field's description; its
          actions sit beside it, not inside it. */}
      <div className="flex min-w-0 flex-wrap items-center gap-2 text-sm text-[var(--color-mute)]">
        {loadFailed ? (
          <>
            <span id={statusId} role="alert" className="min-w-0 break-words text-[var(--color-danger-500)]">
              Matters could not be loaded: {errorText(results.error)}
            </span>
            <Button type="button" size="sm" variant="outline" onClick={() => results.refetch()}>
              Retry
            </Button>
          </>
        ) : (
          <>
            <span id={statusId} role="status" className="min-w-0 break-words">
              {results.isPending
                ? "Loading Matters…"
                : searching
                  ? "Searching Matters…"
                  : loaded.length === 0 && !query
                    ? `No Matters are visible to you yet. Matters behind an ethical wall are not listed.${canCreateMatter ? "" : " Your role cannot create Matters; ask someone who can."}`
                    : loaded.length === 0
                      ? `No Matter you can see matches “${query}”. Search by matter code, title, client or case number.`
                      : choosable === 0
                        ? `None of these Matters can be chosen. ${blockedSummary(blocked)}`
                        : hasMore
                          ? `Showing the ${loaded.length} most recently updated Matters${query ? ` matching “${query}”` : ""} — refine the search or load more.`
                          : `${loaded.length} ${loaded.length === 1 ? "Matter" : "Matters"}${query ? ` matching “${query}”` : ""}.`}
            </span>
            {!results.isPending && !searching && loaded.length === 0 && !query && canCreateMatter ? (
              <Link className="font-semibold text-[var(--color-brand-700)] hover:underline" href="/app/matters">
                Create a Matter
              </Link>
            ) : null}
            {!results.isPending && !searching && hasMore ? (
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
          <>
            <span role="alert" className="min-w-0 break-words text-[var(--color-danger-500)]">
              More Matters could not be loaded: {errorText(results.error)}
            </span>
            <Button type="button" size="sm" variant="outline" onClick={() => results.fetchNextPage()}>
              Retry
            </Button>
          </>
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
