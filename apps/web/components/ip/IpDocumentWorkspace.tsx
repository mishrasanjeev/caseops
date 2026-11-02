"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Archive, Download, FileText, Link2, Upload } from "lucide-react";
import Link from "next/link";
import { useEffect, useId, useMemo, useState } from "react";
import { toast } from "sonner";

import { IpDocketPicker } from "@/components/ip/IpDocketPicker";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Textarea } from "@/components/ui/Textarea";
import {
  addIpDocumentLinks,
  applyIpDocumentBulk,
  downloadApiFile,
  fetchIpDocumentRetirement,
  fetchIpDocuments,
  fetchIpDocumentsForDocket,
  fetchIpDocumentTaxonomy,
  importIpDocumentAliases,
  previewIpDocumentName,
  previewIpDocumentBulk,
  retireIpDocument,
  seedIpDocumentTaxonomy,
  transitionIpDocument,
  uploadIpDocument,
  uploadIpDocumentVersion,
  type IpDocument,
  type IpDocumentAliasImportResult,
  type IpDocumentBulkItem,
  type IpDocumentBulkPreview,
  type IpDocumentNamingPreview,
  type IpDocumentRetirementBlocker,
  type IpDocumentState,
} from "@/lib/api/endpoints";
import { apiErrorMessage, apiValidationIssues, isApiErrorShape } from "@/lib/api/config";
import { useSession } from "@/lib/use-session";

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
  canUpload,
  canManage,
  canReview,
  canConfigure,
  assetType = "Trademark",
  scopeDocketId,
  scopeDocketTitle,
  preferredDocketId,
}: {
  assetType?: "Trademark" | "Patent";
  /**
   * A record's own document area: documents are listed for, and uploaded to,
   * this docket only. Without it the linked docket is chosen from every
   * docket the user can see (server search and paging, never a first page).
   */
  scopeDocketId?: string;
  scopeDocketTitle?: string;
  /** Preselects this record as the linked docket (deep links); nothing else is preselected. */
  preferredDocketId?: string;
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
  const [chosenDocketId, setDocketId] = useState(() => preferredDocketId ?? "");
  const docketId = scopeDocketId ?? chosenDocketId;
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

  const session = useSession();
  const membershipId = session.context?.membership.id ?? null;
  // History adds retired documents and documents of closed records.
  const [showHistory, setShowHistory] = useState(false);
  const [retiringId, setRetiringId] = useState<string | null>(null);
  const historyToggleId = useId();
  const documents = useQuery({
    queryKey: [
      ...(scopeDocketId ? ["ip", "documents", scopeDocketId] : ["ip", "documents"]),
      ...(showHistory ? ["history"] : []),
    ],
    queryFn: () => scopeDocketId
      ? fetchIpDocumentsForDocket(scopeDocketId, { includeHistory: showHistory })
      : fetchIpDocuments({ includeHistory: showHistory }),
  });
  // Bulk changes only documents the API may still change: not retired and not
  // listed only because their record is closed (the history view).
  const currentDocuments = useMemo(
    () =>
      documents.data?.items.filter(
        (document) => !document.retirement && !document.read_only_reason,
      ) ?? [],
    [documents.data],
  );
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
  const showsBulk = currentDocuments.length > 1 && canManage;
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
    !docketId ? "a linked docket" : null,
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
    // A new deep link chooses its record; the user's own choice is otherwise kept.
    if (preferredDocketId) setDocketId(preferredDocketId);
  }, [preferredDocketId]);
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
      const chosen = currentDocuments.filter((row) => selectedIds.includes(row.id));
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
            {scopeDocketId ? (
              <div className="min-w-0">
                <p className="text-sm font-medium text-[var(--color-ink)]">Linked docket</p>
                <p className="mt-1 break-words text-sm" data-testid="ip-document-scope-docket">
                  {scopeDocketTitle ?? "This record"}
                </p>
              </div>
            ) : (
              <IpDocketPicker
                id="ip-document-docket"
                className="min-w-0 md:col-span-2"
                label="Linked docket"
                searchLabel="Find the linked docket"
                value={chosenDocketId}
                onChange={(next) => setDocketId(next)}
                required
              />
            )}
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

        <label
          htmlFor={historyToggleId}
          className="flex min-w-0 items-center gap-2 self-start text-sm"
        >
          <input
            id={historyToggleId}
            type="checkbox"
            checked={showHistory}
            onChange={(event) => {
              setShowHistory(event.target.checked);
              setRetiringId(null);
            }}
          />
          Show retired documents and documents of closed records
        </label>
        {documents.isPending ? (
          <p className="text-sm" role="status">Loading documents…</p>
        ) : documents.isError ? (
          <QueryErrorState
            error={documents.error}
            title="Documents could not be loaded"
            onRetry={() => documents.refetch()}
          />
        ) : documents.data?.items.length === 0 ? (
          <p className="text-sm text-[var(--color-mute)]">
            {showHistory
              ? "No controlled IP documents, current or retired."
              : "No current controlled IP documents. Retired documents appear when you show them above."}
          </p>
        ) : (
          <div className="flex min-w-0 flex-col gap-3">
            {documents.data?.items.map((document) => {
              const version = document.versions[0];
              if (!version) return null;
              const retired = document.retirement ?? null;
              const closedRecord = !retired && document.read_only_reason === "closed_record";
              const readOnly = !!retired || closedRecord;
              const nextState = readOnly ? undefined : NEXT_STATE[version.state];
              const approvalRequired = nextState === "approved" || nextState === "filed";
              const mayOfferRetire = !retired
                && (canManage || (canUpload && !!membershipId && document.created_by_membership_id === membershipId));
              return (
                <article
                  key={document.id}
                  className="min-w-0 rounded-lg border border-[var(--color-line)] p-4"
                  data-testid={`ip-document-${document.id}`}
                  data-retired={retired ? "true" : "false"}
                  data-read-only={readOnly ? "true" : "false"}
                >
                  <div className="flex min-w-0 w-full flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-start sm:justify-between">
                    <div className="flex min-w-0 gap-3">
                      {canManage && !readOnly ? (
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
                          {retired ? <Badge tone="neutral">Retired</Badge> : null}
                          {closedRecord ? <Badge tone="neutral">Closed record</Badge> : null}
                        </div>
                        {retired ? (
                          <p className="mt-2 break-words text-xs text-[var(--color-mute)]">
                            Retired {new Date(retired.retired_at).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })}{" "}
                            by {retired.retired_by_name}: {retired.reason}. Kept for history; it is
                            no longer offered as evidence.
                          </p>
                        ) : closedRecord ? (
                          <p className="mt-2 break-words text-xs text-[var(--color-mute)]">
                            Its record is closed, so this document is kept for history and cannot
                            change. You can download it or retire it; reopen the record to change it.
                          </p>
                        ) : null}
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
                      {mayOfferRetire ? (
                        <Button
                          variant="outline"
                          size="sm"
                          aria-expanded={retiringId === document.id}
                          aria-controls={`ip-document-retire-${document.id}`}
                          onClick={() => setRetiringId((current) => (current === document.id ? null : document.id))}
                        >
                          <Archive className="h-4 w-4" aria-hidden /> Retire
                        </Button>
                      ) : null}
                    </div>
                  </div>
                  {retiringId === document.id && !retired ? (
                    <RetireDocumentPanel
                      document={document}
                      onCancel={() => setRetiringId(null)}
                      onRetired={async () => {
                        setRetiringId(null);
                        await Promise.all([
                          refresh(),
                          queryClient.invalidateQueries({ queryKey: ["ip-documents"] }),
                        ]);
                      }}
                    />
                  ) : null}
                  {version.low_ocr_quality || version.processing_status !== "indexed" ? (
                    <div className="mt-3 flex min-w-0 gap-2 rounded-md bg-amber-50 p-3 text-sm text-amber-900">
                      <AlertTriangle className="h-4 w-4 shrink-0" aria-hidden />
                      <span>
                        Low or incomplete extraction quality. AI/search legal conclusions are disabled;
                        review the original or upload a clearer version.
                      </span>
                    </div>
                  ) : null}
                  {canUpload && !readOnly ? (
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

/** The server's blocking records from a refused retirement, when the error carries them. */
function blockersFrom(error: unknown): IpDocumentRetirementBlocker[] | null {
  if (!isApiErrorShape(error) || !error.data || typeof error.data !== "object") return null;
  const data = error.data as { code?: unknown; blockers?: unknown };
  return data.code === "ip_document_retirement_blocked" && Array.isArray(data.blockers)
    ? (data.blockers as IpDocumentRetirementBlocker[])
    : null;
}

function RetireDocumentPanel({
  document,
  onCancel,
  onRetired,
}: {
  document: IpDocument;
  onCancel: () => void;
  onRetired: () => Promise<void>;
}) {
  const panelId = `ip-document-retire-${document.id}`;
  const reasonId = `${panelId}-reason`;
  const reasonHelpId = `${reasonId}-help`;
  const reasonErrorId = `${reasonId}-error`;
  const blockedNoteId = `${panelId}-blocked`;
  const [reason, setReason] = useState("");
  const [reasonError, setReasonError] = useState<string | null>(null);
  const preview = useQuery({
    queryKey: ["ip", "documents", document.id, "retirement"],
    queryFn: () => fetchIpDocumentRetirement(document.id),
    staleTime: 0,
  });
  const retire = useMutation({
    mutationFn: () => {
      const trimmed = reason.trim();
      if (trimmed.length < 10) throw new Error("Give a reason of at least 10 characters.");
      return retireIpDocument({
        documentId: document.id,
        expectedCurrentVersion: preview.data?.current_version ?? document.current_version,
        reason: trimmed,
      });
    },
    onSuccess: async () => {
      toast.success("Document retired. It stays readable in history and is no longer offered as evidence.");
      await onRetired();
    },
    onError: async (error) => {
      if (blockersFrom(error)) {
        // A record started relying on it since the check: show the fresh list.
        await preview.refetch();
        return;
      }
      const issue = isApiErrorShape(error)
        ? apiValidationIssues(error.data).find((row) => row.loc.includes("reason"))
        : undefined;
      if (issue || (error instanceof Error && error.message.startsWith("Give a reason"))) {
        setReasonError(issue ? issue.msg.replace(/^Value error, /, "") : (error as Error).message);
        return;
      }
      toast.error(apiErrorMessage(error, "The document was not retired."));
    },
  });
  const data = preview.data;
  const blockers = data?.blockers ?? [];
  const blocked = !!data && (!data.may_retire || blockers.length > 0 || data.already_retired);
  return (
    <section
      id={panelId}
      aria-label={`Retire ${document.title}`}
      className="mt-3 flex min-w-0 flex-col gap-3 rounded-md border border-[var(--color-line)] bg-[var(--color-bg-2)] p-3 text-sm"
    >
      <p className="font-semibold">Retire this document</p>
      <p className="text-[var(--color-mute)]">
        Retiring keeps the file, its versions and its audit trail. It stops the document being
        offered or accepted as evidence anywhere in the IP workspace.
      </p>
      {preview.isPending ? (
        <p role="status">Checking which records rely on this document…</p>
      ) : preview.isError ? (
        <QueryErrorState
          error={preview.error}
          title="Could not check which records rely on this document"
          onRetry={() => preview.refetch()}
        />
      ) : data && !data.may_retire ? (
        <p id={blockedNoteId} role="status">{data.permission_reason}</p>
      ) : data?.already_retired ? (
        <p id={blockedNoteId} role="status">This document is already retired.</p>
      ) : blockers.length ? (
        <div id={blockedNoteId} role="status" className="flex min-w-0 flex-col gap-2">
          <p>
            {blockers.length === 1
              ? "1 record still relies on this document as evidence. Release it first:"
              : `${blockers.length} records still rely on this document as evidence. Release them first:`}
          </p>
          <ul className="flex min-w-0 flex-col gap-2" data-testid="ip-document-retirement-blockers">
            {blockers.map((blocker, index) => (
              <li
                key={`${blocker.kind}-${blocker.record_id}-${index}`}
                className="min-w-0 rounded-md border border-[var(--color-line)] bg-white p-2"
              >
                <p className="break-words font-medium">
                  {blocker.label}
                  {blocker.status ? ` · ${blocker.status.replaceAll("_", " ")}` : ""}
                </p>
                {blocker.docket_title ? (
                  <p className="break-words text-xs text-[var(--color-mute)]">On {blocker.docket_title}</p>
                ) : null}
                <p className="break-words text-xs">
                  {blocker.resolution}{" "}
                  {blocker.href ? (
                    <Link className="font-semibold text-[var(--color-brand-700)] underline" href={blocker.href}>
                      Open
                    </Link>
                  ) : null}
                </p>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <div className="flex min-w-0 flex-col gap-1">
          <Label htmlFor={reasonId}>Reason for retiring</Label>
          <Textarea
            id={reasonId}
            value={reason}
            rows={2}
            maxLength={1000}
            aria-invalid={reasonError ? true : undefined}
            aria-describedby={reasonError ? `${reasonErrorId} ${reasonHelpId}` : reasonHelpId}
            onChange={(event) => {
              setReason(event.target.value);
              setReasonError(null);
            }}
          />
          <p id={reasonHelpId} className="text-xs text-[var(--color-mute)]">
            At least 10 characters. Recorded in the audit trail with your name.
          </p>
          {reasonError ? (
            <p id={reasonErrorId} role="alert" className="text-xs text-[var(--color-danger-text)]">
              {reasonError}
            </p>
          ) : null}
        </div>
      )}
      <div className="flex min-w-0 flex-wrap gap-2">
        <Button
          size="sm"
          onClick={() => retire.mutate()}
          disabled={!data || blocked || retire.isPending}
          aria-describedby={blocked ? blockedNoteId : undefined}
        >
          {retire.isPending ? "Retiring…" : "Retire document"}
        </Button>
        <Button size="sm" variant="ghost" onClick={onCancel}>Cancel</Button>
      </div>
    </section>
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
