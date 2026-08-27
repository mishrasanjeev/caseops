"use client";

import {
  ArrowRight,
  BookOpenText,
  Compass,
  LoaderCircle,
  LockKeyhole,
  Search,
  TriangleAlert,
} from "lucide-react";
import { type FormEvent, useRef, useState } from "react";

import { isApiErrorShape } from "@/lib/api/config";
import {
  searchProductGuide,
  type ProductGuideSearchResponse,
} from "@/lib/api/product-guide";

const MIN_QUERY_CHARS = 2;
const MAX_QUERY_CHARS = 160;

function capabilityLabel(capability: string): string {
  const words = capability.replaceAll(":", " ").replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function ProductGuideSearch({ contentVersion }: { contentVersion: string }) {
  const [query, setQuery] = useState("");
  const [response, setResponse] = useState<ProductGuideSearchResponse | null>(null);
  const [error, setError] = useState<"signed_out" | "unavailable" | null>(null);
  const [validation, setValidation] = useState<string | null>(null);
  const [isSearching, setIsSearching] = useState(false);
  const requestRef = useRef<AbortController | null>(null);

  async function runSearch(value: string) {
    const normalized = value.trim();
    if (normalized.length < MIN_QUERY_CHARS) {
      setValidation("Enter at least two characters.");
      setResponse(null);
      return;
    }

    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    setQuery(normalized);
    setValidation(null);
    setError(null);
    setIsSearching(true);
    try {
      const next = await searchProductGuide(normalized, {
        clientVersion: contentVersion,
        signal: controller.signal,
      });
      setResponse(next);
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === "AbortError") return;
      setResponse(null);
      setError(isApiErrorShape(caught) && caught.status === 401 ? "signed_out" : "unavailable");
    } finally {
      if (requestRef.current === controller) {
        requestRef.current = null;
        setIsSearching(false);
      }
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void runSearch(query);
  }

  return (
    <section
      aria-labelledby="product-guide-search-title"
      className="mb-14 rounded-lg border border-[var(--color-line)] bg-[var(--color-bg)] p-5 shadow-sm md:p-7"
      data-testid="product-guide-search"
    >
      <div className="flex min-w-0 items-start gap-3">
        <span className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-[var(--color-ink)] text-white">
          <Compass className="h-4 w-4" aria-hidden />
        </span>
        <div className="min-w-0">
          <h2
            id="product-guide-search-title"
            className="font-display text-xl font-normal leading-tight text-[var(--color-ink)] md:text-2xl"
          >
            What do you need to do?
          </h2>
          <p className="mt-1 text-sm leading-relaxed text-[var(--color-mute)]">
            Find an approved workflow or open a permitted CaseOps screen.
          </p>
        </div>
      </div>

      <form className="mt-5 flex min-w-0 flex-col gap-2 sm:flex-row" onSubmit={handleSubmit}>
        <label className="sr-only" htmlFor="product-guide-query">
          Search the CaseOps guide
        </label>
        <div className="relative min-w-0 flex-1">
          <Search
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--color-mute)]"
            aria-hidden
          />
          <input
            id="product-guide-query"
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value.slice(0, MAX_QUERY_CHARS))}
            maxLength={MAX_QUERY_CHARS}
            autoComplete="off"
            placeholder="e.g. file a trademark application"
            aria-describedby={validation ? "product-guide-query-error" : undefined}
            aria-invalid={validation ? true : undefined}
            className="h-11 w-full min-w-0 rounded-md border border-[var(--color-line)] bg-white pl-10 pr-3 text-[15px] text-[var(--color-ink)] outline-none placeholder:text-[var(--color-mute-2)] focus:border-[var(--color-brand-600)] focus:ring-2 focus:ring-[var(--color-brand-600)]/15"
          />
        </div>
        <button
          type="submit"
          disabled={isSearching}
          className="inline-flex h-11 w-full shrink-0 items-center justify-center gap-2 rounded-md bg-[var(--color-brand-600)] px-5 text-sm font-semibold text-white hover:bg-[var(--color-brand-700)] focus:outline-none focus:ring-2 focus:ring-[var(--color-brand-600)] focus:ring-offset-2 disabled:cursor-wait disabled:opacity-70 sm:w-auto"
        >
          {isSearching ? (
            <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden />
          ) : (
            <Search className="h-4 w-4" aria-hidden />
          )}
          {isSearching ? "Searching" : "Search"}
        </button>
      </form>

      {validation ? (
        <p id="product-guide-query-error" className="mt-2 text-sm text-[var(--color-danger-600)]">
          {validation}
        </p>
      ) : null}

      <div className="mt-5" aria-live="polite" aria-busy={isSearching}>
        {response?.version_status === "stale" ? (
          <div
            className="mb-4 flex items-start gap-2 border-l-2 border-[var(--color-warning-500)] pl-3 text-sm leading-relaxed text-[var(--color-ink-2)]"
            data-testid="product-guide-stale"
          >
            <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0 text-[var(--color-warning-600)]" aria-hidden />
            <p>
              This page uses guide {contentVersion}; search is using the current guide {response.content_version}.
            </p>
          </div>
        ) : null}

        {response?.status === "matched" ? (
          <div data-testid="product-guide-results">
            <p className="text-xs font-semibold uppercase text-[var(--color-mute)]">
              Approved guidance
            </p>
            <ol className="mt-2 divide-y divide-[var(--color-line)] border-y border-[var(--color-line)]">
              {response.results.map((result) => {
                const ResultIcon = result.kind === "command" ? Compass : BookOpenText;
                return (
                  <li key={`${result.kind}:${result.id}`}>
                    <a
                      href={result.href}
                      className="group flex min-w-0 items-start gap-3 px-1 py-4 focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-brand-600)]"
                    >
                      <ResultIcon className="mt-0.5 h-4 w-4 shrink-0 text-[var(--color-brand-600)]" aria-hidden />
                      <span className="min-w-0 flex-1">
                        <span className="block text-sm font-semibold text-[var(--color-ink)] group-hover:underline">
                          {result.title}
                        </span>
                        <span className="mt-1 block text-sm leading-relaxed text-[var(--color-mute)]">
                          {result.summary}
                        </span>
                      </span>
                      <ArrowRight className="mt-0.5 h-4 w-4 shrink-0 text-[var(--color-mute)] group-hover:text-[var(--color-ink)]" aria-hidden />
                    </a>
                  </li>
                );
              })}
            </ol>
          </div>
        ) : null}

        {response?.permission ? (
          <div className="flex items-start gap-3 border-t border-[var(--color-line)] pt-4" data-testid="product-guide-permission">
            <LockKeyhole className="mt-0.5 h-4 w-4 shrink-0 text-[var(--color-warning-600)]" aria-hidden />
            <div className="min-w-0 text-sm leading-relaxed">
              <p className="font-semibold text-[var(--color-ink)]">{response.permission.message}</p>
              <p className="mt-1 text-[var(--color-mute)]">
                Required access: {response.permission.required_capabilities.map(capabilityLabel).join(", ")}.
              </p>
            </div>
          </div>
        ) : null}

        {response?.status === "no_match" ? (
          <div className="border-t border-[var(--color-line)] pt-4" data-testid="product-guide-no-match">
            <p className="text-sm font-semibold text-[var(--color-ink)]">
              This guide does not have approved guidance for that request.
            </p>
            <p className="mt-1 text-sm text-[var(--color-mute)]">Try a related search:</p>
            <div className="mt-3 flex flex-wrap gap-2">
              {response.suggested_queries.map((suggestion) => (
                <button
                  key={suggestion}
                  type="button"
                  onClick={() => void runSearch(suggestion)}
                  className="rounded-md border border-[var(--color-line)] bg-white px-3 py-2 text-sm font-medium text-[var(--color-ink-2)] hover:border-[var(--color-ink)] hover:text-[var(--color-ink)] focus:outline-none focus:ring-2 focus:ring-[var(--color-brand-600)]"
                >
                  {suggestion}
                </button>
              ))}
            </div>
          </div>
        ) : null}

        {error === "signed_out" ? (
          <div className="flex items-start gap-3 border-t border-[var(--color-line)] pt-4" role="status">
            <LockKeyhole className="mt-0.5 h-4 w-4 shrink-0 text-[var(--color-mute)]" aria-hidden />
            <div className="text-sm leading-relaxed">
              <p className="font-semibold text-[var(--color-ink)]">Sign in to search permitted workflows.</p>
              <a className="mt-1 inline-flex items-center gap-1 font-semibold text-[var(--color-brand-700)] hover:underline" href="/sign-in">
                Sign in <ArrowRight className="h-4 w-4" aria-hidden />
              </a>
            </div>
          </div>
        ) : null}

        {error === "unavailable" ? (
          <div className="flex items-start gap-3 border-t border-[var(--color-line)] pt-4" role="alert">
            <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0 text-[var(--color-danger-600)]" aria-hidden />
            <div className="text-sm leading-relaxed">
              <p className="font-semibold text-[var(--color-ink)]">Guide search is temporarily unavailable.</p>
              <button
                type="button"
                onClick={() => void runSearch(query)}
                className="mt-1 font-semibold text-[var(--color-brand-700)] hover:underline focus:outline-none focus:ring-2 focus:ring-[var(--color-brand-600)]"
              >
                Try again
              </button>
            </div>
          </div>
        ) : null}
      </div>
    </section>
  );
}
