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
  RefreshCw,
  Trash2,
} from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useId, useState } from "react";
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
import {
  Select,
  SelectContent,
  SelectEmpty,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/Select";
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
      <CardHeader className="flex flex-col items-start justify-between gap-3 space-y-0 sm:flex-row">
        <div className="min-w-0">
          <CardTitle>Statutes referenced</CardTitle>
          <CardDescription>
            Sections this matter relies on or distinguishes. The drafting flow
            injects bare text from these into the appeal-memorandum prompt for
            verbatim quoting.
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
  const fieldId = useId();
  const [open, setOpen] = useState(false);
  const [statuteId, setStatuteId] = useState<string>("");
  const [sectionId, setSectionId] = useState<string>("");
  const [relevance, setRelevance] = useState<Relevance>("cited");
  const queryClient = useQueryClient();
  const setDialogOpen = (nextOpen: boolean) => {
    setOpen(nextOpen);
    if (!nextOpen) {
      setStatuteId("");
      setSectionId("");
      setRelevance("cited");
    }
  };

  const statutesQuery = useQuery({
    queryKey: ["statutes", "list"],
    queryFn: listStatutes,
    enabled: open,
    staleTime: 30 * 60_000,
  });
  const sectionsQuery = useQuery({
    queryKey: ["statutes", statuteId, "sections"],
    queryFn: async ({ signal }) => {
      const result = await listStatuteSections(statuteId);
      // The client has no transport cancellation; do not admit abandoned reads.
      signal.throwIfAborted();
      return result;
    },
    enabled: open && Boolean(statuteId),
    staleTime: 30 * 60_000,
  });
  const selectableStatutes = (statutesQuery.data?.statutes ?? []).filter(
    (statute) => statute.section_count > 0,
  );
  const allStatutes = statutesQuery.data?.statutes ?? [];
  const sectionsReady = sectionsQuery.isSuccess && !sectionsQuery.isFetching;
  const sections = sectionsReady ? sectionsQuery.data.sections : [];
  const selectableSectionIds = new Set(sections.map((section) => section.id));
  const catalogSections = sectionsReady ? sectionsQuery.data.catalog_sections ?? sections : [];
  const canAttach = statutesQuery.isSuccess && !statutesQuery.isFetching
    && selectableStatutes.some((statute) => statute.id === statuteId)
    && selectableSectionIds.has(sectionId);

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
      setDialogOpen(false);
    },
    onError: (e: unknown) =>
      toast.error(
        e instanceof Error ? e.message : "Could not attach the statute.",
      ),
  });

  return (
    <Dialog open={open} onOpenChange={setDialogOpen}>
      <DialogTrigger asChild>
        <Button className="w-full shrink-0 sm:w-auto" data-testid="matter-statute-add-trigger">
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
        <div className="flex min-w-0 flex-col gap-3">
          <div className="flex min-w-0 flex-col gap-1 text-sm">
            <label htmlFor={`${fieldId}-act`} className="font-medium">
              Act
            </label>
            <Select
              value={statuteId}
              onValueChange={(value) => {
                setStatuteId(value);
                setSectionId("");
              }}
              disabled={statutesQuery.isPending || statutesQuery.isError}
            >
              <SelectTrigger
                id={`${fieldId}-act`}
                data-testid="matter-statute-act-select"
              >
                <SelectValue
                  placeholder={statutesQuery.isPending
                    ? "Loading verified Acts…"
                    : statutesQuery.isError
                      ? "Could not load verified Acts"
                      : selectableStatutes.length === 0
                        ? "No verified Acts available"
                        : "Select an Act…"}
                />
              </SelectTrigger>
              <SelectContent aria-label="Act">
                {allStatutes.length === 0 ? (
                  <SelectEmpty>No verified Acts available</SelectEmpty>
                ) : null}
                {allStatutes.map((s) => (
                  <SelectItem
                    key={s.id}
                    value={s.id}
                    data-value={s.id}
                    disabled={s.section_count === 0}
                  >
                    {s.short_name} — {s.long_name} ({s.section_count} verified of{" "}
                    {s.catalog_section_count ?? s.section_count} catalogued
                    {s.section_count === 0 ? "; verification pending" : ""})
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {!statutesQuery.isPending && !statutesQuery.isError ? (
              <span
                className="text-xs text-[var(--color-mute)]"
                data-testid="matter-statute-catalog-coverage"
              >
                {statutesQuery.data?.total_section_count ?? 0} verified of{" "}
                {statutesQuery.data?.total_catalog_section_count ?? 0}{" "}
                catalogued sections across {allStatutes.length} Acts. All Acts
                are shown; entries awaiting complete source verification are
                visible but disabled.
              </span>
            ) : null}
            {statutesQuery.isError ? (
              <span
                className="text-xs text-[var(--color-danger-700)]"
                data-testid="matter-statute-catalog-error"
              >
                The verified statute catalog could not be loaded. Retry by
                reopening this dialog.
              </span>
            ) : !statutesQuery.isPending && selectableStatutes.length === 0 ? (
              <span
                className="text-xs text-[var(--color-warn-700)]"
                data-testid="matter-statute-no-selectable-acts"
              >
                No Acts currently have source-verified sections available to
                attach.
              </span>
            ) : null}
          </div>
          <div className="flex min-w-0 flex-col gap-1 text-sm">
            <label htmlFor={`${fieldId}-section`} className="font-medium">
              Section
            </label>
            <Select
              value={sectionId}
              onValueChange={setSectionId}
              disabled={!statuteId || sectionsQuery.isFetching || sectionsQuery.isError}
            >
              <SelectTrigger
                id={`${fieldId}-section`}
                data-testid="matter-statute-section-select"
              >
                <SelectValue
                  placeholder={!statuteId
                    ? "Select an Act first"
                    : sectionsQuery.isFetching
                      ? "Loading sections…"
                      : sectionsQuery.isError
                        ? "Could not load verified sections"
                        : sections.length === 0
                          ? "No verified sections available"
                          : "Select a section…"}
                />
              </SelectTrigger>
              <SelectContent aria-label="Section">
                {catalogSections.length === 0 ? (
                  <SelectEmpty>
                    {sectionsQuery.isError
                      ? "Could not load verified sections"
                      : "No verified sections available"}
                  </SelectEmpty>
                ) : null}
                {catalogSections.map((sec) => (
                  <SelectItem
                    key={sec.id}
                    value={sec.id}
                    data-value={sec.id}
                    disabled={!selectableSectionIds.has(sec.id)}
                  >
                    {sec.section_number}
                    {sec.section_label ? ` — ${sec.section_label}` : ""}
                    {sec.legal_status === "repealed" && selectableSectionIds.has(sec.id)
                      ? " (historical repealed-law edition)" : ""}
                    {!selectableSectionIds.has(sec.id)
                      ? " — verification pending; not attachable"
                      : ""}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {statuteId && sectionsReady ? (
              <span
                className="text-xs text-[var(--color-mute)]"
                data-testid="matter-statute-section-coverage"
              >
                {sectionsQuery.data?.verified_section_count ?? sections.length}{" "}
                verified of{" "}
                {sectionsQuery.data?.catalog_section_count ??
                  catalogSections.length}{" "}
                catalogued sections. Unverified provisions cannot be attached
                through the UI or API.
              </span>
            ) : null}
            {sectionsQuery.isError ? (
              <div className="flex min-w-0 flex-col items-start gap-2">
                <span
                  role="alert"
                  className="text-xs text-[var(--color-danger-700)]"
                  data-testid="matter-statute-sections-error"
                >
                  Verified sections could not be loaded for this Act. Use Retry
                  sections to try again.
                </span>
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={sectionsQuery.isFetching}
                  onClick={() => {
                    setSectionId("");
                    void sectionsQuery.refetch({ cancelRefetch: false });
                  }}
                >
                  <RefreshCw className="h-4 w-4" aria-hidden /> Retry sections
                </Button>
              </div>
            ) : null}
          </div>
          <div className="flex min-w-0 flex-col gap-1 text-sm">
            <label htmlFor={`${fieldId}-relevance`} className="font-medium">
              Relevance
            </label>
            <Select
              value={relevance}
              onValueChange={(value) => setRelevance(value as Relevance)}
            >
              <SelectTrigger
                id={`${fieldId}-relevance`}
                data-testid="matter-statute-relevance-select"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent aria-label="Relevance">
                <SelectItem value="cited">cited (we rely on it)</SelectItem>
                <SelectItem value="opposing">
                  opposing (other side relies on it)
                </SelectItem>
                <SelectItem value="context">
                  context (in scope but not load-bearing)
                </SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => setDialogOpen(false)}>
            Cancel
          </Button>
          <Button
            onClick={() => addMutation.mutate()}
            disabled={!canAttach || addMutation.isPending}
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
