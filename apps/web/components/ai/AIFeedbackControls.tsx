"use client";

import { Flag, LoaderCircle, ThumbsDown, ThumbsUp, X } from "lucide-react";
import { useId, useRef, useState } from "react";

import {
  type AIFeedbackCategory,
  submitProductGuideFeedback,
  submitWorkspaceAssistantFeedback,
} from "@/lib/api/ai-feedback";
import { apiErrorMessage } from "@/lib/api/config";

type ProductGuideTarget = {
  surface: "product_guide";
  targetType:
    | "product_guide_command"
    | "product_guide_section"
    | "product_guide_permission"
    | "product_guide_no_match";
  targetId: string;
  catalogFingerprint: string;
};

type AssistantTarget = {
  surface: "workspace_assistant";
  sessionId: string;
  turnId: string;
};

const REPORT_CATEGORIES: Array<{ value: AIFeedbackCategory; label: string }> = [
  { value: "answer_quality", label: "Answer quality" },
  { value: "wrong_navigation", label: "Wrong destination" },
  { value: "missing_permission_explanation", label: "Permission explanation" },
  { value: "unsafe_citation", label: "Citation or source" },
  { value: "outdated_guidance", label: "Outdated guidance" },
  { value: "missing_guidance", label: "Missing guidance" },
  { value: "other", label: "Other" },
];

function submissionKey() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `feedback-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function AIFeedbackControls({
  target,
  testId,
}: {
  target: ProductGuideTarget | AssistantTarget;
  testId?: string;
}) {
  const keys = useRef<Record<string, string>>({});
  const fieldId = useId();
  const [busy, setBusy] = useState<"rating" | "report" | null>(null);
  const [rating, setRating] = useState<"helpful" | "not_helpful" | null>(null);
  const [reportOpen, setReportOpen] = useState(false);
  const [category, setCategory] = useState<AIFeedbackCategory>("answer_quality");
  const [comment, setComment] = useState("");
  const [reported, setReported] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(
    semanticKey: string,
    detail:
      | { feedback_type: "rating"; rating: "helpful" | "not_helpful" }
      | { feedback_type: "report"; category: AIFeedbackCategory; comment?: string },
  ) {
    const key = (keys.current[semanticKey] ??= submissionKey());
    if (target.surface === "product_guide") {
      return submitProductGuideFeedback(
        {
          submission_key: key,
          target_type: target.targetType,
          target_id: target.targetId,
          catalog_fingerprint: target.catalogFingerprint,
        },
        detail,
      );
    }
    return submitWorkspaceAssistantFeedback(
      { submission_key: key, session_id: target.sessionId, turn_id: target.turnId },
      detail,
    );
  }

  async function rate(next: "helpful" | "not_helpful") {
    if (rating) return;
    setBusy("rating");
    setError(null);
    try {
      await submit(`rating:${next}`, { feedback_type: "rating", rating: next });
      setRating(next);
    } catch (caught) {
      setError(apiErrorMessage(caught, "Feedback could not be saved."));
    } finally {
      setBusy(null);
    }
  }

  async function report() {
    setBusy("report");
    setError(null);
    try {
      await submit(`report:${category}:${comment.trim()}`, {
        feedback_type: "report",
        category,
        ...(comment.trim() ? { comment: comment.trim() } : {}),
      });
      setReported(true);
      setReportOpen(false);
    } catch (caught) {
      setError(apiErrorMessage(caught, "Report could not be saved."));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="mt-3 min-w-0" data-testid={testId}>
      <div className="flex min-w-0 flex-wrap items-center gap-1.5">
        <button
          type="button"
          title="Helpful"
          aria-label="Mark as helpful"
          aria-pressed={rating === "helpful"}
          disabled={Boolean(rating) || busy !== null}
          onClick={() => void rate("helpful")}
          className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-[var(--color-line)] text-[var(--color-mute)] hover:text-[var(--color-ink)] disabled:cursor-default disabled:opacity-60"
        >
          {busy === "rating" ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <ThumbsUp className="h-4 w-4" />}
        </button>
        <button
          type="button"
          title="Not helpful"
          aria-label="Mark as not helpful"
          aria-pressed={rating === "not_helpful"}
          disabled={Boolean(rating) || busy !== null}
          onClick={() => void rate("not_helpful")}
          className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-[var(--color-line)] text-[var(--color-mute)] hover:text-[var(--color-ink)] disabled:cursor-default disabled:opacity-60"
        >
          <ThumbsDown className="h-4 w-4" />
        </button>
        <button
          type="button"
          title="Report an issue"
          aria-label="Report an issue"
          aria-expanded={reportOpen}
          disabled={reported || busy !== null}
          onClick={() => setReportOpen((current) => !current)}
          className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-[var(--color-line)] text-[var(--color-mute)] hover:text-[var(--color-danger-600)] disabled:cursor-default disabled:opacity-60"
        >
          <Flag className="h-4 w-4" />
        </button>
        {rating || reported ? (
          <span className="text-xs text-[var(--color-mute)]" role="status">Feedback received</span>
        ) : null}
      </div>

      {reportOpen ? (
        <div className="mt-2 max-w-xl border-l-2 border-[var(--color-line)] pl-3">
          <div className="flex items-center justify-between gap-2">
            <div className="min-w-0 flex-1">
              <label
                htmlFor={`${fieldId}-issue`}
                className="text-xs font-medium text-[var(--color-ink-2)]"
              >
                Issue
              </label>
              <select
                id={`${fieldId}-issue`}
                value={category}
                onChange={(event) => setCategory(event.target.value as AIFeedbackCategory)}
                className="mt-1 h-9 w-full rounded-md border border-[var(--color-line)] bg-white px-2 text-sm"
              >
                {REPORT_CATEGORIES.map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
            </div>
            <button
              type="button"
              title="Close report"
              aria-label="Close report"
              onClick={() => setReportOpen(false)}
              className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-[var(--color-mute)] hover:text-[var(--color-ink)]"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
          <label
            htmlFor={`${fieldId}-note`}
            className="mt-2 block text-xs font-medium text-[var(--color-ink-2)]"
          >
            Note
          </label>
          <textarea
            id={`${fieldId}-note`}
            value={comment}
            maxLength={1000}
            rows={2}
            onChange={(event) => setComment(event.target.value)}
            className="mt-1 w-full rounded-md border border-[var(--color-line)] bg-white px-2 py-1.5 text-sm"
          />
          <button
            type="button"
            disabled={busy !== null}
            onClick={() => void report()}
            className="mt-2 inline-flex h-9 items-center justify-center gap-1.5 rounded-md bg-[var(--color-ink)] px-3 text-xs font-semibold text-white disabled:opacity-60"
          >
            {busy === "report" ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Flag className="h-3.5 w-3.5" />}
            Submit report
          </button>
        </div>
      ) : null}
      {error ? <p className="mt-1 text-xs text-[var(--color-danger-600)]" role="alert">{error}</p> : null}
    </div>
  );
}
