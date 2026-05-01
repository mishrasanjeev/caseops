"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeftRight } from "lucide-react";
import { useState } from "react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/Card";
import { Skeleton } from "@/components/ui/Skeleton";
import {
  type DraftCompareResponse,
  type DraftDiffLine,
  compareDraftRevisions,
} from "@/lib/api/endpoints";

type Props = {
  matterId: string;
  draftId: string;
  revisions: number[]; // ordered ascending (1, 2, 3, ...)
};

/**
 * PG-005 Sprint 6 (2026-05-01) — side-by-side diff view between two
 * revisions of the same draft. Pure compute on the API; this component
 * just renders the hunks + citation deltas.
 *
 * The default revision pair is (max - 1) → max so the lawyer's first
 * glance is "what changed since the last regenerate". Drop-down
 * pickers above the diff allow comparing any pair.
 */
export function DraftCompareView({ matterId, draftId, revisions }: Props) {
  const sorted = [...revisions].sort((a, b) => a - b);
  const defaultNext = sorted[sorted.length - 1];
  const defaultPrev = sorted.length >= 2 ? sorted[sorted.length - 2] : sorted[0];

  const [prev, setPrev] = useState<number>(defaultPrev);
  const [next, setNext] = useState<number>(defaultNext);

  const enabled = revisions.length >= 2 && prev !== next;

  const query = useQuery({
    queryKey: ["draft-compare", matterId, draftId, prev, next],
    queryFn: () =>
      compareDraftRevisions({
        matterId,
        draftId,
        prevRevision: prev,
        nextRevision: next,
      }),
    enabled,
  });

  if (revisions.length < 2) {
    return (
      <Card data-testid="draft-compare-empty">
        <CardHeader>
          <CardTitle as="h2">Compare revisions</CardTitle>
          <CardDescription>
            Generate at least one more revision to enable diff view.
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }

  return (
    <Card data-testid="draft-compare-view">
      <CardHeader>
        <CardTitle as="h2">
          <ArrowLeftRight className="mr-2 inline-block h-4 w-4" aria-hidden /> Compare revisions
        </CardTitle>
        <CardDescription>
          Line-level diff + citation deltas between any two revisions.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <label className="flex items-center gap-2">
            <span className="text-[var(--color-mute)]">From</span>
            <select
              className="rounded-md border border-[var(--color-line)] bg-white px-2 py-1"
              value={prev}
              onChange={(e) => setPrev(Number(e.target.value))}
              data-testid="draft-compare-prev-select"
            >
              {sorted.map((r) => (
                <option key={r} value={r}>
                  Revision {r}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-2">
            <span className="text-[var(--color-mute)]">to</span>
            <select
              className="rounded-md border border-[var(--color-line)] bg-white px-2 py-1"
              value={next}
              onChange={(e) => setNext(Number(e.target.value))}
              data-testid="draft-compare-next-select"
            >
              {sorted.map((r) => (
                <option key={r} value={r}>
                  Revision {r}
                </option>
              ))}
            </select>
          </label>
          {prev === next ? (
            <span className="text-xs text-amber-700">
              Pick two different revisions to see the diff.
            </span>
          ) : null}
        </div>

        {query.isLoading ? (
          <Skeleton className="h-32 w-full" />
        ) : query.error ? (
          <p className="text-sm text-red-700">
            Failed to load diff: {String(query.error)}
          </p>
        ) : query.data ? (
          <DiffPayload data={query.data} />
        ) : null}
      </CardContent>
    </Card>
  );
}

function DiffPayload({ data }: { data: DraftCompareResponse }) {
  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-[var(--color-ink-2)]" data-testid="draft-compare-summary">
        {data.summary}
      </p>

      {(data.citations_added.length > 0 ||
        data.citations_removed.length > 0) && (
        <div className="grid gap-3 sm:grid-cols-2">
          {data.citations_added.length > 0 && (
            <div>
              <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-emerald-700">
                Citations added ({data.citations_added.length})
              </h3>
              <ul className="space-y-1 text-sm">
                {data.citations_added.map((c) => (
                  <li key={c} className="text-emerald-700">
                    + {c}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {data.citations_removed.length > 0 && (
            <div>
              <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-red-700">
                Citations removed ({data.citations_removed.length})
              </h3>
              <ul className="space-y-1 text-sm">
                {data.citations_removed.map((c) => (
                  <li key={c} className="text-red-700">
                    − {c}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {data.hunks.length === 0 ? (
        <p className="text-sm italic text-[var(--color-mute)]">
          No body changes between these revisions.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-md border border-[var(--color-line)] bg-white">
          {data.hunks.map((hunk, idx) => (
            <div key={idx} className="border-b border-[var(--color-line)] last:border-b-0">
              <div className="bg-[var(--color-bg)] px-3 py-1 text-xs text-[var(--color-mute)]">
                @@ -{hunk.prev_start},{hunk.prev_length} +{hunk.next_start},
                {hunk.next_length} @@
              </div>
              <pre className="overflow-x-auto px-3 py-1 font-mono text-xs leading-relaxed">
                {hunk.lines.map((ln, j) => (
                  <DiffLineRow key={j} line={ln} />
                ))}
              </pre>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function DiffLineRow({ line }: { line: DraftDiffLine }) {
  const bg =
    line.kind === "insert"
      ? "bg-emerald-50 text-emerald-900"
      : line.kind === "delete"
        ? "bg-red-50 text-red-900"
        : line.kind === "replace"
          ? line.next_line_number !== null
            ? "bg-emerald-50 text-emerald-900"
            : "bg-red-50 text-red-900"
          : "";
  const marker =
    line.kind === "insert" || (line.kind === "replace" && line.next_line_number !== null)
      ? "+"
      : line.kind === "delete" || (line.kind === "replace" && line.prev_line_number !== null)
        ? "−"
        : " ";
  return (
    <div className={`flex ${bg}`} data-testid={`diff-line-${line.kind}`}>
      <span className="w-10 select-none text-right text-[var(--color-mute)]">
        {line.prev_line_number ?? ""}
      </span>
      <span className="w-10 select-none text-right text-[var(--color-mute)]">
        {line.next_line_number ?? ""}
      </span>
      <span className="w-4 select-none px-1">{marker}</span>
      <span className="flex-1 whitespace-pre">{line.text || " "}</span>
    </div>
  );
}
