"use client";

import { useQuery } from "@tanstack/react-query";
import { FileText, Plus } from "lucide-react";
import { useParams, useRouter } from "next/navigation";

import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { listDrafts } from "@/lib/api/endpoints";

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
