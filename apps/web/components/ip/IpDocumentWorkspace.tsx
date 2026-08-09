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
import {
  addIpDocumentLinks,
  applyIpDocumentBulk,
  downloadApiFile,
  fetchIpDocuments,
  fetchIpDocumentTaxonomy,
  importIpDocumentAliases,
  previewIpDocumentName,
  previewIpDocumentBulk,
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
}: {
  dockets: IpDocket[];
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
  const [taxonomyKey, setTaxonomyKey] = useState("evidence");
  const [docketId, setDocketId] = useState(dockets[0]?.id ?? "");
  const [confidentiality, setConfidentiality] = useState<
    "internal" | "confidential" | "restricted"
  >("internal");
  const [isPrivileged, setIsPrivileged] = useState(false);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [bulkTaxonomy, setBulkTaxonomy] = useState("correspondence");
  const [bulkPreview, setBulkPreview] = useState<IpDocumentBulkPreview | null>(null);
  const [bulkItems, setBulkItems] = useState<IpDocumentBulkItem[]>([]);
  const [namePreview, setNamePreview] = useState<
    (IpDocumentNamingPreview & { inputKey: string }) | null
  >(null);
  const [aliasTaxonomy, setAliasTaxonomy] = useState("evidence");
  const [aliasText, setAliasText] = useState("");
  const [aliasPreview, setAliasPreview] = useState<IpDocumentAliasImportResult | null>(null);
  const [duplicate, setDuplicate] = useState<{
    documentId: string;
    displayName: string;
  } | null>(null);

  const documents = useQuery({ queryKey: ["ip", "documents"], queryFn: fetchIpDocuments });
  const taxonomy = useQuery({
    queryKey: ["ip", "document-taxonomy"],
    queryFn: fetchIpDocumentTaxonomy,
  });
  const activeTaxonomy = useMemo(
    () => taxonomy.data?.entries.filter((entry) => entry.is_active) ?? [],
    [taxonomy.data],
  );
  const existingDisplayNames = useMemo(
    () =>
      (documents.data?.items ?? [])
        .flatMap((document) => document.versions.map((version) => version.display_name))
        .sort((left, right) => left.localeCompare(right)),
    [documents.data],
  );
  const currentPreviewKey = JSON.stringify([
    file?.name ?? "",
    file?.size ?? 0,
    file?.lastModified ?? 0,
    clientCode,
    mark,
    jurisdiction,
    applicationNo,
    proceedingType,
    proceedingNo,
    taxonomyKey,
    documentDate,
    ...existingDisplayNames,
  ]);
  const hasCurrentPreview = namePreview?.inputKey === currentPreviewKey;
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
      if (!hasCurrentPreview) throw new Error("Preview the controlled name before upload.");
      return uploadIpDocument({
        file,
        taxonomyKey,
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
      const extension = file.name.includes(".") ? (file.name.split(".").pop() ?? "") : "";
      const result = await previewIpDocumentName({
        clientCode,
        mark,
        jurisdiction,
        applicationNo,
        proceedingType,
        proceedingNo,
        taxonomyKey,
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
    mutationFn: (dryRun: boolean) =>
      importIpDocumentAliases({ taxonomyKey: aliasTaxonomy, aliases, dryRun }),
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
  const previewBulk = useMutation({
    mutationFn: async () => {
      const chosen = (documents.data?.items ?? []).filter((row) =>
        selectedIds.includes(row.id),
      );
      const items: IpDocumentBulkItem[] = chosen.map((row) => ({
        document_id: row.id,
        expected_current_version: row.current_version,
        expected_taxonomy_key: row.taxonomy_key,
        taxonomy_key: bulkTaxonomy,
        naming: {
          client_code: clientCode || null,
          asset_type: "Trademark",
          document_type: bulkTaxonomy,
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
              <Label htmlFor="ip-document-mark">Mark</Label>
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
                className="h-10 w-full rounded-md border border-[var(--color-line)] bg-white px-3 text-sm"
                value={taxonomyKey}
                onChange={(event) => setTaxonomyKey(event.target.value)}
              >
                {activeTaxonomy.map((entry) => (
                  <option key={entry.key} value={entry.key}>{entry.label}</option>
                ))}
              </select>
            </div>
            <div className="min-w-0">
              <Label htmlFor="ip-document-docket">Linked docket</Label>
              <select
                id="ip-document-docket"
                className="h-10 w-full rounded-md border border-[var(--color-line)] bg-white px-3 text-sm"
                value={docketId}
                onChange={(event) => setDocketId(event.target.value)}
              >
                <option value="">Choose docket</option>
                {dockets.map((docket) => <option key={docket.id} value={docket.id}>{docket.title}</option>)}
              </select>
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
                disabled={!file || previewName.isPending}
              >
                Preview controlled name
              </Button>
              <Button
                type="submit"
                disabled={!file || !docketId || !hasCurrentPreview || upload.isPending}
              >
                <Upload className="h-4 w-4" aria-hidden /> Upload reviewed document
              </Button>
            </div>
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
                <Label htmlFor="ip-alias-taxonomy">Classification</Label>
                <select
                  id="ip-alias-taxonomy"
                  className="h-10 w-full rounded-md border border-[var(--color-line)] bg-white px-3 text-sm"
                  value={aliasTaxonomy}
                  onChange={(event) => {
                    setAliasTaxonomy(event.target.value);
                    setAliasPreview(null);
                  }}
                >
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
                disabled={aliases.length === 0 || importAliases.isPending}
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
                  || importAliases.isPending
                }
              >
                Import reviewed aliases
              </Button>
            </div>
          </div>
        ) : null}

        {(documents.data?.items.length ?? 0) > 1 && canManage ? (
          <div className="flex min-w-0 flex-col gap-3 rounded-lg border border-[var(--color-line)] p-4">
            <div className="flex min-w-0 w-full flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-end">
              <div className="min-w-0 flex-1">
                <Label htmlFor="ip-bulk-taxonomy">Bulk classification</Label>
                <select
                  id="ip-bulk-taxonomy"
                  className="h-10 w-full rounded-md border border-[var(--color-line)] bg-white px-3 text-sm"
                  value={bulkTaxonomy}
                  onChange={(event) => setBulkTaxonomy(event.target.value)}
                >
                  {activeTaxonomy.map((entry) => (
                    <option key={entry.key} value={entry.key}>{entry.label}</option>
                  ))}
                </select>
              </div>
              <Button
                variant="secondary"
                onClick={() => previewBulk.mutate()}
                disabled={selectedIds.length === 0 || previewBulk.isPending}
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
