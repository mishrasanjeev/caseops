"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { LoaderCircle, Upload } from "lucide-react";
import Link from "next/link";
import { useId, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { apiErrorMessage } from "@/lib/api/config";
import {
  addIpDocumentLinks,
  fetchIpDocument,
  fetchIpDocumentTaxonomy,
  seedIpDocumentTaxonomy,
  uploadIpDocument,
  type IpDocket,
  type IpDocument,
} from "@/lib/api/endpoints";
import { useCapability } from "@/lib/capabilities";

const SELECT_CLASS =
  "h-10 w-full min-w-0 rounded-md border border-[var(--color-line)] bg-white px-3 text-sm disabled:cursor-not-allowed disabled:opacity-60";

type Confidentiality = "internal" | "confidential" | "restricted";

function formatList(items: string[]) {
  return items.length <= 1 ? items.join("") : `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

/**
 * Files an executed instrument (deed, licence, certificate) on one docket from
 * inside a recordal form, so a docket without an instrument is never a dead
 * end (BUG-008). It renders no <form> of its own because it sits inside one.
 *
 * Classifications are the tenant's active document taxonomy, the list the
 * upload API validates against; nothing hidden is ever sent. When the
 * taxonomy is missing, the role cannot upload, or the list cannot load, the
 * panel says which of those it is and offers the action that fixes it.
 */
export function RecordalInstrumentUpload({
  docket,
  suggestedTaxonomyKey,
  onUploaded,
}: {
  docket: Pick<IpDocket, "id" | "title" | "primary_identifier">;
  /** Pre-selects this classification when the tenant has it active. */
  suggestedTaxonomyKey?: string;
  onUploaded?: (document: IpDocument) => void | Promise<void>;
}) {
  const base = `recordal-instrument-${useId().replace(/:/g, "")}`;
  const canWrite = useCapability("ip:write");
  const canUploadDocuments = useCapability("documents:upload");
  const canConfigure = useCapability("ip:taxonomy_admin");
  const canUpload = canWrite && canUploadDocuments;
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [fileInputKey, setFileInputKey] = useState(0);
  const [title, setTitle] = useState("");
  const [taxonomyKey, setTaxonomyKey] = useState("");
  const [confidentiality, setConfidentiality] = useState<Confidentiality>("internal");
  const [duplicate, setDuplicate] = useState<{ documentId: string; displayName: string } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const taxonomy = useQuery({
    queryKey: ["ip", "document-taxonomy"],
    queryFn: fetchIpDocumentTaxonomy,
    enabled: canUpload,
  });
  const active = taxonomy.data?.entries.filter((entry) => entry.is_active) ?? [];
  const activeKeys = new Set(active.map((entry) => entry.key));
  const chosenKey = activeKeys.has(taxonomyKey)
    ? taxonomyKey
    : !taxonomyKey && suggestedTaxonomyKey && activeKeys.has(suggestedTaxonomyKey)
      ? suggestedTaxonomyKey
      : "";
  const missing = [
    !file ? "the executed file" : null,
    title.trim().length < 3 ? "a title of at least 3 characters" : null,
    !chosenKey ? "a classification" : null,
  ].filter((value): value is string => value !== null);

  async function finish(document: IpDocument, message: string) {
    setFile(null);
    setFileInputKey((value) => value + 1);
    setTitle("");
    setDuplicate(null);
    setError(null);
    toast.success(message);
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["ip", "recordals", "instruments", docket.id] }),
      queryClient.invalidateQueries({ queryKey: ["ip", "documents"] }),
    ]);
    await onUploaded?.(document);
  }

  const upload = useMutation({
    mutationFn: () => {
      if (!file || !chosenKey || title.trim().length < 3) {
        throw new Error(`Add ${formatList(missing)} before uploading.`);
      }
      return uploadIpDocument({
        file,
        taxonomyKey: chosenKey,
        title: title.trim(),
        confidentiality,
        isPrivileged: false,
        clientCode: "",
        mark: "",
        jurisdiction: "",
        applicationNo: docket.primary_identifier ?? "",
        proceedingType: "",
        proceedingNo: "",
        documentDate: "",
        docketId: docket.id,
      });
    },
    onMutate: () => setError(null),
    onSuccess: async (result) => {
      if (result.outcome === "duplicate_found" || !result.document) {
        const candidate = result.duplicate_candidates[0];
        setDuplicate(candidate ? { documentId: candidate.document_id, displayName: candidate.display_name } : null);
        if (!candidate) setError("This file is already stored, but its record is not available to you.");
        return;
      }
      await finish(result.document, `Instrument filed on ${docket.title}. Choose it for each party.`);
    },
    onError: (failure) => setError(apiErrorMessage(failure, "The instrument could not be uploaded.")),
  });
  const reuse = useMutation({
    mutationFn: async () => {
      if (!duplicate) throw new Error("Upload the instrument again.");
      const existing = await fetchIpDocument(duplicate.documentId);
      return addIpDocumentLinks({
        documentId: existing.id,
        expectedCurrentVersion: existing.current_version,
        docketId: docket.id,
      });
    },
    onMutate: () => setError(null),
    onSuccess: (document) =>
      finish(document, `The stored copy is now linked to ${docket.title}. Choose it for each party.`),
    onError: (failure) =>
      setError(apiErrorMessage(failure, "The stored copy could not be linked to this docket.")),
  });
  const seed = useMutation({
    mutationFn: seedIpDocumentTaxonomy,
    onSuccess: async (result) => {
      queryClient.setQueryData(["ip", "document-taxonomy"], result);
      toast.success("Standard document classifications loaded.");
      await queryClient.invalidateQueries({ queryKey: ["ip", "readiness"] });
    },
    onError: (failure) =>
      setError(apiErrorMessage(failure, "Standard classifications could not be loaded.")),
  });

  const statusId = `${base}-status`;
  if (!canUpload) {
    return (
      <p id={statusId} className="text-sm text-[var(--color-mute)]" data-testid="recordal-instrument-upload">
        Your role cannot upload documents. Ask a colleague with document upload access to file the executed
        instrument on this docket; it then appears here for every party.
      </p>
    );
  }
  if (taxonomy.isPending) {
    return (
      <p id={statusId} role="status" className="text-sm text-[var(--color-mute)]" data-testid="recordal-instrument-upload">
        Loading document classifications…
      </p>
    );
  }
  if (taxonomy.isError) {
    return (
      <div data-testid="recordal-instrument-upload">
        <QueryErrorState error={taxonomy.error} title="Could not load document classifications" onRetry={() => taxonomy.refetch()} />
      </div>
    );
  }
  if (!active.length) {
    const none = !taxonomy.data?.entries.length;
    return (
      <div id={statusId} role="status" className="flex min-w-0 flex-col gap-2 rounded-md border border-[var(--color-warn-border)] bg-[var(--color-warn-bg)] p-3 text-sm text-[var(--color-warn-text)]" data-testid="recordal-instrument-upload">
        <p>
          {none
            ? "Uploads need a document classification, and none is configured for this workspace."
            : "Uploads need a document classification, and every classification in this workspace is inactive."}
        </p>
        {none && canConfigure ? (
          <Button type="button" size="sm" variant="outline" className="w-full sm:w-fit" disabled={seed.isPending} onClick={() => seed.mutate()}>
            {seed.isPending ? "Loading…" : "Load standard classifications"}
          </Button>
        ) : canConfigure ? (
          <Link className="font-semibold underline" href="/app/ip">Reactivate a classification in IP documents</Link>
        ) : (
          <p>Ask an IP workspace admin to load the standard document classifications.</p>
        )}
        {error ? <p role="alert" className="text-[var(--color-danger-text)]">{error}</p> : null}
      </div>
    );
  }

  const requirementsId = `${base}-requirements`;
  const errorId = `${base}-error`;
  return (
    <div className="flex min-w-0 flex-col gap-3 rounded-md border border-[var(--color-line)] p-3" data-testid="recordal-instrument-upload">
      <p className="text-sm font-medium">Upload the executed instrument to {docket.title}</p>
      <div className="grid min-w-0 gap-3 md:grid-cols-2">
        <div className="flex min-w-0 flex-col gap-1.5">
          <Label htmlFor={`${base}-file`}>Executed instrument file</Label>
          <input
            key={fileInputKey}
            id={`${base}-file`}
            type="file"
            className="block w-full min-w-0 text-sm file:mr-3 file:rounded-md file:border file:border-[var(--color-line)] file:bg-white file:px-3 file:py-1.5 file:text-sm"
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? errorId : undefined}
            onChange={(event) => {
              const next = event.target.files?.[0] ?? null;
              setFile(next);
              setDuplicate(null);
              setError(null);
              if (next && !title.trim()) setTitle(next.name.replace(/\.[^.]+$/, ""));
            }}
          />
        </div>
        <div className="flex min-w-0 flex-col gap-1.5">
          <Label htmlFor={`${base}-title`}>Instrument title</Label>
          <Input id={`${base}-title`} value={title} placeholder="Deed of assignment dated …" onChange={(event) => setTitle(event.target.value)} />
        </div>
        <div className="flex min-w-0 flex-col gap-1.5">
          <Label htmlFor={`${base}-classification`}>Classification</Label>
          <select id={`${base}-classification`} className={SELECT_CLASS} value={chosenKey} onChange={(event) => setTaxonomyKey(event.target.value)}>
            <option value="" disabled>Choose a classification</option>
            {active.map((entry) => <option key={entry.key} value={entry.key}>{entry.label}</option>)}
          </select>
        </div>
        <div className="flex min-w-0 flex-col gap-1.5">
          <Label htmlFor={`${base}-confidentiality`}>Confidentiality</Label>
          <select id={`${base}-confidentiality`} className={SELECT_CLASS} value={confidentiality} onChange={(event) => setConfidentiality(event.target.value as Confidentiality)}>
            <option value="internal">Internal</option>
            <option value="confidential">Confidential</option>
            <option value="restricted">Restricted</option>
          </select>
        </div>
      </div>
      {missing.length ? (
        <p id={requirementsId} className="text-sm text-[var(--color-mute)]">Add {formatList(missing)} to upload.</p>
      ) : null}
      {duplicate ? (
        <div className="flex min-w-0 flex-col gap-2 text-sm" role="status">
          <p className="break-words">This file is already stored as “{duplicate.displayName}”. Link that copy to this docket instead of storing it twice.</p>
          <Button type="button" size="sm" variant="outline" className="w-full sm:w-fit" disabled={reuse.isPending} onClick={() => reuse.mutate()}>
            Link the stored copy to this docket
          </Button>
        </div>
      ) : null}
      {error ? <p id={errorId} role="alert" className="break-words text-sm text-[var(--color-danger-500)]">{error}</p> : null}
      <Button
        type="button"
        size="sm"
        className="w-full sm:w-fit"
        disabled={missing.length > 0 || upload.isPending}
        aria-describedby={missing.length ? requirementsId : undefined}
        onClick={() => upload.mutate()}
      >
        {upload.isPending ? <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden /> : <Upload className="h-4 w-4" aria-hidden />}
        Upload instrument
      </Button>
    </div>
  );
}
