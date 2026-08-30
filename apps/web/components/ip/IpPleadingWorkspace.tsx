"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Ban,
  CheckCircle2,
  Download,
  FileSignature,
  FileUp,
  GitCompareArrows,
  LockKeyhole,
  MailCheck,
  PackageCheck,
  Plus,
  RotateCcw,
  Save,
  Send,
  WandSparkles,
} from "lucide-react";
import { useEffect, useId, useMemo, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { Textarea } from "@/components/ui/Textarea";
import { apiErrorMessage } from "@/lib/api/config";
import {
  createIpPleadingDraft,
  compareIpPleadingDraftRevisions,
  downloadIpPleadingDraft,
  downloadIpPleadingFilingBundle,
  generateIpPleadingDraft,
  getIpPleadingDraft,
  listIpPleadingDrafts,
  listIpPleadingTemplates,
  saveIpPleadingDraft,
  transitionIpPleadingLifecycle,
  transitionIpPleadingDraft,
  validateIpPleadingDraft,
} from "@/lib/api/endpoints";
import type { Draft } from "@/lib/api/schemas";

const SELECT_CLASS =
  "h-10 w-full min-w-0 rounded-md border border-[var(--color-line)] bg-white px-3 text-sm";

function statusTone(status: Draft["status"]): "neutral" | "brand" | "success" | "warning" {
  if (["approved", "finalized", "filed", "served"].includes(status)) return "success";
  if (status === "in_review") return "brand";
  if (status === "changes_requested" || status === "filing_rejected") return "warning";
  return "neutral";
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export function IpPleadingWorkspace({
  docketId,
  proceedingId,
  canCreate,
  canEdit,
  canGenerate,
  canReview,
  canFinalize,
  initialDraftId = null,
}: {
  docketId: string;
  proceedingId: string;
  canCreate: boolean;
  canEdit: boolean;
  canGenerate: boolean;
  canReview: boolean;
  canFinalize: boolean;
  initialDraftId?: string | null;
}) {
  const queryClient = useQueryClient();
  const controlId = useId();
  const queryKey = ["ip", "pleading-drafts", docketId, proceedingId] as const;
  const requestedDraft = useQuery({
    queryKey: [...queryKey, "detail", initialDraftId],
    queryFn: () => getIpPleadingDraft({
      docketId,
      proceedingId,
      draftId: initialDraftId!,
    }),
    enabled: Boolean(initialDraftId),
    retry: false,
  });
  const supportingQueriesEnabled = !initialDraftId || requestedDraft.isFetched;
  const templates = useQuery({
    queryKey: ["ip", "pleading-templates", docketId, proceedingId],
    queryFn: () => listIpPleadingTemplates({ docketId, proceedingId }),
    enabled: supportingQueriesEnabled,
  });
  const drafts = useQuery({
    queryKey,
    queryFn: () => listIpPleadingDrafts({ docketId, proceedingId }),
    enabled: supportingQueriesEnabled,
  });
  const [templateKey, setTemplateKey] = useState("");
  const [title, setTitle] = useState("");
  const [selectedId, setSelectedId] = useState(initialDraftId ?? "");
  const [focusNote, setFocusNote] = useState("");
  const [reviewNotes, setReviewNotes] = useState("");
  const [lifecycleReference, setLifecycleReference] = useState("");
  const [serviceMethod, setServiceMethod] = useState("");
  const [body, setBody] = useState("");

  useEffect(() => {
    if (!templateKey && templates.data?.templates[0]) {
      setTemplateKey(templates.data.templates[0].key);
      setTitle(templates.data.templates[0].label);
    }
  }, [templateKey, templates.data?.templates]);
  const draftRows = useMemo(() => {
    const rows = drafts.data?.drafts ?? [];
    if (requestedDraft.data && !rows.some((row) => row.id === requestedDraft.data.id)) {
      return [requestedDraft.data, ...rows];
    }
    return rows;
  }, [drafts.data?.drafts, requestedDraft.data]);
  useEffect(() => {
    if (!drafts.data && !requestedDraft.data) return;
    const rows = draftRows;
    if (!selectedId && rows[0]) setSelectedId(rows[0].id);
    if (selectedId && !rows.some((row) => row.id === selectedId)) {
      setSelectedId(rows[0]?.id ?? "");
    }
  }, [draftRows, drafts.data, requestedDraft.data, selectedId]);
  const selected = useMemo(
    () => draftRows.find((row) => row.id === selectedId) ?? null,
    [draftRows, selectedId],
  );
  const currentVersion = useMemo(
    () => selected?.versions.find((row) => row.id === selected.current_version_id) ?? null,
    [selected],
  );
  const previousVersion = selected && selected.versions.length > 1
    ? selected.versions[selected.versions.length - 2]
    : null;
  const validation = useQuery({
    queryKey: ["ip", "pleading-validation", docketId, proceedingId, selectedId, currentVersion?.id],
    queryFn: () => validateIpPleadingDraft({ docketId, proceedingId, draftId: selectedId }),
    enabled: Boolean(selectedId && currentVersion),
  });
  const comparison = useQuery({
    queryKey: ["ip", "pleading-comparison", docketId, proceedingId, selectedId, previousVersion?.id, currentVersion?.id],
    queryFn: () => compareIpPleadingDraftRevisions({
      docketId,
      proceedingId,
      draftId: selectedId,
      prevRevision: previousVersion!.revision,
      nextRevision: currentVersion!.revision,
    }),
    enabled: Boolean(selectedId && previousVersion && currentVersion),
  });
  useEffect(() => setBody(currentVersion?.body ?? ""), [currentVersion?.id, currentVersion?.body]);

  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey }),
      queryClient.invalidateQueries({ queryKey: ["ip", "pleading-validation", docketId, proceedingId] }),
      queryClient.invalidateQueries({ queryKey: ["ip", "pleading-comparison", docketId, proceedingId] }),
    ]);
  };
  const create = useMutation({
    mutationFn: createIpPleadingDraft,
    onSuccess: async (row) => {
      setSelectedId(row.id);
      toast.success("Pleading draft created.");
      await refresh();
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not create the pleading.")),
  });
  const generate = useMutation({
    mutationFn: generateIpPleadingDraft,
    onSuccess: async () => {
      toast.success("Grounded pleading revision generated.");
      await refresh();
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not generate the pleading.")),
  });
  const save = useMutation({
    mutationFn: saveIpPleadingDraft,
    onSuccess: async () => {
      toast.success("Lawyer edit saved as a new revision.");
      await refresh();
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not save the revision.")),
  });
  const transition = useMutation({
    mutationFn: transitionIpPleadingDraft,
    onSuccess: async () => {
      toast.success("Pleading review state updated.");
      setReviewNotes("");
      await refresh();
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not update review state.")),
  });
  const download = useMutation({
    mutationFn: downloadIpPleadingDraft,
    onSuccess: (blob) => downloadBlob(blob, `${selected?.title ?? "trademark-pleading"}.docx`),
    onError: (error) => toast.error(apiErrorMessage(error, "Could not export the pleading.")),
  });
  const bundle = useMutation({
    mutationFn: downloadIpPleadingFilingBundle,
    onSuccess: (blob) => downloadBlob(blob, `${selected?.title ?? "trademark-pleading"}-filing-bundle.zip`),
    onError: (error) => toast.error(apiErrorMessage(error, "Could not create the filing bundle.")),
  });
  const lifecycle = useMutation({
    mutationFn: transitionIpPleadingLifecycle,
    onSuccess: async () => {
      toast.success("Pleading lifecycle event recorded.");
      setLifecycleReference("");
      setServiceMethod("");
      await refresh();
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not record the lifecycle event.")),
  });
  const busy = create.isPending || generate.isPending || save.isPending || transition.isPending || lifecycle.isPending;
  const sourceRows = currentVersion?.source_manifest ?? [];
  const immutableStatus = selected ? ["finalized", "filed", "served"].includes(selected.status) : false;
  const workspacePending = !selected && (
    requestedDraft.isPending || templates.isPending || drafts.isPending
  );

  return (
    <section
      aria-busy={workspacePending}
      className="min-w-0 space-y-4 border-t border-[var(--color-line)] pt-4"
      data-testid="ip-pleading-workspace"
    >
      <div className="flex min-w-0 flex-wrap items-center justify-between gap-3">
        <h4 className="flex items-center gap-2 font-semibold">
          <FileSignature className="h-4 w-4" /> Trademark pleadings
        </h4>
        {selected ? <Badge tone={statusTone(selected.status)}>{selected.status.replaceAll("_", " ")}</Badge> : null}
      </div>

      {templates.isError ? <QueryErrorState error={templates.error} title="Could not load pleading templates" onRetry={() => templates.refetch()} /> : null}
      {drafts.isError ? <QueryErrorState error={drafts.error} title="Could not load pleading drafts" onRetry={() => drafts.refetch()} /> : null}
      {requestedDraft.isError && !draftRows.some((row) => row.id === initialDraftId) && drafts.isFetched ? (
        <QueryErrorState error={requestedDraft.error} title="Could not load the linked pleading draft" onRetry={() => requestedDraft.refetch()} />
      ) : null}
      {workspacePending ? (
        <div aria-label="Loading pleading workspace" role="status">
          <Skeleton className="h-32 w-full" />
        </div>
      ) : null}

      {templates.data && templates.data.templates.length === 0 ? (
        <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm">
          No pleading template matches the represented side and current opposition stage.
        </div>
      ) : null}

      {templates.data?.templates.length ? (
        <form
          className="grid min-w-0 gap-3 md:grid-cols-[minmax(180px,0.8fr)_minmax(220px,1.2fr)_auto]"
          onSubmit={(event) => {
            event.preventDefault();
            create.mutate({ docketId, proceedingId, title, templateKey });
          }}
        >
          <Label className="min-w-0 space-y-1.5" htmlFor={`${controlId}-template`}>
            <span className="block">Template</span>
            <select id={`${controlId}-template`} className={SELECT_CLASS} value={templateKey} onChange={(event) => {
              const key = event.target.value;
              setTemplateKey(key);
              setTitle(templates.data.templates.find((row) => row.key === key)?.label ?? "");
            }}>
              {templates.data.templates.map((row) => <option key={row.key} value={row.key}>{row.label} v{row.version}</option>)}
            </select>
          </Label>
          <Label className="min-w-0 space-y-1.5" htmlFor={`${controlId}-title`}>
            <span className="block">Draft title</span>
            <Input id={`${controlId}-title`} value={title} onChange={(event) => setTitle(event.target.value)} />
          </Label>
          <div className="flex items-end">
            <Button className="w-full" type="submit" disabled={!canCreate || title.trim().length < 3 || create.isPending}>
              <Plus className="h-4 w-4" /> Create
            </Button>
          </div>
        </form>
      ) : null}

      {draftRows.length ? (
        <Label className="block min-w-0 space-y-1.5" htmlFor={`${controlId}-draft`}>
          <span className="block">Pleading draft</span>
          <select aria-label="Pleading draft" id={`${controlId}-draft`} className={SELECT_CLASS} value={selectedId} onChange={(event) => setSelectedId(event.target.value)}>
            {draftRows.map((row) => <option key={row.id} value={row.id}>{row.title} - {row.status.replaceAll("_", " ")}</option>)}
          </select>
        </Label>
      ) : null}

      {selected ? (
        <div className="min-w-0 space-y-3">
          <Label className="block min-w-0 space-y-1.5" htmlFor={`${controlId}-focus`}>
            <span className="block">Generation focus</span>
            <Textarea id={`${controlId}-focus`} value={focusNote} onChange={(event) => setFocusNote(event.target.value)} placeholder="Issues or reliefs to emphasize" />
          </Label>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" type="button" onClick={() => generate.mutate({ docketId, proceedingId, draftId: selected.id, focusNote })} disabled={!canGenerate || immutableStatus || generate.isPending}>
              <WandSparkles className="h-4 w-4" /> Generate revision
            </Button>
            {currentVersion ? <Button size="sm" type="button" variant="outline" onClick={() => download.mutate({ docketId, proceedingId, draftId: selected.id })} disabled={download.isPending}><Download className="h-4 w-4" /> DOCX</Button> : null}
            {currentVersion && ["finalized", "filed", "filing_rejected", "served"].includes(selected.status) ? <Button size="sm" type="button" variant="outline" onClick={() => bundle.mutate({ docketId, proceedingId, draftId: selected.id })} disabled={bundle.isPending || validation.data?.can_file === false}><PackageCheck className="h-4 w-4" /> Filing bundle</Button> : null}
          </div>

          {currentVersion ? (
            <>
              <div className="flex min-w-0 flex-wrap gap-2 text-xs text-[var(--color-mute)]">
                <span>Revision {currentVersion.revision}</span>
                <span>{currentVersion.verified_citation_count} verified citation{currentVersion.verified_citation_count === 1 ? "" : "s"}</span>
                <span>{sourceRows.length} frozen source version{sourceRows.length === 1 ? "" : "s"}</span>
              </div>
              <Label className="block min-w-0 space-y-1.5" htmlFor={`${controlId}-body`}>
                <span className="block">Pleading body</span>
                <Textarea aria-label="Pleading body" id={`${controlId}-body`} className="min-h-80 font-mono" value={body} onChange={(event) => setBody(event.target.value)} disabled={!canEdit || immutableStatus} />
              </Label>
              <div className="flex flex-wrap gap-2">
                <Button size="sm" type="button" onClick={() => save.mutate({ docketId, proceedingId, draftId: selected.id, body })} disabled={!canEdit || immutableStatus || body.trim() === currentVersion.body.trim() || save.isPending}><Save className="h-4 w-4" /> Save revision</Button>
              </div>
              {validation.isError ? <QueryErrorState error={validation.error} title="Could not validate this revision" onRetry={() => validation.refetch()} /> : null}
              {validation.data ? (
                <div className={`border-l-4 p-3 text-sm ${validation.data.blocker_count ? "border-red-500 bg-red-50" : validation.data.warning_count ? "border-amber-500 bg-amber-50" : "border-emerald-500 bg-emerald-50"}`} data-testid="ip-draft-validation">
                  <div className="flex flex-wrap items-center gap-2 font-semibold">
                    {validation.data.blocker_count ? <AlertTriangle className="h-4 w-4" /> : <CheckCircle2 className="h-4 w-4" />}
                    {validation.data.blocker_count} blockers, {validation.data.warning_count} warnings
                  </div>
                  {validation.data.findings.length ? <ul className="mt-2 space-y-1">{validation.data.findings.map((finding) => <li key={`${finding.code}-${finding.message}`}>{finding.message}</li>)}</ul> : <p className="mt-1">Current identifiers, sources, citations, exhibits, and placeholders passed.</p>}
                </div>
              ) : null}
              {comparison.data ? (
                <details className="border-t border-[var(--color-line)] pt-3 text-sm" data-testid="ip-draft-comparison">
                  <summary className="flex cursor-pointer items-center gap-2 font-semibold"><GitCompareArrows className="h-4 w-4" /> {comparison.data.summary}</summary>
                  <div className="mt-2 grid gap-2 sm:grid-cols-2"><span>Added: {comparison.data.lines_added} lines, {comparison.data.citations_added.length} citations</span><span>Removed: {comparison.data.lines_removed} lines, {comparison.data.citations_removed.length} citations</span></div>
                </details>
              ) : null}
              <Label className="block min-w-0 space-y-1.5" htmlFor={`${controlId}-review-notes`}>
                <span className="block">Review notes</span>
                <Input id={`${controlId}-review-notes`} value={reviewNotes} onChange={(event) => setReviewNotes(event.target.value)} />
              </Label>
              <div className="flex flex-wrap gap-2">
                {(selected.status === "draft" || selected.status === "changes_requested") ? <Button size="sm" type="button" variant="outline" disabled={!canEdit || busy} onClick={() => transition.mutate({ docketId, proceedingId, draftId: selected.id, action: "submit", notes: reviewNotes })}><Send className="h-4 w-4" /> Submit</Button> : null}
                {selected.status === "in_review" ? <Button size="sm" type="button" variant="outline" disabled={!canReview || busy} onClick={() => transition.mutate({ docketId, proceedingId, draftId: selected.id, action: "request-changes", notes: reviewNotes })}><RotateCcw className="h-4 w-4" /> Request changes</Button> : null}
                {selected.status === "in_review" ? <Button size="sm" type="button" disabled={!canReview || currentVersion.verified_citation_count < 1 || validation.data?.can_approve === false || busy} onClick={() => transition.mutate({ docketId, proceedingId, draftId: selected.id, action: "approve", notes: reviewNotes })}><CheckCircle2 className="h-4 w-4" /> Approve</Button> : null}
                {selected.status === "approved" ? <Button size="sm" type="button" disabled={!canFinalize || busy} onClick={() => transition.mutate({ docketId, proceedingId, draftId: selected.id, action: "finalize", notes: reviewNotes })}><LockKeyhole className="h-4 w-4" /> Finalize</Button> : null}
              </div>
              {["finalized", "filed"].includes(selected.status) ? (
                <div className="grid gap-3 border-t border-[var(--color-line)] pt-3 md:grid-cols-[minmax(180px,1fr)_minmax(180px,1fr)_auto]">
                  <Label className="space-y-1.5" htmlFor={`${controlId}-registry-reference`}><span className="block">Registry reference</span><Input id={`${controlId}-registry-reference`} value={lifecycleReference} onChange={(event) => setLifecycleReference(event.target.value)} /></Label>
                  <Label className="space-y-1.5" htmlFor={`${controlId}-service-method`}><span className="block">Service method</span><Input id={`${controlId}-service-method`} value={serviceMethod} onChange={(event) => setServiceMethod(event.target.value)} disabled={selected.status !== "filed"} /></Label>
                  <div className="flex flex-wrap items-end gap-2">
                    {selected.status === "finalized" ? <Button size="sm" type="button" disabled={!canFinalize || !lifecycleReference.trim() || validation.data?.can_file === false || busy} onClick={() => lifecycle.mutate({ docketId, proceedingId, draftId: selected.id, action: "file", reference: lifecycleReference, notes: reviewNotes })}><FileUp className="h-4 w-4" /> Mark filed</Button> : null}
                    {selected.status === "filed" ? <Button size="sm" type="button" variant="outline" disabled={!canFinalize || !lifecycleReference.trim() || busy} onClick={() => lifecycle.mutate({ docketId, proceedingId, draftId: selected.id, action: "reject-filing", reference: lifecycleReference, notes: reviewNotes })}><Ban className="h-4 w-4" /> Rejected</Button> : null}
                    {selected.status === "filed" ? <Button size="sm" type="button" disabled={!canFinalize || !lifecycleReference.trim() || !serviceMethod.trim() || busy} onClick={() => lifecycle.mutate({ docketId, proceedingId, draftId: selected.id, action: "serve", reference: lifecycleReference, method: serviceMethod, notes: reviewNotes })}><MailCheck className="h-4 w-4" /> Mark served</Button> : null}
                  </div>
                </div>
              ) : null}
              {selected.reviews.length ? (
                <details className="border-t border-[var(--color-line)] pt-3 text-sm">
                  <summary className="cursor-pointer font-semibold">Review and filing history</summary>
                  <ol className="mt-2 space-y-2">{selected.reviews.map((event) => <li key={event.id}><strong>{event.action.replaceAll("_", " ")}</strong> on revision {selected.versions.find((row) => row.id === event.version_id)?.revision ?? "-"}{typeof event.metadata.reference === "string" ? ` - ${event.metadata.reference}` : ""}</li>)}</ol>
                </details>
              ) : null}
              {sourceRows.length ? (
                <details className="rounded-md border border-[var(--color-line)] p-3 text-sm">
                  <summary className="cursor-pointer font-semibold">Frozen document versions</summary>
                  <ul className="mt-2 space-y-2">
                    {sourceRows.map((row, index) => <li className="min-w-0 break-words" key={String(row.document_version_id ?? index)}><strong>{String(row.display_name ?? row.document_title ?? "Document")}</strong><div className="font-mono text-xs text-[var(--color-mute)]">{String(row.sha256 ?? "Hash unavailable")}</div></li>)}
                  </ul>
                </details>
              ) : null}
            </>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
