"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2,
  Download,
  FileSignature,
  LockKeyhole,
  Plus,
  RotateCcw,
  Save,
  Send,
  WandSparkles,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
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
  downloadIpPleadingDraft,
  generateIpPleadingDraft,
  listIpPleadingDrafts,
  listIpPleadingTemplates,
  saveIpPleadingDraft,
  transitionIpPleadingDraft,
} from "@/lib/api/endpoints";
import type { Draft } from "@/lib/api/schemas";

const SELECT_CLASS =
  "h-10 w-full min-w-0 rounded-md border border-[var(--color-line)] bg-white px-3 text-sm";

function statusTone(status: Draft["status"]): "neutral" | "brand" | "success" | "warning" {
  if (status === "approved" || status === "finalized") return "success";
  if (status === "in_review") return "brand";
  if (status === "changes_requested") return "warning";
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
}: {
  docketId: string;
  proceedingId: string;
  canCreate: boolean;
  canEdit: boolean;
  canGenerate: boolean;
  canReview: boolean;
  canFinalize: boolean;
}) {
  const queryClient = useQueryClient();
  const queryKey = ["ip", "pleading-drafts", docketId, proceedingId] as const;
  const templates = useQuery({
    queryKey: ["ip", "pleading-templates", docketId, proceedingId],
    queryFn: () => listIpPleadingTemplates({ docketId, proceedingId }),
  });
  const drafts = useQuery({
    queryKey,
    queryFn: () => listIpPleadingDrafts({ docketId, proceedingId }),
  });
  const [templateKey, setTemplateKey] = useState("");
  const [title, setTitle] = useState("");
  const [selectedId, setSelectedId] = useState("");
  const [focusNote, setFocusNote] = useState("");
  const [reviewNotes, setReviewNotes] = useState("");
  const [body, setBody] = useState("");

  useEffect(() => {
    if (!templateKey && templates.data?.templates[0]) {
      setTemplateKey(templates.data.templates[0].key);
      setTitle(templates.data.templates[0].label);
    }
  }, [templateKey, templates.data?.templates]);
  useEffect(() => {
    const rows = drafts.data?.drafts ?? [];
    if (!selectedId && rows[0]) setSelectedId(rows[0].id);
    if (selectedId && !rows.some((row) => row.id === selectedId)) {
      setSelectedId(rows[0]?.id ?? "");
    }
  }, [drafts.data?.drafts, selectedId]);
  const selected = useMemo(
    () => drafts.data?.drafts.find((row) => row.id === selectedId) ?? null,
    [drafts.data?.drafts, selectedId],
  );
  const currentVersion = useMemo(
    () => selected?.versions.find((row) => row.id === selected.current_version_id) ?? null,
    [selected],
  );
  useEffect(() => setBody(currentVersion?.body ?? ""), [currentVersion?.id, currentVersion?.body]);

  const refresh = async () => queryClient.invalidateQueries({ queryKey });
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
  const busy = create.isPending || generate.isPending || save.isPending || transition.isPending;
  const sourceRows = currentVersion?.source_manifest ?? [];

  return (
    <section className="min-w-0 space-y-4 border-t border-[var(--color-line)] pt-4" data-testid="ip-pleading-workspace">
      <div className="flex min-w-0 flex-wrap items-center justify-between gap-3">
        <h4 className="flex items-center gap-2 font-semibold">
          <FileSignature className="h-4 w-4" /> Trademark pleadings
        </h4>
        {selected ? <Badge tone={statusTone(selected.status)}>{selected.status.replaceAll("_", " ")}</Badge> : null}
      </div>

      {templates.isError ? <QueryErrorState error={templates.error} title="Could not load pleading templates" onRetry={() => templates.refetch()} /> : null}
      {drafts.isError ? <QueryErrorState error={drafts.error} title="Could not load pleading drafts" onRetry={() => drafts.refetch()} /> : null}
      {templates.isPending || drafts.isPending ? <Skeleton className="h-32 w-full" /> : null}

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
          <Label className="min-w-0 space-y-1.5">
            <span className="block">Template</span>
            <select className={SELECT_CLASS} value={templateKey} onChange={(event) => {
              const key = event.target.value;
              setTemplateKey(key);
              setTitle(templates.data.templates.find((row) => row.key === key)?.label ?? "");
            }}>
              {templates.data.templates.map((row) => <option key={row.key} value={row.key}>{row.label} v{row.version}</option>)}
            </select>
          </Label>
          <Label className="min-w-0 space-y-1.5">
            <span className="block">Draft title</span>
            <Input value={title} onChange={(event) => setTitle(event.target.value)} />
          </Label>
          <div className="flex items-end">
            <Button className="w-full" type="submit" disabled={!canCreate || title.trim().length < 3 || create.isPending}>
              <Plus className="h-4 w-4" /> Create
            </Button>
          </div>
        </form>
      ) : null}

      {drafts.data?.drafts.length ? (
        <Label className="block min-w-0 space-y-1.5">
          <span className="block">Pleading draft</span>
          <select className={SELECT_CLASS} value={selectedId} onChange={(event) => setSelectedId(event.target.value)}>
            {drafts.data.drafts.map((row) => <option key={row.id} value={row.id}>{row.title} - {row.status.replaceAll("_", " ")}</option>)}
          </select>
        </Label>
      ) : null}

      {selected ? (
        <div className="min-w-0 space-y-3">
          <Label className="block min-w-0 space-y-1.5">
            <span className="block">Generation focus</span>
            <Textarea value={focusNote} onChange={(event) => setFocusNote(event.target.value)} placeholder="Issues or reliefs to emphasize" />
          </Label>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" type="button" onClick={() => generate.mutate({ docketId, proceedingId, draftId: selected.id, focusNote })} disabled={!canGenerate || selected.status === "finalized" || generate.isPending}>
              <WandSparkles className="h-4 w-4" /> Generate revision
            </Button>
            {currentVersion ? <Button size="sm" type="button" variant="outline" onClick={() => download.mutate({ docketId, proceedingId, draftId: selected.id })} disabled={download.isPending}><Download className="h-4 w-4" /> DOCX</Button> : null}
          </div>

          {currentVersion ? (
            <>
              <div className="flex min-w-0 flex-wrap gap-2 text-xs text-[var(--color-mute)]">
                <span>Revision {currentVersion.revision}</span>
                <span>{currentVersion.verified_citation_count} verified citation{currentVersion.verified_citation_count === 1 ? "" : "s"}</span>
                <span>{sourceRows.length} frozen source version{sourceRows.length === 1 ? "" : "s"}</span>
              </div>
              <Label className="block min-w-0 space-y-1.5">
                <span className="block">Pleading body</span>
                <Textarea className="min-h-80 font-mono" value={body} onChange={(event) => setBody(event.target.value)} disabled={!canEdit || selected.status === "finalized"} />
              </Label>
              <div className="flex flex-wrap gap-2">
                <Button size="sm" type="button" onClick={() => save.mutate({ docketId, proceedingId, draftId: selected.id, body })} disabled={!canEdit || selected.status === "finalized" || body.trim() === currentVersion.body.trim() || save.isPending}><Save className="h-4 w-4" /> Save revision</Button>
              </div>
              <Label className="block min-w-0 space-y-1.5">
                <span className="block">Review notes</span>
                <Input value={reviewNotes} onChange={(event) => setReviewNotes(event.target.value)} />
              </Label>
              <div className="flex flex-wrap gap-2">
                {(selected.status === "draft" || selected.status === "changes_requested") ? <Button size="sm" type="button" variant="outline" disabled={!canEdit || busy} onClick={() => transition.mutate({ docketId, proceedingId, draftId: selected.id, action: "submit", notes: reviewNotes })}><Send className="h-4 w-4" /> Submit</Button> : null}
                {selected.status === "in_review" ? <Button size="sm" type="button" variant="outline" disabled={!canReview || busy} onClick={() => transition.mutate({ docketId, proceedingId, draftId: selected.id, action: "request-changes", notes: reviewNotes })}><RotateCcw className="h-4 w-4" /> Request changes</Button> : null}
                {selected.status === "in_review" ? <Button size="sm" type="button" disabled={!canReview || currentVersion.verified_citation_count < 1 || busy} onClick={() => transition.mutate({ docketId, proceedingId, draftId: selected.id, action: "approve", notes: reviewNotes })}><CheckCircle2 className="h-4 w-4" /> Approve</Button> : null}
                {selected.status === "approved" ? <Button size="sm" type="button" disabled={!canFinalize || busy} onClick={() => transition.mutate({ docketId, proceedingId, draftId: selected.id, action: "finalize", notes: reviewNotes })}><LockKeyhole className="h-4 w-4" /> Finalize</Button> : null}
              </div>
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
