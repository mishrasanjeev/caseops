"use client";

import { CheckCircle2, LoaderCircle, MessageSquareWarning, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { PageHeader } from "@/components/ui/PageHeader";
import {
  type AIFeedbackRecord,
  type AIFeedbackStatus,
  listAIFeedback,
  reviewAIFeedback,
} from "@/lib/api/ai-feedback";
import { apiErrorMessage } from "@/lib/api/config";
import { useCapability } from "@/lib/capabilities";

function formatDate(value: string) {
  return new Intl.DateTimeFormat("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function label(value: string | null) {
  if (!value) return "Uncategorised";
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export default function AIFeedbackPage() {
  const canAdmin = useCapability("workspace:admin");
  const [items, setItems] = useState<AIFeedbackRecord[]>([]);
  const [status, setStatus] = useState<AIFeedbackStatus | "">("open");
  const [surface, setSurface] = useState<"product_guide" | "workspace_assistant" | "">("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);

  const load = useCallback(async () => {
    if (!canAdmin) return;
    setBusy(true);
    setError(null);
    try {
      const response = await listAIFeedback({
        ...(status ? { status } : {}),
        ...(surface ? { surface } : {}),
        limit: 50,
      });
      setItems(response.items);
      setHasMore(response.has_more);
    } catch (caught) {
      setError(apiErrorMessage(caught, "The feedback queue could not be loaded."));
    } finally {
      setBusy(false);
    }
  }, [canAdmin, status, surface]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="flex min-w-0 flex-col gap-6">
      <PageHeader
        eyebrow="AI governance"
        title="Feedback review"
        description="Review Product Guide and workspace assistant feedback without duplicating prompts, answers, citations, or source content."
        actions={
          <button
            type="button"
            title="Refresh feedback"
            aria-label="Refresh feedback"
            disabled={!canAdmin || busy}
            onClick={() => void load()}
            className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-[var(--color-line)] bg-white text-[var(--color-ink-2)] disabled:opacity-60"
          >
            <RefreshCw className={`h-4 w-4 ${busy ? "animate-spin" : ""}`} aria-hidden />
          </button>
        }
      />

      {!canAdmin ? (
        <div className="border-y border-[var(--color-line)] py-6 text-sm text-[var(--color-mute)]">
          Workspace administrator access is required.
        </div>
      ) : (
        <>
          <div className="flex min-w-0 flex-col gap-3 border-y border-[var(--color-line)] py-4 sm:flex-row sm:items-end">
            <label className="min-w-0 flex-1 text-xs font-medium text-[var(--color-mute)]">
              Status
              <select
                value={status}
                onChange={(event) => setStatus(event.target.value as AIFeedbackStatus | "")}
                className="mt-1 h-10 w-full rounded-md border border-[var(--color-line)] bg-white px-3 text-sm text-[var(--color-ink)]"
              >
                <option value="">All statuses</option>
                <option value="open">Open</option>
                <option value="in_review">In review</option>
                <option value="resolved">Resolved</option>
                <option value="dismissed">Dismissed</option>
              </select>
            </label>
            <label className="min-w-0 flex-1 text-xs font-medium text-[var(--color-mute)]">
              Surface
              <select
                value={surface}
                onChange={(event) => setSurface(event.target.value as typeof surface)}
                className="mt-1 h-10 w-full rounded-md border border-[var(--color-line)] bg-white px-3 text-sm text-[var(--color-ink)]"
              >
                <option value="">All surfaces</option>
                <option value="product_guide">Product Guide</option>
                <option value="workspace_assistant">Workspace assistant</option>
              </select>
            </label>
          </div>

          {error ? <p className="text-sm text-[var(--color-danger-600)]" role="alert">{error}</p> : null}
          {busy && items.length === 0 ? (
            <div className="flex min-h-48 items-center justify-center gap-2 text-sm text-[var(--color-mute)]">
              <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden /> Loading feedback
            </div>
          ) : items.length === 0 ? (
            <div className="flex min-h-48 flex-col items-center justify-center border-y border-[var(--color-line)] text-center">
              <CheckCircle2 className="h-6 w-6 text-[var(--color-brand-600)]" aria-hidden />
              <p className="mt-2 text-sm font-semibold text-[var(--color-ink)]">No matching feedback</p>
            </div>
          ) : (
            <div className="divide-y divide-[var(--color-line)] border-y border-[var(--color-line)]" data-testid="ai-feedback-queue">
              {items.map((item) => (
                <FeedbackRow
                  key={item.id}
                  item={item}
                  onUpdated={(updated) =>
                    setItems((current) => current.map((row) => (row.id === updated.id ? updated : row)))
                  }
                />
              ))}
            </div>
          )}
          {hasMore ? (
            <p className="text-xs text-[var(--color-mute)]">More records match these filters. Narrow the queue to review them.</p>
          ) : null}
        </>
      )}
    </div>
  );
}

function FeedbackRow({
  item,
  onUpdated,
}: {
  item: AIFeedbackRecord;
  onUpdated: (item: AIFeedbackRecord) => void;
}) {
  const [nextStatus, setNextStatus] = useState<"in_review" | "resolved" | "dismissed">(
    item.status === "open" ? "in_review" : item.status === "in_review" ? "resolved" : item.status,
  );
  const [notes, setNotes] = useState(item.review_notes ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const terminal = item.status === "resolved" || item.status === "dismissed";

  async function save() {
    setBusy(true);
    setError(null);
    try {
      const updated = await reviewAIFeedback(item.id, {
        expected_updated_at: item.updated_at,
        status: nextStatus,
        ...(notes.trim() ? { review_notes: notes.trim() } : {}),
      });
      onUpdated(updated);
    } catch (caught) {
      setError(apiErrorMessage(caught, "Feedback could not be updated."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <article className="min-w-0 py-5" data-feedback-id={item.id}>
      <div className="flex min-w-0 flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <MessageSquareWarning className="h-4 w-4 shrink-0 text-[var(--color-brand-600)]" aria-hidden />
            <span className="text-sm font-semibold text-[var(--color-ink)]">{label(item.surface)}</span>
            <span className="rounded-md border border-[var(--color-line)] px-2 py-0.5 text-xs text-[var(--color-mute)]">{label(item.status)}</span>
            {item.priority === "high" ? (
              <span className="rounded-md bg-[var(--color-danger-50)] px-2 py-0.5 text-xs font-semibold text-[var(--color-danger-700)]">High priority</span>
            ) : null}
          </div>
          <p className="mt-2 break-words text-sm text-[var(--color-ink-2)]">
            {item.feedback_type === "rating" ? label(item.rating) : label(item.category)}
          </p>
          {item.comment ? <p className="mt-1 whitespace-pre-wrap break-words text-sm text-[var(--color-mute)]">{item.comment}</p> : null}
          <p className="mt-2 break-all text-xs text-[var(--color-mute)]">
            {item.target_type} · {item.target_id} · {formatDate(item.created_at)}
          </p>
        </div>

        <div className="min-w-0 w-full lg:max-w-lg">
          <div className="flex min-w-0 flex-col gap-2 sm:flex-row">
            <select
              aria-label="Review status"
              value={nextStatus}
              disabled={terminal}
              onChange={(event) => setNextStatus(event.target.value as typeof nextStatus)}
              className="h-10 min-w-0 rounded-md border border-[var(--color-line)] bg-white px-2 text-sm sm:w-36"
            >
              <option value="in_review">In review</option>
              <option value="resolved">Resolved</option>
              <option value="dismissed">Dismissed</option>
            </select>
            <input
              aria-label="Review notes"
              value={notes}
              disabled={terminal}
              maxLength={2000}
              onChange={(event) => setNotes(event.target.value)}
              className="h-10 min-w-0 flex-1 rounded-md border border-[var(--color-line)] bg-white px-3 text-sm"
            />
            <button
              type="button"
              disabled={terminal || busy}
              onClick={() => void save()}
              className="inline-flex h-10 shrink-0 items-center justify-center gap-1.5 rounded-md bg-[var(--color-ink)] px-3 text-sm font-semibold text-white disabled:opacity-60"
            >
              {busy ? <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden /> : <CheckCircle2 className="h-4 w-4" aria-hidden />}
              Save
            </button>
          </div>
          {error ? <p className="mt-1 text-xs text-[var(--color-danger-600)]" role="alert">{error}</p> : null}
        </div>
      </div>
    </article>
  );
}
