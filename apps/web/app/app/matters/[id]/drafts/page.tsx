"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, Loader2, Plus } from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { Button } from "@/components/ui/Button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/Dialog";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/Select";
import { Skeleton } from "@/components/ui/Skeleton";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { ApiError } from "@/lib/api/config";
import { createDraft, listDrafts } from "@/lib/api/endpoints";
import type { DraftType } from "@/lib/api/schemas";

const DRAFT_TYPE_LABEL: Record<DraftType, string> = {
  brief: "Brief",
  notice: "Notice",
  reply: "Reply",
  memo: "Internal memo",
  other: "Other",
};

const createSchema = z.object({
  title: z.string().min(3, "At least 3 characters."),
  draft_type: z.enum(["brief", "notice", "reply", "memo", "other"]),
});

type CreateForm = z.infer<typeof createSchema>;

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

function NewDraftDialog({ matterId }: { matterId: string }) {
  const [open, setOpen] = useState(false);
  const router = useRouter();
  const queryClient = useQueryClient();
  const form = useForm<CreateForm>({
    resolver: zodResolver(createSchema),
    defaultValues: { title: "", draft_type: "brief" },
  });

  const mutation = useMutation({
    mutationFn: (values: CreateForm) =>
      createDraft({
        matterId,
        title: values.title.trim(),
        draftType: values.draft_type,
      }),
    onSuccess: async (draft) => {
      await queryClient.invalidateQueries({
        queryKey: ["matters", matterId, "drafts"],
      });
      toast.success("Draft created");
      form.reset();
      setOpen(false);
      router.push(`/app/matters/${matterId}/drafts/${draft.id}`);
    },
    onError: (err) => {
      toast.error(
        err instanceof ApiError ? err.detail : "Could not create draft.",
      );
    },
  });

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button data-testid="new-draft-trigger">
          <Plus className="h-4 w-4" aria-hidden /> New draft
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>New draft</DialogTitle>
          <DialogDescription>
            Creates the draft shell — generate the first version from the
            editor.
          </DialogDescription>
        </DialogHeader>
        <form
          className="flex flex-col gap-4"
          onSubmit={form.handleSubmit((values) => mutation.mutate(values))}
          noValidate
        >
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="draft-title">Title</Label>
            <Input
              id="draft-title"
              placeholder="Interim reply brief"
              autoFocus
              aria-invalid={form.formState.errors.title ? true : undefined}
              aria-describedby={form.formState.errors.title ? "draft-title-error" : undefined}
              {...form.register("title")}
            />
            {form.formState.errors.title ? (
              <p
                id="draft-title-error"
                role="alert"
                className="text-xs text-[var(--color-danger-500,#c53030)]"
              >
                {form.formState.errors.title.message}
              </p>
            ) : null}
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="draft-type">Type</Label>
            <Select
              value={form.watch("draft_type")}
              onValueChange={(v) =>
                form.setValue("draft_type", v as DraftType)
              }
            >
              <SelectTrigger id="draft-type">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {(Object.entries(DRAFT_TYPE_LABEL) as [DraftType, string][]).map(
                  ([value, label]) => (
                    <SelectItem key={value} value={value}>
                      {label}
                    </SelectItem>
                  ),
                )}
              </SelectContent>
            </Select>
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                form.reset();
                setOpen(false);
              }}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={mutation.isPending}>
              {mutation.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" /> Creating…
                </>
              ) : (
                "Create draft"
              )}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
