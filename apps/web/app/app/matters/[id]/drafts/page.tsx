"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, FileText, Loader2, Plus, RefreshCcw, XCircle } from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { StatusBadge } from "@/components/ui/StatusBadge";
import {
  extractDraftingData,
  listDraftingData,
  listDrafts,
  reviewDraftingDataField,
} from "@/lib/api/endpoints";
import type { DraftingDataField } from "@/lib/api/schemas";

const DRAFT_TYPE_LABEL: Record<string, string> = {
  brief: "Brief",
  notice: "Notice",
  reply: "Reply",
  memo: "Internal memo",
  other: "Other",
};

export default function MatterDraftsPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const matterId = params.id;

  const query = useQuery({
    queryKey: ["matters", matterId, "drafts"],
    queryFn: () => listDrafts(matterId),
  });

  const drafts = query.data?.drafts ?? [];

  return (
    <div className="flex flex-col gap-5">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-[var(--color-ink)]">
            Drafting studio
          </h2>
          <p className="text-sm text-[var(--color-mute)]">
            Citation-grounded drafts. Every new version resets status to draft
            until a partner signs off.
          </p>
        </div>
        <NewDraftDialog matterId={matterId} />
      </header>

      <DraftingDataReviewQueue matterId={matterId} />

      {query.isPending ? (
        <div className="flex flex-col gap-3">
          <Skeleton className="h-12 w-full" />
          <Skeleton className="h-12 w-full" />
        </div>
      ) : query.isError ? (
        <QueryErrorState
          title="Could not load drafts"
          error={query.error}
          onRetry={query.refetch}
        />
      ) : drafts.length === 0 ? (
        <EmptyState
          icon={FileText}
          title="No drafts yet"
          description="Start the first draft — the studio will assemble matter context, retrieved authorities, and a citation-checked body. You stay in control of approval."
          action={<NewDraftDialog matterId={matterId} />}
        />
      ) : (
        <ul className="flex flex-col gap-3">
          {drafts.map((d) => (
            <li
              key={d.id}
              className="rounded-xl border border-[var(--color-line)] bg-white p-4 transition-colors hover:bg-[var(--color-bg-2)]"
            >
              <button
                type="button"
                onClick={() => router.push(`/app/matters/${matterId}/drafts/${d.id}`)}
                className="flex w-full flex-wrap items-center justify-between gap-3 text-left focus-visible:outline-none"
                data-testid={`draft-row-${d.id}`}
              >
                <div className="flex min-w-0 flex-col gap-1">
                  <div className="flex items-center gap-2 text-sm font-semibold text-[var(--color-ink)]">
                    <FileText className="h-4 w-4 text-[var(--color-brand-700)]" aria-hidden />
                    {d.title}
                  </div>
                  <div className="flex flex-wrap items-center gap-2 text-xs text-[var(--color-mute)]">
                    <span className="tabular">
                      {DRAFT_TYPE_LABEL[d.draft_type]}
                    </span>
                    <span>·</span>
                    <span>
                      {d.versions.length > 0
                        ? `Revision ${Math.max(...d.versions.map((v) => v.revision))}`
                        : "No version yet"}
                    </span>
                    <span>·</span>
                    <span>
                      Updated{" "}
                      {new Date(d.updated_at).toLocaleDateString(undefined, {
                        day: "2-digit",
                        month: "short",
                        year: "numeric",
                      })}
                    </span>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {d.review_required ? (
                    <span className="inline-flex items-center gap-1 rounded-full border border-[var(--color-warning-500)]/40 bg-[var(--color-warning-500)]/10 px-2 py-0.5 text-xs text-[var(--color-ink)]">
                      Review required
                    </span>
                  ) : null}
                  <StatusBadge status={d.status} />
                </div>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

const FIELD_STATUS_LABEL: Record<DraftingDataField["status"], string> = {
  suggested: "Suggested",
  needs_review: "Needs review",
  confirmed: "Confirmed",
  overridden: "Overridden",
  rejected: "Rejected",
};

const CONFIDENCE_LABEL: Record<DraftingDataField["confidence_band"], string> = {
  high: "High",
  medium: "Medium",
  low: "Low",
};

function DraftingDataReviewQueue({ matterId }: { matterId: string }) {
  const queryClient = useQueryClient();
  const [overrideValues, setOverrideValues] = useState<Record<string, string>>({});

  const query = useQuery({
    queryKey: ["matters", matterId, "drafting-data"],
    queryFn: () => listDraftingData(matterId),
  });

  const refresh = async () => {
    await queryClient.invalidateQueries({
      queryKey: ["matters", matterId, "drafting-data"],
    });
  };

  const extract = useMutation({
    mutationFn: () => extractDraftingData(matterId),
    onSuccess: async (data) => {
      await refresh();
      toast.success(
        data.created_count > 0
          ? `Added ${data.created_count} drafting field suggestion${data.created_count === 1 ? "" : "s"}`
          : "Drafting field suggestions are up to date",
      );
    },
    onError: () => toast.error("Could not extract drafting data."),
  });

  const review = useMutation({
    mutationFn: (input: {
      fieldId: string;
      action: "confirm" | "override" | "reject";
      overrideValue?: string | null;
    }) =>
      reviewDraftingDataField({
        matterId,
        fieldId: input.fieldId,
        action: input.action,
        overrideValue: input.overrideValue,
      }),
    onSuccess: async () => {
      await refresh();
      toast.success("Drafting field updated");
    },
    onError: () => toast.error("Could not update the drafting field."),
  });

  const fields = query.data?.fields ?? [];
  const reviewedCount = (query.data?.counts.confirmed ?? 0) + (query.data?.counts.overridden ?? 0);

  return (
    <section className="rounded-xl border border-[var(--color-line)] bg-white p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-1">
          <h3 className="text-sm font-semibold text-[var(--color-ink)]">
            Drafting data review queue
          </h3>
          <p className="text-xs text-[var(--color-mute)]">
            Confirmed or overridden fields feed draft generation. Pending and rejected suggestions stay out.
          </p>
        </div>
        <Button
          type="button"
          variant="secondary"
          size="sm"
          onClick={() => extract.mutate()}
          disabled={extract.isPending}
          data-testid="drafting-data-extract"
        >
          {extract.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
          ) : (
            <RefreshCcw className="h-4 w-4" aria-hidden />
          )}
          Extract fields
        </Button>
      </div>

      <div className="mt-3 flex flex-wrap gap-2 text-xs text-[var(--color-mute)]">
        <span>{fields.length} suggestions</span>
        <span>{reviewedCount} reviewed</span>
      </div>

      {query.isPending ? (
        <div className="mt-4 flex flex-col gap-2">
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
        </div>
      ) : query.isError ? (
        <div className="mt-4">
          <QueryErrorState
            title="Could not load drafting data"
            error={query.error}
            onRetry={query.refetch}
          />
        </div>
      ) : fields.length === 0 ? (
        <p className="mt-4 text-sm text-[var(--color-mute)]">
          No reviewed drafting data yet.
        </p>
      ) : (
        <ul className="mt-4 flex flex-col gap-3">
          {fields.map((field) => (
            <li
              key={field.id}
              className="rounded-lg border border-[var(--color-line)] bg-[var(--color-bg-2)] p-3"
              data-testid={`drafting-data-field-${field.field_key}`}
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h4 className="text-sm font-semibold text-[var(--color-ink)]">
                      {field.label}
                    </h4>
                    <span className="rounded-full border border-[var(--color-line)] bg-white px-2 py-0.5 text-xs text-[var(--color-mute)]">
                      {FIELD_STATUS_LABEL[field.status]}
                    </span>
                    <span className="rounded-full border border-[var(--color-line)] bg-white px-2 py-0.5 text-xs text-[var(--color-mute)]">
                      {CONFIDENCE_LABEL[field.confidence_band]} confidence
                    </span>
                  </div>
                  <p className="mt-1 break-words text-sm text-[var(--color-ink)]">
                    {field.effective_value ?? field.proposed_value}
                  </p>
                  {field.source_snippet ? (
                    <blockquote className="mt-2 border-l-2 border-[var(--color-line)] pl-3 text-xs text-[var(--color-mute)]">
                      {field.source_snippet}
                    </blockquote>
                  ) : (
                    <p className="mt-2 text-xs text-[var(--color-mute)]">
                      Source snippet not verified.
                    </p>
                  )}
                </div>
                <div className="flex min-w-[220px] flex-col gap-2">
                  <div className="flex gap-2">
                    <Button
                      type="button"
                      size="sm"
                      variant="secondary"
                      disabled={review.isPending}
                      onClick={() =>
                        review.mutate({ fieldId: field.id, action: "confirm" })
                      }
                      data-testid={`drafting-data-confirm-${field.field_key}`}
                    >
                      <CheckCircle2 className="h-4 w-4" aria-hidden />
                      Confirm
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      disabled={review.isPending}
                      onClick={() =>
                        review.mutate({ fieldId: field.id, action: "reject" })
                      }
                      data-testid={`drafting-data-reject-${field.field_key}`}
                    >
                      <XCircle className="h-4 w-4" aria-hidden />
                      Reject
                    </Button>
                  </div>
                  <div className="flex gap-2">
                    <input
                      className="min-w-0 flex-1 rounded-md border border-[var(--color-line)] px-2 py-1 text-sm"
                      value={overrideValues[field.id] ?? ""}
                      onChange={(event) =>
                        setOverrideValues((current) => ({
                          ...current,
                          [field.id]: event.target.value,
                        }))
                      }
                      placeholder="Override value"
                      data-testid={`drafting-data-override-input-${field.field_key}`}
                    />
                    <Button
                      type="button"
                      size="sm"
                      disabled={review.isPending || !(overrideValues[field.id] ?? "").trim()}
                      onClick={() =>
                        review.mutate({
                          fieldId: field.id,
                          action: "override",
                          overrideValue: overrideValues[field.id],
                        })
                      }
                      data-testid={`drafting-data-override-${field.field_key}`}
                    >
                      Override
                    </Button>
                  </div>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// Ram BUG-2026-05-01 / ENH-004 root-cause fix:
//
// The previous "New draft" dialog opened a 5-option form (Brief /
// Notice / Reply / Internal memo / Other) — completely bypassing the
// 20 specialised templates the backend ships (Sprints 1+2). A user
// clicking "New draft" never saw the bail / writ / quashing / civil
// suit / written statement / etc. templates because the dialog short-
// circuited the template grid entirely.
//
// Fix: replace the dialog with a Link that routes to the template
// grid (/app/matters/{id}/drafts/new). The grid is the single source
// of truth for "all available templates" — the user picks one, the
// stepper opens, and the resulting draft inherits the right
// template_type. Legacy generic types (brief/notice/reply/memo/other)
// remain accessible as catch-all entries inside the grid for users
// who don't need a structured template.
function NewDraftDialog({ matterId }: { matterId: string }) {
  return (
    <Button
      href={`/app/matters/${matterId}/drafts/new`}
      data-testid="new-draft-trigger"
    >
      <Plus className="h-4 w-4" aria-hidden /> New draft
    </Button>
  );
}
