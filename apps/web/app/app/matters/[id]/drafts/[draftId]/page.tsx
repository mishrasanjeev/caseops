"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  CheckCircle2,
  Download,
  Lock,
  Loader2,
  RefreshCcw,
  Send,
  ShieldCheck,
  Undo2,
} from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { toast } from "sonner";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { ApiError } from "@/lib/api/config";
import {
  approveDraft,
  draftDocxUrl,
  fetchDraft,
  finalizeDraft,
  generateDraftVersion,
  requestDraftChanges,
  submitDraft,
} from "@/lib/api/endpoints";
import type { Draft, DraftStatus } from "@/lib/api/schemas";

const ACTION_LABEL: Record<string, string> = {
  submit: "Submitted for review",
  request_changes: "Requested changes",
  approve: "Approved",
  finalize: "Finalized",
};

export default function MatterDraftDetailPage() {
  const params = useParams<{ id: string; draftId: string }>();
  const matterId = params.id;
  const draftId = params.draftId;
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: ["matters", matterId, "drafts", draftId],
    queryFn: () => fetchDraft({ matterId, draftId }),
  });

  const refreshCaches = async () => {
    await queryClient.invalidateQueries({
      queryKey: ["matters", matterId, "drafts"],
    });
    await query.refetch();
  };

  const makeError = (fallback: string) => (err: unknown) => {
    toast.error(err instanceof ApiError ? err.detail : fallback);
  };
  const makeSuccess = (label: string) => async () => {
    await refreshCaches();
    toast.success(label);
  };

  const generate = useMutation({
    mutationFn: () => generateDraftVersion({ matterId, draftId }),
    onSuccess: makeSuccess("New version drafted"),
    onError: makeError("Could not generate a new version."),
  });
  const submit = useMutation({
    mutationFn: () => submitDraft(matterId, draftId),
    onSuccess: makeSuccess("Submitted for review"),
    onError: makeError("Could not submit draft."),
  });
  const requestChanges = useMutation({
    mutationFn: () => requestDraftChanges(matterId, draftId),
    onSuccess: makeSuccess("Changes requested"),
    onError: makeError("Could not request changes."),
  });
  const approve = useMutation({
    mutationFn: () => approveDraft(matterId, draftId),
    onSuccess: makeSuccess("Draft approved"),
    onError: makeError(
      "Could not approve — regenerate with grounded citations if citations are unverified.",
    ),
  });
  const finalize = useMutation({
    mutationFn: () => finalizeDraft(matterId, draftId),
    onSuccess: makeSuccess("Draft finalized"),
    onError: makeError("Could not finalize draft."),
  });

  return (
    <div className="flex flex-col gap-5">
      <Link
        href={`/app/matters/${matterId}/drafts`}
        className="inline-flex items-center gap-1.5 text-xs font-medium text-[var(--color-mute)] hover:text-[var(--color-ink)]"
      >
        <ArrowLeft className="h-3.5 w-3.5" aria-hidden /> Back to drafts
      </Link>

      {query.isPending ? (
        <div className="flex flex-col gap-3">
          <Skeleton className="h-8 w-72" />
          <Skeleton className="h-6 w-40" />
          <Skeleton className="h-96 w-full" />
        </div>
      ) : query.isError ? (
        <QueryErrorState
          title="Could not load this draft"
          error={query.error}
          onRetry={query.refetch}
        />
      ) : query.data ? (
        <DraftBody
          draft={query.data}
          matterId={matterId}
          onGenerate={() => generate.mutate()}
          onSubmit={() => submit.mutate()}
          onRequestChanges={() => requestChanges.mutate()}
          onApprove={() => approve.mutate()}
          onFinalize={() => finalize.mutate()}
          generating={generate.isPending}
          transitioning={
            submit.isPending ||
            requestChanges.isPending ||
            approve.isPending ||
            finalize.isPending
          }
        />
      ) : null}
    </div>
  );
}

function DraftBody({
  draft,
  matterId,
  onGenerate,
  onSubmit,
  onRequestChanges,
  onApprove,
  onFinalize,
  generating,
  transitioning,
}: {
  draft: Draft;
  matterId: string;
  onGenerate: () => void;
  onSubmit: () => void;
  onRequestChanges: () => void;
  onApprove: () => void;
  onFinalize: () => void;
  generating: boolean;
  transitioning: boolean;
}) {
  const currentVersion = draft.versions.find(
    (v) => v.id === draft.current_version_id,
  );
  const status: DraftStatus = draft.status;
  const isFinalized = status === "finalized";
  const canRegenerate = !isFinalized;
  const canSubmit =
    !isFinalized && (status === "draft" || status === "changes_requested");
  const canRequestChanges = status === "in_review";
  const canApprove = status === "in_review";
  const canFinalize = status === "approved";
  const canExport = !!currentVersion;

  const verifiedCount = currentVersion?.verified_citation_count ?? 0;

  return (
    <div className="flex flex-col gap-5">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-[var(--color-ink)]">
            {draft.title}
          </h1>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-[var(--color-mute)]">
            <span className="capitalize">{draft.draft_type}</span>
            <span>·</span>
            <span>
              {currentVersion
                ? `Revision ${currentVersion.revision}`
                : "No version generated yet"}
            </span>
            <span>·</span>
            <StatusBadge status={status} />
            {draft.review_required ? (
              <span className="inline-flex items-center gap-1 rounded-full border border-[var(--color-warning-500)]/40 bg-[var(--color-warning-500)]/10 px-2 py-0.5 text-[var(--color-ink)]">
                <ShieldCheck className="h-3 w-3" aria-hidden /> Review required
              </span>
            ) : null}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="outline"
            onClick={onGenerate}
            disabled={!canRegenerate || generating || transitioning}
            data-testid="draft-generate"
          >
            {generating ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Generating…
              </>
            ) : (
              <>
                <RefreshCcw className="h-4 w-4" aria-hidden />
                {currentVersion ? "Regenerate" : "Generate"}
              </>
            )}
          </Button>
          {canSubmit ? (
            <Button
              onClick={onSubmit}
              disabled={transitioning || !currentVersion}
              data-testid="draft-submit"
            >
              <Send className="h-4 w-4" aria-hidden /> Submit for review
            </Button>
          ) : null}
          {canRequestChanges ? (
            <Button
              variant="outline"
              onClick={onRequestChanges}
              disabled={transitioning}
              data-testid="draft-request-changes"
            >
              <Undo2 className="h-4 w-4" aria-hidden /> Request changes
            </Button>
          ) : null}
          {canApprove ? (
            <Button
              onClick={onApprove}
              disabled={transitioning}
              data-testid="draft-approve"
            >
              <CheckCircle2 className="h-4 w-4" aria-hidden /> Approve
            </Button>
          ) : null}
          {canFinalize ? (
            <Button
              onClick={onFinalize}
              disabled={transitioning}
              data-testid="draft-finalize"
            >
              <Lock className="h-4 w-4" aria-hidden /> Finalize
            </Button>
          ) : null}
          {canExport ? (
            <Button
              variant="outline"
              href={draftDocxUrl(matterId, draft.id)}
              data-testid="draft-download-docx"
            >
              <Download className="h-4 w-4" aria-hidden /> Download DOCX
            </Button>
          ) : null}
        </div>
      </header>

      <div className="grid gap-5 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle as="h2">Draft body</CardTitle>
            <CardDescription>
              {currentVersion
                ? `Generated ${new Date(currentVersion.created_at).toLocaleString()}`
                : "No version yet — generate one to populate the editor."}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {currentVersion ? (
              <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed text-[var(--color-ink-2)]">
                {currentVersion.body}
              </pre>
            ) : (
              <p className="text-sm text-[var(--color-mute)]">
                Click <em>Generate</em> to draft the first version using the
                matter context + retrieved authorities.
              </p>
            )}
          </CardContent>
        </Card>

        <div className="flex flex-col gap-5">
          <Card>
            <CardHeader>
              <CardTitle as="h2">Citations</CardTitle>
              <CardDescription>
                {verifiedCount > 0
                  ? `${verifiedCount} verified citation${verifiedCount === 1 ? "" : "s"}.`
                  : "No verified citations yet — approve will be blocked."}
              </CardDescription>
            </CardHeader>
            <CardContent>
              {currentVersion && currentVersion.citations.length > 0 ? (
                <ul className="flex flex-col gap-1.5 text-sm tabular">
                  {currentVersion.citations.map((c) => (
                    <li
                      key={c}
                      className="rounded-md border border-[var(--color-line)] bg-[var(--color-bg)] px-2.5 py-1.5 font-mono text-xs"
                    >
                      {c}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-[var(--color-mute)]">
                  The model did not cite any authority this version. Regenerate
                  after enriching the matter context.
                </p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle as="h2">Review history</CardTitle>
              <CardDescription>
                Every transition is audited.
              </CardDescription>
            </CardHeader>
            <CardContent>
              {draft.reviews.length === 0 ? (
                <p className="text-sm text-[var(--color-mute)]">
                  No review actions yet.
                </p>
              ) : (
                <ol className="flex flex-col gap-2 text-sm">
                  {draft.reviews.map((r) => (
                    <li
                      key={r.id}
                      className="rounded-md border border-[var(--color-line-2)] bg-[var(--color-bg)] px-2.5 py-1.5"
                    >
                      <div className="flex items-center justify-between text-xs">
                        <span className="font-medium text-[var(--color-ink)]">
                          {ACTION_LABEL[r.action] ?? r.action}
                        </span>
                        <span className="tabular text-[var(--color-mute)]">
                          {new Date(r.created_at).toLocaleString(undefined, {
                            day: "2-digit",
                            month: "short",
                            hour: "2-digit",
                            minute: "2-digit",
                          })}
                        </span>
                      </div>
                      {r.notes ? (
                        <p className="mt-1 text-xs text-[var(--color-mute)]">
                          {r.notes}
                        </p>
                      ) : null}
                    </li>
                  ))}
                </ol>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
