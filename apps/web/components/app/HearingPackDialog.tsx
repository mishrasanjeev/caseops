"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, FileText, Loader2, ShieldCheck, Sparkles } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

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
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { ApiError } from "@/lib/api/config";
import {
  fetchHearingPack,
  generateHearingPack,
  reviewHearingPack,
} from "@/lib/api/endpoints";
import type { HearingPack, HearingPackItemKind } from "@/lib/api/schemas";

const KIND_LABEL: Record<HearingPackItemKind, string> = {
  chronology: "Chronology",
  last_order: "Last order",
  pending_compliance: "Pending compliance",
  issue: "Issues",
  opposition_point: "Opposition points",
  authority_card: "Authority cards",
  oral_point: "Oral points",
};

const KIND_ORDER: HearingPackItemKind[] = [
  "chronology",
  "last_order",
  "pending_compliance",
  "issue",
  "opposition_point",
  "authority_card",
  "oral_point",
];

export function HearingPackDialog({
  matterId,
  hearingId,
  label,
}: {
  matterId: string;
  hearingId: string;
  label?: string;
}) {
  const [open, setOpen] = useState(false);
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: ["matters", matterId, "hearings", hearingId, "pack"],
    queryFn: () => fetchHearingPack({ matterId, hearingId }),
    enabled: open,
  });

  const generate = useMutation({
    mutationFn: () => generateHearingPack({ matterId, hearingId }),
    onSuccess: async (pack) => {
      queryClient.setQueryData(
        ["matters", matterId, "hearings", hearingId, "pack"],
        pack,
      );
      toast.success("Hearing pack drafted — review before sharing.");
    },
    onError: (err) => {
      const msg =
        err instanceof ApiError
          ? err.detail
          : "Could not assemble a hearing pack.";
      toast.error(msg);
    },
  });

  const review = useMutation({
    mutationFn: (packId: string) => reviewHearingPack({ matterId, packId }),
    onSuccess: async (pack) => {
      queryClient.setQueryData(
        ["matters", matterId, "hearings", hearingId, "pack"],
        pack,
      );
      toast.success("Pack marked reviewed.");
    },
    onError: (err) => {
      const msg =
        err instanceof ApiError ? err.detail : "Could not save the review.";
      toast.error(msg);
    },
  });

  const pack = query.data;

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" data-testid="hearing-pack-trigger">
          <FileText className="h-4 w-4" aria-hidden />
          {label ?? "Hearing pack"}
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Hearing pack</DialogTitle>
          <DialogDescription>
            Citation-grounded brief for the bench. Marked{" "}
            <em>review_required</em> until a partner signs off.
          </DialogDescription>
        </DialogHeader>

        {query.isPending ? (
          <div className="flex flex-col gap-3 px-6 py-4">
            <Skeleton className="h-4 w-24" />
            <Skeleton className="h-6 w-full" />
            <Skeleton className="h-24 w-full" />
          </div>
        ) : query.isError ? (
          <QueryErrorState
            title="Could not load the pack"
            error={query.error}
            onRetry={query.refetch}
          />
        ) : pack ? (
          <PackView
            pack={pack}
            onReview={() => review.mutate(pack.id)}
            reviewing={review.isPending}
          />
        ) : (
          <EmptyState
            icon={Sparkles}
            title="No pack generated yet"
            description="Generate a hearing pack from the matter context, the last order, open tasks, and recent activity. Every pack arrives as a draft until reviewed."
            action={
              <Button
                onClick={() => generate.mutate()}
                disabled={generate.isPending}
                data-testid="generate-hearing-pack"
              >
                {generate.isPending ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Generating…
                  </>
                ) : (
                  <>
                    <Sparkles className="h-4 w-4" aria-hidden /> Generate pack
                  </>
                )}
              </Button>
            }
          />
        )}

        {pack ? (
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => generate.mutate()}
              disabled={generate.isPending}
            >
              {generate.isPending ? "Regenerating…" : "Regenerate"}
            </Button>
            <Button
              onClick={() => setOpen(false)}
              variant={pack.status === "reviewed" ? "outline" : "ghost"}
            >
              Close
            </Button>
          </DialogFooter>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

function PackView({
  pack,
  onReview,
  reviewing,
}: {
  pack: HearingPack;
  onReview: () => void;
  reviewing: boolean;
}) {
  const grouped = KIND_ORDER.map((kind) => ({
    kind,
    label: KIND_LABEL[kind],
    items: pack.items.filter((item) => item.item_type === kind),
  })).filter((group) => group.items.length > 0);

  return (
    <div className="flex flex-col gap-4 px-6 pb-2">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        {pack.status === "reviewed" ? (
          <span className="inline-flex items-center gap-1.5 rounded-full border border-[var(--color-success-500)]/40 bg-[var(--color-success-500)]/10 px-2.5 py-1 text-[var(--color-success-500)]">
            <CheckCircle2 className="h-3.5 w-3.5" aria-hidden /> Reviewed
          </span>
        ) : (
          <span className="inline-flex items-center gap-1.5 rounded-full border border-[var(--color-warning-500)]/40 bg-[var(--color-warning-500)]/10 px-2.5 py-1 text-[var(--color-ink)]">
            <ShieldCheck className="h-3.5 w-3.5" aria-hidden /> Review required
          </span>
        )}
        <span className="text-[var(--color-mute)]">
          Generated {new Date(pack.generated_at).toLocaleString()}
        </span>
      </div>

      <p className="text-sm leading-relaxed text-[var(--color-ink-2)]">
        {pack.summary}
      </p>

      <div className="flex flex-col gap-4">
        {grouped.map((group) => (
          <section key={group.kind} className="flex flex-col gap-2">
            <h3 className="text-xs font-semibold uppercase tracking-[0.14em] text-[var(--color-mute-2)]">
              {group.label}
            </h3>
            <ul className="flex flex-col gap-2">
              {group.items.map((item) => (
                <li
                  key={item.id}
                  className="rounded-lg border border-[var(--color-line)] bg-[var(--color-bg)] px-3 py-2"
                >
                  <div className="text-sm font-medium text-[var(--color-ink)]">
                    {item.title}
                  </div>
                  <p className="mt-1 text-sm leading-relaxed text-[var(--color-ink-2)]">
                    {item.body}
                  </p>
                  {item.source_ref ? (
                    <div className="mt-1 text-xs tabular text-[var(--color-mute)]">
                      Source: <span className="font-mono">{item.source_ref}</span>
                    </div>
                  ) : null}
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>

      {pack.status !== "reviewed" ? (
        <div className="flex justify-end">
          <Button
            onClick={onReview}
            disabled={reviewing}
            data-testid="mark-pack-reviewed"
          >
            {reviewing ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Saving…
              </>
            ) : (
              <>
                <CheckCircle2 className="h-4 w-4" aria-hidden /> Mark reviewed
              </>
            )}
          </Button>
        </div>
      ) : null}
    </div>
  );
}
