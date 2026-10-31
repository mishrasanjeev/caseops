"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronDown, X } from "lucide-react";
import { useEffect, useMemo, useState, type FocusEvent, type KeyboardEvent } from "react";

import { Button } from "@/components/ui/Button";
import { Label } from "@/components/ui/Label";
import { ApiError, NetworkError } from "@/lib/api/config";
import { fetchIpNiceClasses } from "@/lib/api/endpoints";
import type { IpNiceClass } from "@/lib/api/schemas";
import { cn } from "@/lib/cn";

/**
 * Choose WIPO Nice classes by number or by what the class covers (BUG-002).
 *
 * Options come only from GET /api/ip/nice-classes, the same catalogue the
 * trademark particulars validator checks, so nothing offered here can be
 * refused for being outside the classification. Classes the caller marks
 * `unavailable` (for example, already listed in another class row) stay
 * visible but cannot be chosen, matching the API's duplicate refusal.
 *
 * Usage: render it with its own `label` (do not wrap it in a <label>, which
 * would fold every option into the field's accessible name). While the
 * catalogue is loading or failed the control is disabled; callers that also
 * need to block submit read the same query with `useNiceClassCatalogue()`.
 */

export const NICE_CLASS_QUERY_KEY = ["ip", "nice-classes"] as const;

export function useNiceClassCatalogue() {
  return useQuery({
    queryKey: NICE_CLASS_QUERY_KEY,
    queryFn: fetchIpNiceClasses,
    // Reference data: a new edition arrives with a release, not mid-session.
    staleTime: Number.POSITIVE_INFINITY,
  });
}

export function niceClassLabel(row: Pick<IpNiceClass, "number" | "heading">): string {
  return `Class ${row.number} — ${row.heading}`;
}

/** Screen-reader name of an option; the visible parts are separate spans. */
function optionName(row: IpNiceClass, blocked: boolean): string {
  const kind = row.kind === "goods" ? "goods" : "services";
  const name = `Class ${row.number}, ${kind}: ${row.heading}`;
  return blocked ? `${name} Already listed in another row.` : name;
}

function catalogueErrorText(error: unknown): string {
  if ((error instanceof ApiError || error instanceof NetworkError) && error.message) {
    return error.message;
  }
  // A response that fails the catalogue contract (for example a partial list)
  // is refused rather than offering a subset of classes.
  return "The server returned an incomplete Nice class list.";
}

const CLASS_PREFIX = /^(?:class(?:es)?|cl\.?)\s*/i;

/** "35", "Class 3", "cl. 9" search by number; anything else searches text. */
function numberQuery(query: string): string | null {
  const numeric = query.trim().replace(CLASS_PREFIX, "");
  return /^\d+$/.test(numeric) ? String(Number(numeric)) : null;
}

function queryWords(query: string): string[] {
  return query.trim().toLowerCase().split(/\s+/).filter(Boolean);
}

function containsAll(text: string, words: string[]): boolean {
  const haystack = text.toLowerCase();
  return words.every((word) => haystack.includes(word));
}

/** True when a text query matches the class only through its explanatory note. */
export function matchesOnlyInNote(row: IpNiceClass, query: string): boolean {
  const words = queryWords(query);
  if (words.length === 0 || numberQuery(query) !== null) return false;
  return !containsAll(row.heading, words) && containsAll(`${row.heading} ${row.note ?? ""}`, words);
}

/** Filter by class number (prefix), or by words in the heading or note. */
export function searchNiceClasses(classes: IpNiceClass[], query: string): IpNiceClass[] {
  const words = queryWords(query);
  if (words.length === 0) return classes;
  const digits = numberQuery(query);
  if (digits !== null) return classes.filter((row) => String(row.number).startsWith(digits));
  const byHeading = classes.filter((row) => containsAll(row.heading, words));
  const byNote = classes.filter((row) => matchesOnlyInNote(row, query));
  return [...byHeading, ...byNote];
}

type CommonProps = {
  /** Id of the search input; the label and any caller error point at it. */
  id: string;
  /** Visible field label, for example "Nice class". */
  label: string;
  disabled?: boolean;
  /** Marks the field invalid; pair with `errorId` for the caller's message. */
  invalid?: boolean;
  /** Id of a caller-rendered error message, added to aria-describedby. */
  errorId?: string;
  /** Classes that must not be chosen here, e.g. listed in another class row. */
  unavailable?: number[];
  className?: string;
};

export type NiceClassPickerProps =
  | (CommonProps & {
      mode?: "single";
      value: number | null;
      onChange: (value: number) => void;
    })
  | (CommonProps & {
      mode: "multiple";
      value: number[];
      onChange: (value: number[]) => void;
    });

export function NiceClassPicker(props: NiceClassPickerProps) {
  const { id, label, disabled = false, invalid = false, errorId, unavailable, className } = props;
  const multiple = props.mode === "multiple";
  const selected = useMemo<number[]>(
    () => (multiple ? (props.value as number[]) : props.value === null ? [] : [props.value as number]),
    [multiple, props.value],
  );

  const catalogue = useNiceClassCatalogue();
  const classes = useMemo(() => catalogue.data?.classes ?? [], [catalogue.data]);
  const byNumber = useMemo(() => new Map(classes.map((row) => [row.number, row])), [classes]);
  const blocked = useMemo(() => new Set(unavailable ?? []), [unavailable]);

  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [preferred, setPreferred] = useState<number | null>(null);

  const matches = useMemo(() => searchNiceClasses(classes, query), [classes, query]);
  const selectable = (row: IpNiceClass) =>
    !blocked.has(row.number) || selected.includes(row.number);
  // The highlighted option: the last one the person moved to, if it is still
  // shown and choosable, otherwise the first choosable match.
  const active = open
    ? (matches.find((row) => row.number === preferred && selectable(row)) ??
        matches.find(selectable) ??
        null)?.number ?? null
    : null;

  const ready = catalogue.isSuccess;
  const controlDisabled = disabled || !ready;
  const listboxId = `${id}-listbox`;
  const labelId = `${id}-label`;
  const statusId = `${id}-status`;
  const selectedId = `${id}-selected-description`;
  const optionId = (number: number) => `${id}-option-${number}`;

  useEffect(() => {
    if (active === null) return;
    document.getElementById(`${id}-option-${active}`)?.scrollIntoView?.({ block: "nearest" });
  }, [id, active]);

  useEffect(() => {
    if (controlDisabled) setOpen(false);
  }, [controlDisabled]);

  function choose(row: IpNiceClass) {
    if (!selectable(row)) return;
    if (props.mode === "multiple") {
      const next = props.value.includes(row.number)
        ? props.value.filter((number) => number !== row.number)
        : [...props.value, row.number];
      props.onChange(next);
      setPreferred(row.number);
      return;
    }
    props.onChange(row.number);
    setQuery("");
    setOpen(false);
  }

  function remove(number: number) {
    if (props.mode === "multiple") props.onChange(props.value.filter((value) => value !== number));
  }

  function move(step: 1 | -1) {
    const enabled = matches.filter(selectable);
    if (enabled.length === 0) return;
    const index = enabled.findIndex((row) => row.number === active);
    const next = index === -1 ? (step === 1 ? 0 : enabled.length - 1) : index + step;
    setPreferred(enabled[Math.min(Math.max(next, 0), enabled.length - 1)].number);
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      if (!open) setOpen(true);
      else if (!event.altKey) move(1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      if (event.altKey) setOpen(false);
      else if (open) move(-1);
    } else if (event.key === "Enter") {
      // Never let Enter in the search box submit the surrounding form.
      event.preventDefault();
      const row = active === null ? undefined : byNumber.get(active);
      if (open && row) choose(row);
      else if (!open) setOpen(true);
    } else if (event.key === "Escape") {
      if (open) {
        event.preventDefault();
        event.stopPropagation();
        setOpen(false);
      } else if (query) {
        event.preventDefault();
        setQuery("");
      }
    } else if (event.key === "Tab") {
      setOpen(false);
    }
  }

  function onBlur(event: FocusEvent<HTMLDivElement>) {
    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setOpen(false);
  }

  const singleRow = !multiple && selected.length === 1 ? byNumber.get(selected[0]) : undefined;
  const singleCaption =
    !multiple && selected.length === 1
      ? singleRow
        ? niceClassLabel(singleRow)
        : ready
          ? `Class ${selected[0]} is not a Nice class in ${catalogue.data?.edition}. Choose a class from 1 to 45.`
          : `Class ${selected[0]}`
      : null;
  const describedBy = [singleCaption ? selectedId : null, errorId ?? null]
    .filter(Boolean)
    .join(" ");

  const placeholder = catalogue.isPending
    ? "Loading Nice classes…"
    : catalogue.isError
      ? "Nice classes unavailable"
      : selected.length > 0 && !multiple
        ? "Change class: type a number or a word…"
        : "Type a class number or a word, e.g. 35 or advertising";

  const statusText = !ready
    ? ""
    : !open
      ? ""
      : matches.length === 0
        ? `No Nice class matches "${query.trim()}".`
        : `${matches.length} of ${classes.length} classes shown.`;

  return (
    <div className={cn("flex min-w-0 flex-col gap-2", className)} onBlur={onBlur}>
      <Label id={labelId} htmlFor={id} className="break-words leading-snug">
        {label}
      </Label>

      {multiple && selected.length > 0 ? (
        <ul aria-label={`${label}: selected`} className="flex min-w-0 flex-col gap-1">
          {selected.map((number) => {
            const row = byNumber.get(number);
            const text = row ? niceClassLabel(row) : `Class ${number}`;
            return (
              <li
                key={number}
                className="flex min-w-0 items-start gap-2 rounded-md border border-[var(--color-line)] bg-[var(--color-bg)] px-2 py-1 text-sm text-[var(--color-ink)]"
              >
                <span className="min-w-0 flex-1 whitespace-normal break-words">{text}</span>
                <button
                  type="button"
                  onClick={() => remove(number)}
                  disabled={disabled}
                  aria-label={`Remove class ${number}`}
                  className="shrink-0 rounded p-0.5 text-[var(--color-mute)] hover:text-[var(--color-ink)] focus-visible:outline-2 focus-visible:outline-[var(--color-brand-500)] disabled:opacity-50"
                >
                  <X className="h-4 w-4" aria-hidden />
                </button>
              </li>
            );
          })}
        </ul>
      ) : null}

      <div className="flex min-w-0 items-stretch gap-1">
        <input
          id={id}
          type="text"
          role="combobox"
          autoComplete="off"
          spellCheck={false}
          value={query}
          placeholder={placeholder}
          disabled={controlDisabled}
          aria-busy={catalogue.isPending || undefined}
          aria-expanded={open}
          aria-controls={listboxId}
          aria-autocomplete="list"
          aria-activedescendant={open && active !== null ? optionId(active) : undefined}
          aria-invalid={invalid || undefined}
          aria-describedby={describedBy || undefined}
          onChange={(event) => {
            setQuery(event.target.value);
            setOpen(true);
          }}
          onClick={() => {
            if (!controlDisabled) setOpen(true);
          }}
          onKeyDown={onKeyDown}
          className={cn(
            "h-10 w-full min-w-0 rounded-md border bg-white px-3 text-sm text-[var(--color-ink)] shadow-sm placeholder:text-[var(--color-mute-2)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-brand-500)] focus-visible:ring-offset-1 disabled:cursor-not-allowed disabled:opacity-50",
            invalid ? "border-[var(--color-danger-500)]" : "border-[var(--color-line)]",
          )}
        />
        <button
          type="button"
          tabIndex={-1}
          disabled={controlDisabled}
          aria-label={open ? "Hide Nice classes" : "Show Nice classes"}
          aria-controls={listboxId}
          aria-expanded={open}
          onMouseDown={(event) => event.preventDefault()}
          onClick={() => {
            setOpen((value) => !value);
            document.getElementById(id)?.focus();
          }}
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md border border-[var(--color-line)] bg-white text-[var(--color-ink-2)] hover:border-[var(--color-ink-3)] disabled:cursor-not-allowed disabled:opacity-50"
        >
          <ChevronDown className={cn("h-4 w-4", open && "rotate-180")} aria-hidden />
        </button>
      </div>

      <p id={statusId} aria-live="polite" className="sr-only">
        {statusText}
      </p>

      <div
        hidden={!open}
        className="min-w-0 overflow-hidden rounded-md border border-[var(--color-line)] bg-[var(--color-surface)]"
      >
        <ul
          id={listboxId}
          role="listbox"
          aria-labelledby={labelId}
          aria-multiselectable={multiple || undefined}
          className="max-h-80 min-w-0 overflow-y-auto py-1"
        >
          {open
            ? matches.map((row) => {
                const isSelected = selected.includes(row.number);
                const isBlocked = !selectable(row);
                const noteMatched = matchesOnlyInNote(row, query);
                return (
                  <li
                    key={row.number}
                    id={optionId(row.number)}
                    role="option"
                    aria-label={optionName(row, isBlocked)}
                    aria-selected={isSelected}
                    aria-disabled={isBlocked || undefined}
                    data-active={active === row.number || undefined}
                    onMouseDown={(event) => event.preventDefault()}
                    onMouseEnter={() => {
                      if (!isBlocked) setPreferred(row.number);
                    }}
                    onClick={() => choose(row)}
                    className={cn(
                      "flex min-w-0 cursor-pointer flex-col gap-0.5 px-3 py-2 text-sm",
                      active === row.number && "bg-[var(--color-brand-50)]",
                      isSelected && "font-medium",
                      isBlocked && "cursor-not-allowed text-[var(--color-mute)]",
                    )}
                  >
                    <span className="flex min-w-0 items-baseline gap-2">
                      <span className="shrink-0 tabular-nums text-[var(--color-ink)]">
                        Class {row.number}
                      </span>
                      <span className="text-xs uppercase tracking-wide text-[var(--color-mute-2)]">
                        {row.kind === "goods" ? "Goods" : "Services"}
                      </span>
                      {isSelected ? (
                        <span aria-hidden className="text-xs text-[var(--color-brand-700)]">
                          Selected
                        </span>
                      ) : null}
                      {isBlocked ? <span className="text-xs">Already listed</span> : null}
                    </span>
                    <span className="min-w-0 whitespace-normal break-words text-[var(--color-ink-2)]">
                      {row.heading}
                    </span>
                    {noteMatched && row.note ? (
                      <span className="min-w-0 whitespace-normal break-words text-xs text-[var(--color-mute)]">
                        {row.note}
                      </span>
                    ) : null}
                  </li>
                );
              })
            : null}
        </ul>
        {open && matches.length === 0 ? (
          <p className="px-3 py-2 text-sm text-[var(--color-mute)]">
            No Nice class matches &ldquo;{query.trim()}&rdquo;. Search by class number (1 to 45)
            or by a word from the class heading, such as &ldquo;software&rdquo;.
          </p>
        ) : null}
        {open && catalogue.data ? (
          <p className="border-t border-[var(--color-line)] px-3 py-1.5 text-xs text-[var(--color-mute)]">
            Class headings: {catalogue.data.attribution}{" "}
            <a
              href={catalogue.data.source_url}
              target="_blank"
              rel="noreferrer"
              className="underline underline-offset-2"
            >
              WIPO source
            </a>
          </p>
        ) : null}
      </div>

      {singleCaption ? (
        <p
          id={selectedId}
          data-selected-option-value={selected[0]}
          className="min-w-0 whitespace-normal break-words text-sm text-[var(--color-ink-2)]"
        >
          {singleCaption}
        </p>
      ) : null}

      {catalogue.isPending ? (
        <p className="text-sm text-[var(--color-mute)]">Loading the WIPO Nice class list…</p>
      ) : null}
      {catalogue.isError ? (
        <div role="alert" className="flex min-w-0 flex-wrap items-center gap-2 text-sm text-[var(--color-ink-2)]">
          <span className="min-w-0 break-words">
            The Nice class list could not be loaded, so a class cannot be chosen yet.{" "}
            {catalogueErrorText(catalogue.error)}
          </span>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => void catalogue.refetch()}
            disabled={catalogue.isFetching}
            data-testid="nice-class-retry"
          >
            {catalogue.isFetching ? "Retrying…" : "Try again"}
          </Button>
        </div>
      ) : null}
    </div>
  );
}
