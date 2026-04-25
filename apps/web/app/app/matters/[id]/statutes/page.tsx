"use client";

/**
 * MOD-TS-017 Slice S4 (2026-04-25). Matter cockpit Statutes sub-tab.
 *
 * Lists statute sections attached to this matter (cited / opposing /
 * context). 'Add reference' opens a 2-step picker: Act → Section.
 * Each row clicks through to the bare-acts browser. Delete removes
 * the link.
 *
 * The drafting flow reads these references and injects bare section
 * text into the appeal-memorandum prompt for verbatim quoting (per
 * PRD §16.2).
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BookOpenCheck,
  ExternalLink,
  Loader2,
  Plus,
  Trash2,
} from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/Card";
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
import {
  addMatterStatuteReference,
  deleteMatterStatuteReference,
  listMatterStatuteReferences,
  listStatuteSections,
  listStatutes,
  type MatterStatuteReferenceRecord,
} from "@/lib/api/endpoints";

type Relevance = "cited" | "opposing" | "context";

const RELEVANCE_TONE: Record<Relevance, "brand" | "warning" | "neutral"> = {
  cited: "brand",
  opposing: "warning",
  context: "neutral",
};

export default function MatterStatutesPage() {
  const params = useParams<{ id: string }>();
  const matterId = params.id;
  const queryClient = useQueryClient();
  const refsQuery = useQuery({
    queryKey: ["matter", matterId, "statute-references"],
    queryFn: () => listMatterStatuteReferences(matterId),
    enabled: Boolean(matterId),
  });

  const deleteMutation = useMutation({
    mutationFn: (referenceId: string) =>
      deleteMatterStatuteReference(matterId, referenceId),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["matter", matterId, "statute-references"],
      });
      toast.success("Statute reference removed.");
    },
    onError: () => toast.error("Could not remove the statute reference."),
  });

  if (refsQuery.isPending) {
    return <Skeleton className="h-64 w-full" />;
  }
  if (refsQuery.isError) {
    return (
      <QueryErrorState
        title="Could not load statute references"
        error={refsQuery.error}
        onRetry={() => refsQuery.refetch()}
      />
    );
  }
  const refs = refsQuery.data?.references ?? [];

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
        <div>
          <CardTitle>Statutes referenced</CardTitle>
          <CardDescription>
            Sections this matter relies on or distinguishes. The
            drafting flow injects bare text from these into the
            appeal-memorandum prompt for verbatim quoting.
          </CardDescription>
        </div>
        <AddReferenceDialog matterId={matterId} />
      </CardHeader>
      <CardContent>
        {refs.length === 0 ? (
          <EmptyState
            icon={BookOpenCheck}
            title="No statutes attached yet"
            description="Click 'Add reference' to link the sections this matter cites — they'll feed the drafting prompt automatically."
          />
        ) : (
          <ul
            className="flex flex-col gap-2"
            data-testid="matter-statute-refs-list"
          >
            {refs.map((r) => (
              <RefRow
                key={r.id}
                ref={r}
                onDelete={() => deleteMutation.mutate(r.id)}
                disabled={deleteMutation.isPending}
              />
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function RefRow({
  ref,
  onDelete,
  disabled,
}: {
  ref: MatterStatuteReferenceRecord;
  onDelete: () => void;
  disabled: boolean;
}) {
  return (
    <li
      className="flex items-start justify-between gap-3 rounded-md border border-[var(--color-line)] bg-white p-3"
      data-testid={`matter-statute-ref-${ref.id}`}
    >
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-2">
          <Link
            href={`/app/statutes/${ref.statute_id}/sections/${encodeURIComponent(ref.section_number)}`}
            className="font-mono text-sm font-semibold text-[var(--color-ink)] hover:text-[var(--color-brand-600)] hover:underline"
          >
            {ref.statute_short_name} {ref.section_number}
          </Link>
          <Badge tone={RELEVANCE_TONE[ref.relevance as Relevance]}>
            {ref.relevance}
          </Badge>
        </div>
        {ref.section_label ? (
          <div className="mt-0.5 text-xs text-[var(--color-mute)]">
            {ref.section_label}
          </div>
        ) : null}
        {ref.section_url ? (
          <a
            href={ref.section_url}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-1 inline-flex items-center gap-1 text-xs text-[var(--color-brand-600)] hover:underline"
          >
            indiacode.nic.in
            <ExternalLink className="h-3 w-3" aria-hidden />
          </a>
        ) : null}
      </div>
      <Button
        variant="ghost"
        size="sm"
        onClick={onDelete}
        disabled={disabled}
        aria-label={`Remove ${ref.statute_short_name} ${ref.section_number}`}
      >
        <Trash2 className="h-4 w-4" aria-hidden />
      </Button>
    </li>
  );
}

function AddReferenceDialog({ matterId }: { matterId: string }) {
  const [open, setOpen] = useState(false);
  const [statuteId, setStatuteId] = useState<string>("");
  const [sectionId, setSectionId] = useState<string>("");
  const [relevance, setRelevance] = useState<Relevance>("cited");
  const queryClient = useQueryClient();

  const statutesQuery = useQuery({
    queryKey: ["statutes", "list"],
    queryFn: listStatutes,
    enabled: open,
    staleTime: 30 * 60_000,
  });
  const sectionsQuery = useQuery({
    queryKey: ["statutes", statuteId, "sections"],
    queryFn: () => listStatuteSections(statuteId),
    enabled: open && Boolean(statuteId),
    staleTime: 30 * 60_000,
  });

  const addMutation = useMutation({
    mutationFn: () =>
      addMatterStatuteReference(matterId, {
        section_id: sectionId,
        relevance,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["matter", matterId, "statute-references"],
      });
      toast.success("Statute reference attached.");
      setOpen(false);
      setStatuteId("");
      setSectionId("");
      setRelevance("cited");
    },
    onError: (e: unknown) =>
      toast.error(
        e instanceof Error ? e.message : "Could not attach the statute.",
      ),
  });

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button data-testid="matter-statute-add-trigger">
          <Plus className="h-4 w-4" aria-hidden /> Add reference
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add statute reference</DialogTitle>
          <DialogDescription>
            Pick the Act → Section, then how this matter relates to it.
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium">Act</span>
            <select
              className="rounded-md border border-[var(--color-line)] bg-white px-3 py-2 text-sm"
              value={statuteId}
              onChange={(e) => {
                setStatuteId(e.target.value);
                setSectionId("");
              }}
              data-testid="matter-statute-act-select"
            >
              <option value="">Select an Act…</option>
              {(statutesQuery.data?.statutes ?? []).map((s) => (
                <option key={s.id} value={s.id}>
                  {s.short_name} — {s.long_name}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium">Section</span>
            <select
              className="rounded-md border border-[var(--color-line)] bg-white px-3 py-2 text-sm disabled:opacity-50"
              value={sectionId}
              onChange={(e) => setSectionId(e.target.value)}
              disabled={!statuteId || sectionsQuery.isPending}
              data-testid="matter-statute-section-select"
            >
              <option value="">
                {!statuteId
                  ? "Select an Act first"
                  : sectionsQuery.isPending
                    ? "Loading sections…"
                    : "Select a section…"}
              </option>
              {(sectionsQuery.data?.sections ?? []).map((sec) => (
                <option key={sec.id} value={sec.id}>
                  {sec.section_number}
                  {sec.section_label ? ` — ${sec.section_label}` : ""}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium">Relevance</span>
            <select
              className="rounded-md border border-[var(--color-line)] bg-white px-3 py-2 text-sm"
              value={relevance}
              onChange={(e) => setRelevance(e.target.value as Relevance)}
              data-testid="matter-statute-relevance-select"
            >
              <option value="cited">cited (we rely on it)</option>
              <option value="opposing">opposing (other side relies on it)</option>
              <option value="context">context (in scope but not load-bearing)</option>
            </select>
          </label>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button
            onClick={() => addMutation.mutate()}
            disabled={!sectionId || addMutation.isPending}
            data-testid="matter-statute-add-submit"
          >
            {addMutation.isPending ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Adding…
              </>
            ) : (
              "Attach reference"
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
