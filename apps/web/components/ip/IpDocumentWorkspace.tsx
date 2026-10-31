"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Download, FileText, Link2, Upload } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import {
  addIpDocumentLinks,
  applyIpDocumentBulk,
  downloadApiFile,
  fetchIpDocuments,
  fetchIpDocumentsForDocket,
  fetchIpDocumentTaxonomy,
  importIpDocumentAliases,
  previewIpDocumentName,
  previewIpDocumentBulk,
  seedIpDocumentTaxonomy,
  transitionIpDocument,
  uploadIpDocument,
  uploadIpDocumentVersion,
  type IpDocket,
  type IpDocument,
  type IpDocumentAliasImportResult,
  type IpDocumentBulkItem,
  type IpDocumentBulkPreview,
  type IpDocumentNamingPreview,
  type IpDocumentState,
} from "@/lib/api/endpoints";
import { apiErrorMessage } from "@/lib/api/config";

const TAXONOMY_STATUS_ID = "ip-document-taxonomy-status";
const UPLOAD_REQUIREMENTS_ID = "ip-document-upload-requirements";

function formatList(items: string[]): string {
  if (items.length <= 1) return items.join("");
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

const NEXT_STATE: Partial<Record<IpDocumentState, IpDocumentState>> = {
  draft: "review",
  review: "approved",
  approved: "filed",
  filed: "served",
  served: "accepted",
  rejected: "draft",
};

export function IpDocumentWorkspace({
  dockets,
  canUpload,
  canManage,
  canReview,
  canConfigure,
  assetType = "Trademark",
  scopeDocketId,
  docketsLoading = false,
  docketsError = null,
  onRetryDockets,
}: {
  dockets: Pick<IpDocket, "id" | "title">[];
  /** The caller's docket listing is still loading, so an empty list means nothing yet. */
  docketsLoading?: boolean;
  /** The caller's docket listing failed; shown with a retry instead of "no docket yet". */
  docketsError?: unknown;
  onRetryDockets?: () => void;
  assetType?: "Trademark" | "Patent";
  scopeDocketId?: string;
  canUpload: boolean;
  canManage: boolean;
  canReview: boolean;
  canConfigure: boolean;
}) {
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [clientCode, setClientCode] = useState("");
  const [mark, setMark] = useState("");
  const [jurisdiction, setJurisdiction] = useState("");
  const [applicationNo, setApplicationNo] = useState("");
  const [proceedingType, setProceedingType] = useState("");
  const [proceedingNo, setProceedingNo] = useState("");
  const [documentDate, setDocumentDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [taxonomyKey, setTaxonomyKey] = useState("");
  const [docketId, setDocketId] = useState(dockets[0]?.id ?? "");
  const [confidentiality, setConfidentiality] = useState<
    "internal" | "confidential" | "restricted"
  >(assetType === "Patent" ? "restricted" : "internal");
  const [isPrivileged, setIsPrivileged] = useState(false);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [bulkTaxonomy, setBulkTaxonomy] = useState("");
  const [bulkPreview, setBulkPreview] = useState<IpDocumentBulkPreview | null>(null);
  const [bulkItems, setBulkItems] = useState<IpDocumentBulkItem[]>([]);
  const [namePreview, setNamePreview] = useState<
    (IpDocumentNamingPreview & { inputKey: string }) | null
  >(null);
  const [aliasTaxonomy, setAliasTaxonomy] = useState("");
  const [aliasText, setAliasText] = useState("");
  const [aliasPreview, setAliasPreview] = useState<IpDocumentAliasImportResult | null>(null);
  const [duplicate, setDuplicate] = useState<{
    documentId: string;
    displayName: string;
  } | null>(null);

  const documents = useQuery({
    queryKey: scopeDocketId ? ["ip", "documents", scopeDocketId] : ["ip", "documents"],
    queryFn: () => scopeDocketId ? fetchIpDocumentsForDocket(scopeDocketId) : fetchIpDocuments(),
  });
  const taxonomy = useQuery({
    queryKey: ["ip", "document-taxonomy"],
    queryFn: fetchIpDocumentTaxonomy,
  });
  const activeTaxonomy = useMemo(
    () => taxonomy.data?.entries.filter((entry) => entry.is_active) ?? [],
    [taxonomy.data],
  );
  // Every classification sent to the API is one the server listed as active.
  // A stale or never-chosen key resolves to "", which keeps its actions disabled.
  const activeTaxonomyKeys = useMemo(
    () => new Set(activeTaxonomy.map((entry) => entry.key)),
    [activeTaxonomy],
  );
  const documentTaxonomyKey = activeTaxonomyKeys.has(taxonomyKey) ? taxonomyKey : "";
  const aliasTaxonomyKey = activeTaxonomyKeys.has(aliasTaxonomy) ? aliasTaxonomy : "";
  const bulkTaxonomyKey = activeTaxonomyKeys.has(bulkTaxonomy) ? bulkTaxonomy : "";
  const taxonomyReady = activeTaxonomy.length > 0;
  const taxonomyDescription = taxonomyReady ? undefined : TAXONOMY_STATUS_ID;
  const showsBulk = (documents.data?.items.length ?? 0) > 1 && canManage;
  const showsTaxonomyStatus = !taxonomyReady && (canUpload || canConfigure || showsBulk);
  const existingDisplayNames = useMemo(
    () =>
      (documents.data?.items ?? [])
        .flatMap((document) => document.versions.map((version) => version.display_name))
        .sort((left, right) => left.localeCompare(right)),
    [documents.data],
  );
  const currentPreviewKey = JSON.stringify([
    assetType,
    file?.name ?? "",
    file?.size ?? 0,
    file?.lastModified ?? 0,
    clientCode,
    mark,
    jurisdiction,
    applicationNo,
    proceedingType,
    proceedingNo,
    documentTaxonomyKey,
    documentDate,
    ...existingDisplayNames,
  ]);
  const hasCurrentPreview = namePreview?.inputKey === currentPreviewKey;
  const uploadRequirements = [
    !file ? "the original file" : null,
    !documentTaxonomyKey ? "a classification" : null,
    !docketId
      ? dockets.length
        ? "a linked docket"
        : docketsLoading
          ? "a linked docket (the docket list is still loading)"
          : docketsError
            ? "a linked docket (the docket list could not load)"
            : "a linked docket (create an IP docket first)"
      : null,
  ].filter((value): value is string => value !== null);
  const uploadHint = !taxonomyReady
    ? null
    : uploadRequirements.length
      ? `Choose ${formatList(uploadRequirements)} before upload.`
      : !hasCurrentPreview
        ? "Preview the controlled name before upload."
        : null;
  const uploadDescription =
    taxonomyDescription ?? (uploadHint ? UPLOAD_REQUIREMENTS_ID : undefined);
  const aliases = aliasText
    .split(/\r?\n|,/)
    .map((value) => value.trim())
    .filter(Boolean);

  useEffect(() => {
    if (!docketId && dockets[0]?.id) setDocketId(dockets[0].id);
  }, [docketId, dockets]);
  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["ip", "documents"] });
  };

  const upload = useMutation({
    mutationFn: () => {
      if (!file || !docketId) throw new Error("Choose a file and linked docket.");
      if (!documentTaxonomyKey) throw new Error("Choose a classification.");
      if (!hasCurrentPreview) throw new Error("Preview the controlled name before upload.");
      return uploadIpDocument({
        assetType,
        file,
        taxonomyKey: documentTaxonomyKey,
        title,
        confidentiality,
        isPrivileged,
        clientCode,
        mark,
        jurisdiction,
        applicationNo,
        proceedingType,
        proceedingNo,
        documentDate,
        docketId,
      });
    },
    onSuccess: async (result) => {
      if (result.outcome === "duplicate_found") {
        const candidate = result.duplicate_candidates[0];
        setDuplicate(
          candidate
            ? { documentId: candidate.document_id, displayName: candidate.display_name }
            : null,
        );
        return;
      }
      setFile(null);
      setTitle("");
      setNamePreview(null);
      toast.success("Document uploaded; immutable original and processing evidence retained.");
      await refresh();
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Document upload failed.")),
  });
  const previewName = useMutation({
    mutationFn: async (inputKey: string) => {
      if (!file) throw new Error("Choose a file before previewing its controlled name.");
      if (!documentTaxonomyKey) throw new Error("Choose a classification.");
      const extension = file.name.includes(".") ? (file.name.split(".").pop() ?? "") : "";
      const result = await previewIpDocumentName({
        assetType,
        clientCode,
        mark,
        jurisdiction,
        applicationNo,
        proceedingType,
        proceedingNo,
        taxonomyKey: documentTaxonomyKey,
        documentDate,
        version: 1,
        extension,
        existingNames: existingDisplayNames,
      });
      return { ...result, inputKey };
    },
    onSuccess: setNamePreview,
    onError: (error) => toast.error(apiErrorMessage(error, "Name preview failed.")),
  });
  const reuse = useMutation({
    mutationFn: async () => {
      if (!duplicate || !docketId) throw new Error("Choose a docket for the reused document.");
      const current = documents.data?.items.find((row) => row.id === duplicate.documentId);
      if (!current) throw new Error("Refresh the document list before reusing this version.");
      return addIpDocumentLinks({
        documentId: current.id,
        expectedCurrentVersion: current.current_version,
        docketId,
      });
    },
    onSuccess: async () => {
      setDuplicate(null);
      toast.success("Existing content linked without creating a duplicate binary.");
      await refresh();
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not reuse document.")),
  });
  const transition = useMutation({
    mutationFn: (input: {
      documentId: string;
      version: number;
      expectedState: IpDocumentState;
      targetState: IpDocumentState;
    }) => transitionIpDocument(input),
    onSuccess: refresh,
    onError: (error) => toast.error(apiErrorMessage(error, "Document state did not change.")),
  });
  const newVersion = useMutation({
    mutationFn: (input: { document: IpDocument; file: File }) =>
      uploadIpDocumentVersion({
        assetType,
        documentId: input.document.id,
        expectedCurrentVersion: input.document.current_version,
        file: input.file,
        clientCode,
        mark,
        jurisdiction,
        applicationNo,
        proceedingType,
        proceedingNo,
        documentDate,
      }),
    onSuccess: async (result) => {
      if (result.outcome === "duplicate_found") {
        toast.error("Those bytes already exist. Reuse the existing document link instead.");
      } else {
        toast.success("New immutable version uploaded; the prior version is superseded.");
        await refresh();
      }
    },
    onError: (error) => toast.error(apiErrorMessage(error, "New version upload failed.")),
  });
  const download = useMutation({
    mutationFn: (input: { documentId: string; version: number; filename: string }) =>
      downloadApiFile(
        `/api/ip/documents/${encodeURIComponent(input.documentId)}/versions/${input.version}/download`,
        input.filename,
      ),
    onError: (error) => toast.error(apiErrorMessage(error, "Document download failed.")),
  });
  const importAliases = useMutation({
    mutationFn: async (dryRun: boolean) => {
      if (!aliasTaxonomyKey) throw new Error("Choose the classification these aliases map to.");
      return importIpDocumentAliases({ taxonomyKey: aliasTaxonomyKey, aliases, dryRun });
    },
    onSuccess: async (result) => {
      setAliasPreview(result);
      if (!result.dry_run) {
        toast.success(`${result.imported_count} taxonomy aliases imported.`);
        setAliasText("");
        await queryClient.invalidateQueries({ queryKey: ["ip", "document-taxonomy"] });
      }
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Alias import failed.")),
  });
  const seedTaxonomy = useMutation({
    mutationFn: seedIpDocumentTaxonomy,
    onSuccess: async (result) => {
      queryClient.setQueryData(["ip", "document-taxonomy"], result);
      toast.success("Standard document classifications loaded.");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["ip", "document-taxonomy"] }),
        queryClient.invalidateQueries({ queryKey: ["ip", "readiness"] }),
      ]);
    },
    onError: (error) =>
      toast.error(apiErrorMessage(error, "Standard classifications could not be loaded.")),
  });
  const previewBulk = useMutation({
    mutationFn: async () => {
      if (!bulkTaxonomyKey) throw new Error("Choose the new classification.");
      const chosen = (documents.data?.items ?? []).filter((row) =>
        selectedIds.includes(row.id),
      );
      const items: IpDocumentBulkItem[] = chosen.map((row) => ({
        document_id: row.id,
        expected_current_version: row.current_version,
        expected_taxonomy_key: row.taxonomy_key,
        taxonomy_key: bulkTaxonomyKey,
        naming: {
          client_code: clientCode || null,
          asset_type: assetType,
          document_type: bulkTaxonomyKey,
          document_date: new Date().toISOString().slice(0, 10),
          version: row.current_version,
          extension: row.versions[0]?.original_filename.split(".").pop() ?? null,
        },
      }));
      setBulkItems(items);
      return previewIpDocumentBulk(items);
    },
    onSuccess: setBulkPreview,
    onError: (error) => toast.error(apiErrorMessage(error, "Bulk preview failed.")),
  });
  const applyBulk = useMutation({
    mutationFn: () => {
      if (!bulkPreview) throw new Error("Preview the bulk change first.");
      return applyIpDocumentBulk({ items: bulkItems, previewToken: bulkPreview.preview_token });
    },
    onSuccess: async () => {
      setBulkPreview(null);
      setSelectedIds([]);
      toast.success("Previewed classification and rename changes applied atomically.");
      await refresh();
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Bulk apply failed.")),
  });

  return (
    <Card className="min-w-0" data-testid="ip-document-workspace">
      <CardHeader>
        <CardTitle as="h2">Document workflow</CardTitle>
        <p className="text-sm text-[var(--color-mute)]">
          Controlled names, immutable originals, version locks, OCR quality, and reusable links.
        </p>
      </CardHeader>
      <CardContent className="flex min-w-0 flex-col gap-5">
        {showsTaxonomyStatus ? (
          <TaxonomyStatus
            state={
              taxonomy.isPending
                ? "loading"
                : taxonomy.isError && !taxonomy.data
                  ? "error"
                  : (taxonomy.data?.entries.length ?? 0) === 0
                    ? "empty"
                    : "inactive"
            }
            error={taxonomy.error}
            onRetry={() => taxonomy.refetch()}
            canConfigure={canConfigure}
            seeding={seedTaxonomy.isPending}
            seedError={seedTaxonomy.isError ? seedTaxonomy.error : null}
            onSeed={() => seedTaxonomy.mutate()}
          />
        ) : null}
        {canUpload ? (
          <form
            className="grid min-w-0 gap-3 rounded-lg border border-[var(--color-line)] p-4 md:grid-cols-2"
            onSubmit={(event) => {
              event.preventDefault();
              upload.mutate();
            }}
          >
            <div className="min-w-0 md:col-span-2">
              <Label htmlFor="ip-document-file">Original file</Label>
              <Input
                id="ip-document-file"
                type="file"
                onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              />
              <p className="mt-1 text-xs text-[var(--color-mute)]">
                Original name and bytes remain immutable; the controlled display name is separate.
              </p>
            </div>
            <div className="min-w-0">
              <Label htmlFor="ip-document-title">Title</Label>
              <Input id="ip-document-title" value={title} onChange={(e) => setTitle(e.target.value)} />
            </div>
            <div className="min-w-0">
              <Label htmlFor="ip-document-client">Client code</Label>
              <Input
                id="ip-document-client"
                value={clientCode}
                onChange={(e) => setClientCode(e.target.value)}
              />
            </div>
            <div className="min-w-0">
              <Label htmlFor="ip-document-mark">{assetType === "Patent" ? "Invention" : "Mark"}</Label>
              <Input id="ip-document-mark" value={mark} onChange={(e) => setMark(e.target.value)} />
            </div>
            <div className="min-w-0">
              <Label htmlFor="ip-document-jurisdiction">Jurisdiction</Label>
              <Input
                id="ip-document-jurisdiction"
                value={jurisdiction}
                onChange={(e) => setJurisdiction(e.target.value)}
              />
            </div>
            <div className="min-w-0">
              <Label htmlFor="ip-document-application">Application number</Label>
              <Input
                id="ip-document-application"
                value={applicationNo}
                onChange={(e) => setApplicationNo(e.target.value)}
              />
            </div>
            <div className="min-w-0">
              <Label htmlFor="ip-document-proceeding-type">Proceeding type</Label>
              <Input
                id="ip-document-proceeding-type"
                value={proceedingType}
                onChange={(e) => setProceedingType(e.target.value)}
              />
            </div>
            <div className="min-w-0">
              <Label htmlFor="ip-document-proceeding-number">Proceeding number</Label>
              <Input
                id="ip-document-proceeding-number"
                value={proceedingNo}
                onChange={(e) => setProceedingNo(e.target.value)}
              />
            </div>
            <div className="min-w-0">
              <Label htmlFor="ip-document-date">Document date</Label>
              <Input
                id="ip-document-date"
                type="date"
                value={documentDate}
                onChange={(e) => setDocumentDate(e.target.value)}
              />
            </div>
            <div className="min-w-0">
              <Label htmlFor="ip-document-taxonomy">Classification</Label>
              <select
                id="ip-document-taxonomy"
                className="h-10 w-full rounded-md border border-[var(--color-line)] bg-white px-3 text-sm disabled:opacity-60"
                value={documentTaxonomyKey}
                disabled={!taxonomyReady}
                aria-describedby={taxonomyDescription}
                onChange={(event) => setTaxonomyKey(event.target.value)}
              >
                <TaxonomyPlaceholder loading={taxonomy.isPending} ready={taxonomyReady} />
                {activeTaxonomy.map((entry) => (
                  <option key={entry.key} value={entry.key}>{entry.label}</option>
                ))}
              </select>
            </div>
            <div className="min-w-0">
              <Label htmlFor="ip-document-docket">Linked docket</Label>
              <select
                id="ip-document-docket"
                className="h-10 w-full rounded-md border border-[var(--color-line)] bg-white px-3 text-sm disabled:opacity-60"
                value={docketId}
                disabled={dockets.length === 0}
                aria-describedby={dockets.length === 0 ? "ip-document-docket-empty" : undefined}
                onChange={(event) => setDocketId(event.target.value)}
              >
                <option value="">Choose docket</option>
                {dockets.map((docket) => <option key={docket.id} value={docket.id}>{docket.title}</option>)}
              </select>
              {dockets.length === 0 && docketsLoading ? (
                <p id="ip-document-docket-empty" role="status" className="mt-1 text-xs text-[var(--color-mute)]">
                  Loading dockets…
                </p>
              ) : dockets.length === 0 && docketsError ? (
                <div id="ip-document-docket-empty" role="alert" className="mt-1 flex min-w-0 flex-wrap items-center gap-2 text-xs text-[var(--color-danger-text)]">
                  <span className="min-w-0 break-words">{apiErrorMessage(docketsError, "The docket list could not load.")}</span>
                  {onRetryDockets ? (
                    <Button type="button" size="sm" variant="outline" onClick={onRetryDockets}>Try again</Button>
                  ) : null}
                </div>
              ) : dockets.length === 0 ? (
                <p id="ip-document-docket-empty" className="mt-1 text-xs text-[var(--color-mute)]">
                  No trademark docket yet. Create one with New trademark, then link the document to it here.
                </p>
              ) : null}
            </div>
            <div className="min-w-0">
              <Label htmlFor="ip-document-confidentiality">Confidentiality</Label>
              <select
                id="ip-document-confidentiality"
                className="h-10 w-full rounded-md border border-[var(--color-line)] bg-white px-3 text-sm"
                value={confidentiality}
                onChange={(event) =>
                  setConfidentiality(event.target.value as typeof confidentiality)
                }
              >
                <option value="internal">Internal</option>
                <option value="confidential">Confidential</option>
                <option value="restricted">Restricted</option>
              </select>
            </div>
            <label className="flex min-w-0 items-center gap-2 self-end py-2 text-sm">
              <input
                type="checkbox"
                checked={isPrivileged}
                onChange={(event) => setIsPrivileged(event.target.checked)}
              />
              Attorney-client privileged
            </label>
            {hasCurrentPreview ? (
              <div className="min-w-0 rounded-md bg-[var(--color-bg-2)] p-3 text-sm md:col-span-2">
                <p className="font-semibold">Controlled name preview</p>
                <p className="mt-1 break-all">{namePreview.resolved_name}</p>
                <p className="mt-1 text-xs text-[var(--color-mute)]">
                  Filing state starts as draft. Review the classification, date, linked docket,
                  confidentiality, and controlled name before upload.
                </p>
                {namePreview.conflict_detected ? (
                  <p className="mt-1 text-xs text-amber-800">
                    A deterministic conflict suffix will prevent overwrite.
                  </p>
                ) : null}
              </div>
            ) : null}
            <div className="flex min-w-0 w-full flex-wrap gap-2 md:col-span-2">
              <Button
                type="button"
                variant="secondary"
                onClick={() => previewName.mutate(currentPreviewKey)}
                disabled={!file || !documentTaxonomyKey || previewName.isPending}
                aria-describedby={uploadDescription}
              >
                Preview controlled name
              </Button>
              <Button
                type="submit"
                disabled={
                  !file || !documentTaxonomyKey || !docketId || !hasCurrentPreview || upload.isPending
                }
                aria-describedby={uploadDescription}
              >
                <Upload className="h-4 w-4" aria-hidden /> Upload reviewed document
              </Button>
            </div>
            {uploadHint ? (
              <p id={UPLOAD_REQUIREMENTS_ID} className="text-xs text-[var(--color-mute)] md:col-span-2">
                {uploadHint}
              </p>
            ) : null}
          </form>
        ) : null}

        {duplicate ? (
          <div className="flex min-w-0 w-full flex-col gap-3 rounded-lg border border-amber-300 bg-amber-50 p-4 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between">
            <div className="min-w-0">
              <p className="font-semibold">Duplicate content found</p>
              <p className="break-words text-sm">Reuse {duplicate.displayName} on the selected docket.</p>
            </div>
            <div className="flex min-w-0 w-full flex-wrap gap-2 sm:w-auto">
              {canManage ? (
                <Button onClick={() => reuse.mutate()} disabled={reuse.isPending}>
                  <Link2 className="h-4 w-4" aria-hidden /> Link existing document
                </Button>
              ) : (
                <p className="text-xs text-amber-900">
                  A document manager must approve the reusable legal-record link.
                </p>
              )}
              <Button variant="secondary" onClick={() => setDuplicate(null)}>Cancel</Button>
            </div>
          </div>
        ) : null}

        {canConfigure ? (
          <div className="flex min-w-0 flex-col gap-3 rounded-lg border border-[var(--color-line)] p-4">
            <div>
              <p className="font-semibold">Law-firm taxonomy aliases</p>
              <p className="text-sm text-[var(--color-mute)]">
                Paste supplied document names, one per line or comma-separated. Preview detects
                tenant collisions before import.
              </p>
            </div>
            <div className="grid min-w-0 gap-3 md:grid-cols-2">
              <div className="min-w-0">
                <Label htmlFor="ip-alias-taxonomy">Alias classification</Label>
                <select
                  id="ip-alias-taxonomy"
                  className="h-10 w-full rounded-md border border-[var(--color-line)] bg-white px-3 text-sm disabled:opacity-60"
                  value={aliasTaxonomyKey}
                  disabled={!taxonomyReady}
                  aria-describedby={taxonomyDescription}
                  onChange={(event) => {
                    setAliasTaxonomy(event.target.value);
                    setAliasPreview(null);
                  }}
                >
                  <TaxonomyPlaceholder loading={taxonomy.isPending} ready={taxonomyReady} />
                  {activeTaxonomy.map((entry) => (
                    <option key={entry.key} value={entry.key}>{entry.label}</option>
                  ))}
                </select>
              </div>
              <div className="min-w-0">
                <Label htmlFor="ip-alias-list">Supplied document names</Label>
                <textarea
                  id="ip-alias-list"
                  className="min-h-24 w-full rounded-md border border-[var(--color-line)] bg-white px-3 py-2 text-sm"
                  value={aliasText}
                  onChange={(event) => {
                    setAliasText(event.target.value);
                    setAliasPreview(null);
                  }}
                />
              </div>
            </div>
            {aliasPreview ? (
              <p className="text-sm" role="status">
                {aliasPreview.imported_count} new, {aliasPreview.unchanged_count} unchanged,{" "}
                {aliasPreview.conflicts.length} conflicts.
              </p>
            ) : null}
            <div className="flex min-w-0 w-full flex-wrap gap-2">
              <Button
                variant="secondary"
                onClick={() => importAliases.mutate(true)}
                disabled={aliases.length === 0 || !aliasTaxonomyKey || importAliases.isPending}
                aria-describedby={taxonomyDescription}
              >
                Preview alias import
              </Button>
              <Button
                onClick={() => importAliases.mutate(false)}
                disabled={
                  !aliasPreview
                  || !aliasPreview.dry_run
                  || aliasPreview.conflicts.length > 0
                  || aliasPreview.imported_count === 0
                  || !aliasTaxonomyKey
                  || importAliases.isPending
                }
              >
                Import reviewed aliases
              </Button>
            </div>
          </div>
        ) : null}

        {showsBulk ? (
          <div className="flex min-w-0 flex-col gap-3 rounded-lg border border-[var(--color-line)] p-4">
            <div className="flex min-w-0 w-full flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-end">
              <div className="min-w-0 flex-1">
                <Label htmlFor="ip-bulk-taxonomy">Bulk classification</Label>
                <select
                  id="ip-bulk-taxonomy"
                  className="h-10 w-full rounded-md border border-[var(--color-line)] bg-white px-3 text-sm disabled:opacity-60"
                  value={bulkTaxonomyKey}
                  disabled={!taxonomyReady}
                  aria-describedby={taxonomyDescription}
                  onChange={(event) => setBulkTaxonomy(event.target.value)}
                >
                  <TaxonomyPlaceholder loading={taxonomy.isPending} ready={taxonomyReady} />
                  {activeTaxonomy.map((entry) => (
                    <option key={entry.key} value={entry.key}>{entry.label}</option>
                  ))}
                </select>
              </div>
              <Button
                variant="secondary"
                onClick={() => previewBulk.mutate()}
                disabled={selectedIds.length === 0 || !bulkTaxonomyKey || previewBulk.isPending}
                aria-describedby={taxonomyDescription}
              >
                Preview rename and classification
              </Button>
            </div>
            {bulkPreview ? (
              <div className="min-w-0 rounded-md bg-[var(--color-bg-2)] p-3">
                <p className="font-semibold">Review {bulkPreview.items.length} proposed changes</p>
                {bulkPreview.items.map((item) => (
                  <p key={item.document_id} className="mt-1 break-all text-xs">
                    {item.current_display_name} → {item.proposed_display_name}
                    {item.conflict_detected ? " (conflict suffix added)" : ""}
                  </p>
                ))}
                <Button className="mt-3" onClick={() => applyBulk.mutate()} disabled={applyBulk.isPending}>
                  Apply reviewed changes
                </Button>
              </div>
            ) : null}
          </div>
        ) : null}

        {documents.isPending ? (
          <p className="text-sm">Loading documents…</p>
        ) : documents.isError ? (
          <p className="text-sm text-red-700">Documents could not be loaded.</p>
        ) : documents.data?.items.length === 0 ? (
          <p className="text-sm text-[var(--color-mute)]">No controlled IP documents yet.</p>
        ) : (
          <div className="flex min-w-0 flex-col gap-3">
            {documents.data?.items.map((document) => {
              const version = document.versions[0];
              if (!version) return null;
              const nextState = NEXT_STATE[version.state];
              const approvalRequired = nextState === "approved" || nextState === "filed";
              return (
                <article
                  key={document.id}
                  className="min-w-0 rounded-lg border border-[var(--color-line)] p-4"
                  data-testid={`ip-document-${document.id}`}
                >
                  <div className="flex min-w-0 w-full flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-start sm:justify-between">
                    <div className="flex min-w-0 gap-3">
                      {canManage ? (
                        <input
                          aria-label={`Select ${version.display_name}`}
                          type="checkbox"
                          checked={selectedIds.includes(document.id)}
                          onChange={(event) =>
                            setSelectedIds((current) =>
                              event.target.checked
                                ? [...current, document.id]
                                : current.filter((id) => id !== document.id),
                            )
                          }
                        />
                      ) : null}
                      <FileText className="mt-1 h-5 w-5 shrink-0" aria-hidden />
                      <div className="min-w-0">
                        <p className="break-all font-semibold">{version.display_name}</p>
                        <p className="break-all text-xs text-[var(--color-mute)]">
                          Original: {version.original_filename} · SHA-256 {version.sha256_hex.slice(0, 12)}…
                        </p>
                        <div className="mt-2 flex min-w-0 flex-wrap gap-2">
                          <Badge>{document.taxonomy_label}</Badge>
                          <Badge tone={version.state === "accepted" ? "success" : "brand"}>
                            {version.state} · v{version.version}
                          </Badge>
                          {document.is_privileged ? <Badge tone="warning">Privileged</Badge> : null}
                          {document.confidentiality !== "internal" ? (
                            <Badge tone="warning">{document.confidentiality}</Badge>
                          ) : null}
                        </div>
                      </div>
                    </div>
                    <div className="flex min-w-0 w-full flex-wrap gap-2 sm:w-auto">
                      <Button
                        variant="secondary"
                        size="sm"
                        onClick={() =>
                          download.mutate({
                            documentId: document.id,
                            version: version.version,
                            filename: version.original_filename,
                          })
                        }
                        disabled={download.isPending}
                      >
                        <Download className="h-4 w-4" aria-hidden /> Download original
                      </Button>
                      {nextState && canManage && (!approvalRequired || canReview) ? (
                        <Button
                          size="sm"
                          onClick={() =>
                            transition.mutate({
                              documentId: document.id,
                              version: version.version,
                              expectedState: version.state,
                              targetState: nextState,
                            })
                          }
                        >Move to {nextState}</Button>
                      ) : null}
                    </div>
                  </div>
                  {version.low_ocr_quality || version.processing_status !== "indexed" ? (
                    <div className="mt-3 flex min-w-0 gap-2 rounded-md bg-amber-50 p-3 text-sm text-amber-900">
                      <AlertTriangle className="h-4 w-4 shrink-0" aria-hidden />
                      <span>
                        Low or incomplete extraction quality. AI/search legal conclusions are disabled;
                        review the original or upload a clearer version.
                      </span>
                    </div>
                  ) : null}
                  {canUpload ? (
                    <label className="mt-3 flex min-w-0 w-full flex-col gap-1 text-sm sm:max-w-md">
                      <span className="font-medium">Upload a new immutable version</span>
                      <Input
                        aria-label={`New version for ${version.display_name}`}
                        type="file"
                        onChange={(event) => {
                          const nextFile = event.target.files?.[0];
                          if (nextFile) newVersion.mutate({ document, file: nextFile });
                        }}
                      />
                    </label>
                  ) : null}
                </article>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function TaxonomyPlaceholder({ loading, ready }: { loading: boolean; ready: boolean }) {
  return (
    <option value="" disabled>
      {loading ? "Loading classifications…" : ready ? "Choose a classification" : "No classifications available"}
    </option>
  );
}

function TaxonomyStatus({
  state,
  error,
  onRetry,
  canConfigure,
  seeding,
  seedError,
  onSeed,
}: {
  state: "loading" | "empty" | "inactive" | "error";
  error: unknown;
  onRetry: () => unknown;
  canConfigure: boolean;
  seeding: boolean;
  seedError: unknown;
  onSeed: () => void;
}) {
  if (state === "loading") {
    return (
      <p id={TAXONOMY_STATUS_ID} role="status" className="text-sm text-[var(--color-mute)]">
        Loading document classifications…
      </p>
    );
  }
  if (state === "error") {
    return (
      <div id={TAXONOMY_STATUS_ID}>
        <QueryErrorState
          error={error}
          title="Could not load document classifications"
          onRetry={onRetry}
        />
      </div>
    );
  }
  return (
    <div
      id={TAXONOMY_STATUS_ID}
      role="status"
      className="flex min-w-0 flex-col gap-2 rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm text-amber-950"
    >
      <p className="font-semibold">
        {state === "empty"
          ? "No document classifications are configured"
          : "Every document classification is inactive"}
      </p>
      <p>
        Uploads, alias imports and bulk reclassification need at least one active
        classification, so they stay disabled until one exists.
      </p>
      {state === "inactive" ? (
        <p>Ask an IP workspace admin to reactivate a classification for this workspace.</p>
      ) : canConfigure ? (
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <Button type="button" size="sm" onClick={onSeed} disabled={seeding}>
            {seeding ? "Loading standard classifications…" : "Load standard classifications"}
          </Button>
          <span className="text-xs">
            Adds the CaseOps trademark document categories. You can rename or deactivate them later.
          </span>
        </div>
      ) : (
        <p>Ask an IP workspace admin to load the standard document classifications.</p>
      )}
      {seedError ? (
        <p role="alert" className="text-red-800">
          {apiErrorMessage(seedError, "Standard classifications could not be loaded.")}
        </p>
      ) : null}
    </div>
  );
}
