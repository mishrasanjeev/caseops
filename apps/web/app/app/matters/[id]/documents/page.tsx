"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Eye,
  File,
  FileText,
  Loader2,
  Pencil,
  RefreshCw,
  Save,
  Search,
  Upload,
  X,
} from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { Fragment, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { apiErrorMessage } from "@/lib/api/config";
import {
  reindexMatterAttachment,
  retryMatterAttachment,
  updateMatterAttachmentMetadata,
  uploadMatterAttachment,
} from "@/lib/api/endpoints";
import type {
  MatterDocumentType,
  MatterLifecycleStage,
} from "@/lib/api/endpoints";
import { useCapability } from "@/lib/capabilities";
import { useMatterWorkspace } from "@/lib/use-matter-workspace";
import type {
  WorkspaceAttachment,
  WorkspaceCourtOrder,
  WorkspaceHearing,
} from "@/lib/api/workspace-types";

const DOCUMENT_TYPE_OPTIONS: Array<{ value: MatterDocumentType; label: string }> = [
  { value: "complaint_petition", label: "Complaint / petition" },
  { value: "notice", label: "Notice" },
  { value: "vakalatnama", label: "Vakalatnama" },
  { value: "pleading_reply", label: "Pleading / reply" },
  { value: "affidavit", label: "Affidavit" },
  { value: "evidence", label: "Evidence" },
  { value: "written_submission", label: "Written submission" },
  { value: "interim_application", label: "Interim application" },
  { value: "order_judgment", label: "Order / judgment" },
  { value: "correspondence", label: "Correspondence" },
  { value: "research", label: "Research" },
  { value: "billing", label: "Billing" },
  { value: "other", label: "Other" },
];

const LIFECYCLE_STAGE_OPTIONS: Array<{ value: MatterLifecycleStage; label: string }> = [
  { value: "initiation", label: "Initiation" },
  { value: "pleadings", label: "Pleadings" },
  { value: "interim_applications", label: "Interim applications" },
  { value: "evidence", label: "Evidence" },
  { value: "arguments", label: "Arguments" },
  { value: "orders", label: "Orders" },
  { value: "post_order", label: "Post-order" },
  { value: "administrative", label: "Administrative" },
  { value: "other", label: "Other" },
];

const DEFAULT_STAGE_BY_TYPE: Record<MatterDocumentType, MatterLifecycleStage> = {
  complaint_petition: "initiation",
  notice: "initiation",
  vakalatnama: "administrative",
  pleading_reply: "pleadings",
  affidavit: "pleadings",
  evidence: "evidence",
  written_submission: "arguments",
  interim_application: "interim_applications",
  order_judgment: "orders",
  correspondence: "administrative",
  research: "administrative",
  billing: "administrative",
  other: "other",
};

const LIFECYCLE_SEQUENCE: Array<MatterLifecycleStage | "unclassified"> = [
  "initiation",
  "pleadings",
  "interim_applications",
  "evidence",
  "arguments",
  "orders",
  "post_order",
  "administrative",
  "other",
  "unclassified",
];

const RETRY_STATUSES = new Set(["failed", "needs_ocr", "pending"]);
const REINDEX_STATUSES = new Set(["indexed"]);
const UNCLASSIFIED = "unclassified" as const;
const NO_LINKED_ORDER = "none";
const NO_LINKED_HEARING = "none";
const HEARING_FILTER_ALL = "all" as const;
const HEARING_FILTER_NONE = "none" as const;

type MetadataDraft = {
  documentType: MatterDocumentType | typeof UNCLASSIFIED;
  lifecycleStage: MatterLifecycleStage | typeof UNCLASSIFIED;
  documentDate: string;
  sequenceIndex: string;
  linkedCourtOrderId: string;
  hearingId: string;
};

type UploadMetadata = {
  documentType: MatterDocumentType;
  lifecycleStage: MatterLifecycleStage;
  documentDate: string;
  sequenceIndex: string;
  linkedCourtOrderId: string;
  hearingId: string;
};

function humanSize(bytes: number | null | undefined): string {
  if (!bytes || bytes <= 0) return "-";
  const units = ["B", "KB", "MB", "GB"];
  let i = 0;
  let size = bytes;
  while (size >= 1024 && i < units.length - 1) {
    size /= 1024;
    i += 1;
  }
  return `${size.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

function labelFor<T extends string>(
  options: Array<{ value: T; label: string }>,
  value: T | string | null | undefined,
  fallback = "Unclassified",
): string {
  if (!value) return fallback;
  return options.find((option) => option.value === value)?.label ?? fallback;
}

function documentDate(doc: WorkspaceAttachment): string | null {
  return doc.document_date ?? null;
}

function dateLabel(value: string | null | undefined): string {
  if (!value) return "-";
  return new Date(value).toLocaleDateString(undefined, {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

function sequenceValue(value: string): number | null {
  if (!value.trim()) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : null;
}

function metadataDraftFromDoc(doc: WorkspaceAttachment): MetadataDraft {
  return {
    documentType: (doc.document_type as MatterDocumentType | null) ?? UNCLASSIFIED,
    lifecycleStage: (doc.lifecycle_stage as MatterLifecycleStage | null) ?? UNCLASSIFIED,
    documentDate: doc.document_date ?? "",
    sequenceIndex:
      doc.sequence_index === null || doc.sequence_index === undefined
        ? ""
        : String(doc.sequence_index),
    linkedCourtOrderId: doc.linked_court_order_id ?? NO_LINKED_ORDER,
    hearingId: doc.hearing_id ?? NO_LINKED_HEARING,
  };
}

function orderLabel(order: WorkspaceCourtOrder): string {
  const title = order.title ?? "Court order";
  const date = order.order_date ? dateLabel(order.order_date) : null;
  return date ? `${date} - ${title}` : title;
}

function hearingDate(hearing: WorkspaceHearing): string | null | undefined {
  return hearing.hearing_on ?? hearing.scheduled_for ?? hearing.listing_date;
}

function hearingLabel(hearing: WorkspaceHearing): string {
  const date = hearingDate(hearing);
  const dateText = date ? dateLabel(date) : "Unscheduled";
  const subject = hearing.purpose ?? hearing.hearing_type ?? "Hearing";
  return `${dateText} - ${subject}`;
}

function groupAttachments(attachments: WorkspaceAttachment[]) {
  const rank = new Map(LIFECYCLE_SEQUENCE.map((stage, index) => [stage, index]));
  const sorted = [...attachments].sort((left, right) => {
    const leftStage = (left.lifecycle_stage ?? UNCLASSIFIED) as MatterLifecycleStage | typeof UNCLASSIFIED;
    const rightStage = (right.lifecycle_stage ?? UNCLASSIFIED) as MatterLifecycleStage | typeof UNCLASSIFIED;
    const stageDelta = (rank.get(leftStage) ?? 99) - (rank.get(rightStage) ?? 99);
    if (stageDelta !== 0) return stageDelta;
    const leftSequence = left.sequence_index ?? Number.MAX_SAFE_INTEGER;
    const rightSequence = right.sequence_index ?? Number.MAX_SAFE_INTEGER;
    if (leftSequence !== rightSequence) return leftSequence - rightSequence;
    const leftDate = documentDate(left) ?? left.created_at;
    const rightDate = documentDate(right) ?? right.created_at;
    if (leftDate !== rightDate) return leftDate.localeCompare(rightDate);
    const leftName = left.original_filename ?? left.filename ?? "";
    const rightName = right.original_filename ?? right.filename ?? "";
    return leftName.localeCompare(rightName);
  });
  return LIFECYCLE_SEQUENCE.map((stage) => ({
    stage,
    documents: sorted.filter((doc) => (doc.lifecycle_stage ?? UNCLASSIFIED) === stage),
  })).filter((group) => group.documents.length > 0);
}

function selectClassName() {
  return "h-10 w-full rounded-md border border-[var(--color-line)] bg-white px-3 text-sm text-[var(--color-ink)] shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-brand-500)]";
}

export default function MatterDocumentsPage() {
  const params = useParams<{ id: string }>();
  const matterId = params.id;
  const queryClient = useQueryClient();
  const { data } = useMatterWorkspace(matterId);
  const canUpload = useCapability("documents:upload");
  const canManage = useCapability("documents:manage");
  const fileInput = useRef<HTMLInputElement | null>(null);
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [metadataDraft, setMetadataDraft] = useState<MetadataDraft | null>(null);
  // BUG-043 (Hari 2026-05-11): client-side search across the loaded
  // attachment set. Matches on filename, document type label, and
  // lifecycle stage label so a lawyer hunting "vakalatnama" or
  // "evidence" finds them without scrolling. Backend full-text search
  // over attachment_chunks is a follow-up; the workspace endpoint
  // already returns the full attachment list for the matter so client
  // filter is the right scope today.
  const [searchQ, setSearchQ] = useState("");
  // BUG-045 (Hari 2026-05-11): filter by hearing — "all" shows
  // everything, "none" shows un-linked, "<id>" shows the chosen
  // hearing's evidence. Stays in sync with the upload-metadata
  // hearing selector so a user can scope-then-add.
  const [hearingFilter, setHearingFilter] = useState<string>(HEARING_FILTER_ALL);
  const [uploadMetadata, setUploadMetadata] = useState<UploadMetadata>({
    documentType: "other",
    lifecycleStage: "other",
    documentDate: "",
    sequenceIndex: "",
    linkedCourtOrderId: NO_LINKED_ORDER,
    hearingId: NO_LINKED_HEARING,
  });

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ["matters", matterId, "workspace"] });

  const uploadMutation = useMutation({
    mutationFn: (file: File) =>
      uploadMatterAttachment({
        matterId,
        file,
        documentType: uploadMetadata.documentType,
        lifecycleStage: uploadMetadata.lifecycleStage,
        documentDate: uploadMetadata.documentDate || null,
        sequenceIndex: sequenceValue(uploadMetadata.sequenceIndex),
        linkedCourtOrderId:
          uploadMetadata.linkedCourtOrderId === NO_LINKED_ORDER
            ? null
            : uploadMetadata.linkedCourtOrderId,
        hearingId:
          uploadMetadata.hearingId === NO_LINKED_HEARING
            ? null
            : uploadMetadata.hearingId,
      }),
    onSuccess: async () => {
      await invalidate();
      toast.success("Document uploaded - processing will begin shortly.");
    },
    onError: (err) => {
      toast.error(apiErrorMessage(err, "Could not upload the document."));
    },
    onSettled: () => {
      if (fileInput.current) fileInput.current.value = "";
    },
  });

  const metadataMutation = useMutation({
    mutationFn: ({ attachmentId, draft }: { attachmentId: string; draft: MetadataDraft }) =>
      updateMatterAttachmentMetadata({
        matterId,
        attachmentId,
        document_type: draft.documentType === UNCLASSIFIED ? null : draft.documentType,
        lifecycle_stage: draft.lifecycleStage === UNCLASSIFIED ? null : draft.lifecycleStage,
        document_date: draft.documentDate || null,
        sequence_index: sequenceValue(draft.sequenceIndex),
        linked_court_order_id:
          draft.linkedCourtOrderId === NO_LINKED_ORDER ? null : draft.linkedCourtOrderId,
        hearing_id:
          draft.hearingId === NO_LINKED_HEARING ? null : draft.hearingId,
      }),
    onMutate: ({ attachmentId }) => setPendingId(attachmentId),
    onSuccess: async () => {
      await invalidate();
      toast.success("Document metadata updated.");
      setEditingId(null);
      setMetadataDraft(null);
    },
    onError: (err) => {
      toast.error(apiErrorMessage(err, "Could not update document metadata."));
    },
    onSettled: () => setPendingId(null),
  });

  const retryMutation = useMutation({
    mutationFn: (attachmentId: string) =>
      retryMatterAttachment({ matterId, attachmentId }),
    onMutate: (attachmentId) => setPendingId(attachmentId),
    onSuccess: async () => {
      await invalidate();
      toast.success("Retry queued.");
    },
    onError: (err) => {
      toast.error(apiErrorMessage(err, "Could not retry processing."));
    },
    onSettled: () => setPendingId(null),
  });

  const reindexMutation = useMutation({
    mutationFn: (attachmentId: string) =>
      reindexMatterAttachment({ matterId, attachmentId }),
    onMutate: (attachmentId) => setPendingId(attachmentId),
    onSuccess: async () => {
      await invalidate();
      toast.success("Reindex queued.");
    },
    onError: (err) => {
      toast.error(apiErrorMessage(err, "Could not reindex the document."));
    },
    onSettled: () => setPendingId(null),
  });

  const filteredAttachments = useMemo(() => {
    const all = data?.attachments ?? [];
    const q = searchQ.trim().toLowerCase();
    return all.filter((doc) => {
      // BUG-045: hearing filter
      if (hearingFilter === HEARING_FILTER_NONE) {
        if (doc.hearing_id) return false;
      } else if (hearingFilter !== HEARING_FILTER_ALL) {
        if (doc.hearing_id !== hearingFilter) return false;
      }
      if (!q) return true;
      const haystack = [
        doc.original_filename ?? "",
        doc.filename ?? "",
        labelFor(DOCUMENT_TYPE_OPTIONS, doc.document_type),
        labelFor(LIFECYCLE_STAGE_OPTIONS, doc.lifecycle_stage),
      ]
        .join(" | ")
        .toLowerCase();
      return haystack.includes(q);
    });
  }, [data?.attachments, searchQ, hearingFilter]);
  const groupedAttachments = useMemo(
    () => groupAttachments(filteredAttachments),
    [filteredAttachments],
  );

  if (!data) return null;
  const attachments = data.attachments;
  const courtOrders = data.court_orders ?? [];
  const hearings: WorkspaceHearing[] = data.hearings ?? [];
  const sortedHearings = [...hearings].sort((a, b) => {
    const aDate = hearingDate(a) ?? "";
    const bDate = hearingDate(b) ?? "";
    return bDate.localeCompare(aDate);
  });
  const hearingsById = new Map<string, WorkspaceHearing>(
    hearings.map((h) => [h.id, h]),
  );
  const isFiltered =
    searchQ.trim().length > 0 || hearingFilter !== HEARING_FILTER_ALL;

  function handleFileChange(event: React.ChangeEvent<HTMLInputElement>) {
    const selected = event.target.files?.[0];
    if (selected) uploadMutation.mutate(selected);
  }

  function handleUploadDocumentType(value: MatterDocumentType) {
    setUploadMetadata((current) => ({
      ...current,
      documentType: value,
      lifecycleStage: DEFAULT_STAGE_BY_TYPE[value],
    }));
  }

  function beginEdit(doc: WorkspaceAttachment) {
    setEditingId(doc.id);
    setMetadataDraft(metadataDraftFromDoc(doc));
  }

  function updateDraft(patch: Partial<MetadataDraft>) {
    setMetadataDraft((current) => (current ? { ...current, ...patch } : current));
  }

  const uploader = canUpload ? (
    <div className="rounded-lg border border-[var(--color-line)] bg-[var(--color-bg-2)] p-4">
      <div className="grid gap-3 lg:grid-cols-[1.1fr_1.1fr_0.9fr_0.7fr]">
        <div>
          <Label htmlFor="upload-document-type">Document type</Label>
          <select
            id="upload-document-type"
            className={`${selectClassName()} mt-1.5`}
            value={uploadMetadata.documentType}
            onChange={(event) =>
              handleUploadDocumentType(event.target.value as MatterDocumentType)
            }
            data-testid="matter-attachment-document-type"
          >
            {DOCUMENT_TYPE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <Label htmlFor="upload-lifecycle-stage">Lifecycle</Label>
          <select
            id="upload-lifecycle-stage"
            className={`${selectClassName()} mt-1.5`}
            value={uploadMetadata.lifecycleStage}
            onChange={(event) =>
              setUploadMetadata((current) => ({
                ...current,
                lifecycleStage: event.target.value as MatterLifecycleStage,
              }))
            }
            data-testid="matter-attachment-lifecycle-stage"
          >
            {LIFECYCLE_STAGE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <Label htmlFor="upload-document-date">Document date</Label>
          <Input
            id="upload-document-date"
            className="mt-1.5"
            type="date"
            value={uploadMetadata.documentDate}
            onChange={(event) =>
              setUploadMetadata((current) => ({
                ...current,
                documentDate: event.target.value,
              }))
            }
          />
        </div>
        <div>
          <Label htmlFor="upload-sequence-index">Sequence</Label>
          <Input
            id="upload-sequence-index"
            className="mt-1.5"
            type="number"
            min={0}
            value={uploadMetadata.sequenceIndex}
            onChange={(event) =>
              setUploadMetadata((current) => ({
                ...current,
                sequenceIndex: event.target.value,
              }))
            }
          />
        </div>
      </div>
      <div className="mt-3 grid gap-3 lg:grid-cols-[1fr_1fr_auto] lg:items-end">
        <div className="w-full">
          <Label htmlFor="upload-linked-order">Linked order</Label>
          <select
            id="upload-linked-order"
            className={`${selectClassName()} mt-1.5`}
            value={uploadMetadata.linkedCourtOrderId}
            onChange={(event) =>
              setUploadMetadata((current) => ({
                ...current,
                linkedCourtOrderId: event.target.value,
              }))
            }
          >
            <option value={NO_LINKED_ORDER}>No linked order</option>
            {courtOrders.map((order) => (
              <option key={order.id} value={order.id}>
                {orderLabel(order)}
              </option>
            ))}
          </select>
        </div>
        {/* BUG-045 (Hari 2026-05-11): hearing selector for the
            upload form. Lets the lawyer tag this evidence with the
            specific hearing it belongs to so it shows up in the
            hearing-filtered view + downstream hearing pack. */}
        <div className="w-full">
          <Label htmlFor="upload-linked-hearing">Linked hearing</Label>
          <select
            id="upload-linked-hearing"
            className={`${selectClassName()} mt-1.5`}
            value={uploadMetadata.hearingId}
            onChange={(event) =>
              setUploadMetadata((current) => ({
                ...current,
                hearingId: event.target.value,
              }))
            }
            data-testid="matter-attachment-linked-hearing"
          >
            <option value={NO_LINKED_HEARING}>No linked hearing</option>
            {sortedHearings.map((hearing) => (
              <option key={hearing.id} value={hearing.id}>
                {hearingLabel(hearing)}
              </option>
            ))}
          </select>
        </div>
        <div className="flex justify-end">
          <input
            ref={fileInput}
            type="file"
            className="sr-only"
            data-testid="matter-attachment-file-input"
            accept=".pdf,.doc,.docx,.txt,.rtf,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain,application/rtf"
            onChange={handleFileChange}
          />
          <Button
            type="button"
            size="sm"
            disabled={uploadMutation.isPending}
            onClick={() => fileInput.current?.click()}
            data-testid="matter-attachment-upload"
          >
            {uploadMutation.isPending ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Uploading...
              </>
            ) : (
              <>
                <Upload className="h-4 w-4" aria-hidden /> Upload
              </>
            )}
          </Button>
        </div>
      </div>
    </div>
  ) : null;

  if (attachments.length === 0) {
    return (
      <div className="flex flex-col gap-6">
        {uploader}
        <EmptyState
          icon={FileText}
          title="No documents attached yet"
          description={
            canUpload
              ? "Upload a pleading, order, or piece of correspondence and CaseOps will index it for this matter."
              : "Nothing has been uploaded to this matter yet. Ask a team member with document-manage access to add files."
          }
        />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      {uploader}
      {/* BUG-043 (Hari 2026-05-11): document search bar. Filters the
          rendered groups in-place so the lifecycle structure is
          preserved when a query is active. The "Showing N of M" hint
          + Clear button keep the empty filtered-result state from
          looking like data loss. */}
      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-[var(--color-line)] bg-white px-3 py-2">
        <Search
          className="h-4 w-4 shrink-0 text-[var(--color-mute)]"
          aria-hidden
        />
        <Input
          id="matter-document-search"
          type="search"
          placeholder="Search by filename, document type, or lifecycle"
          className="h-9 flex-1 border-0 shadow-none focus-visible:ring-0"
          value={searchQ}
          onChange={(event) => setSearchQ(event.target.value)}
          data-testid="matter-document-search"
          aria-label="Search uploaded documents"
        />
        {/* BUG-045: hearing filter — scope the documents tab to a
            single hearing so the lawyer can pull "all evidence for
            22 May listing" without scrolling. */}
        {sortedHearings.length > 0 ? (
          <select
            id="matter-document-hearing-filter"
            className="h-9 rounded-md border border-[var(--color-line)] bg-white px-2 text-sm text-[var(--color-ink)]"
            value={hearingFilter}
            onChange={(event) => setHearingFilter(event.target.value)}
            data-testid="matter-document-hearing-filter"
            aria-label="Filter by hearing"
          >
            <option value={HEARING_FILTER_ALL}>All hearings</option>
            <option value={HEARING_FILTER_NONE}>Not linked to a hearing</option>
            {sortedHearings.map((hearing) => (
              <option key={hearing.id} value={hearing.id}>
                {hearingLabel(hearing)}
              </option>
            ))}
          </select>
        ) : null}
        {isFiltered ? (
          <>
            <span
              className="text-xs text-[var(--color-mute)]"
              data-testid="matter-document-search-count"
            >
              Showing {filteredAttachments.length} of {attachments.length}
            </span>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => {
                setSearchQ("");
                setHearingFilter(HEARING_FILTER_ALL);
              }}
              data-testid="matter-document-search-clear"
            >
              <X className="h-3.5 w-3.5" aria-hidden /> Clear
            </Button>
          </>
        ) : null}
      </div>
      {isFiltered && filteredAttachments.length === 0 ? (
        <EmptyState
          icon={Search}
          title="No documents match this search"
          description={`Nothing in this matter matched "${searchQ.trim()}". Try a different filename or document type.`}
        />
      ) : (
      <Card>
        <CardContent className="p-0">
          {groupedAttachments.map((group) => (
            <section
              key={group.stage}
              className="border-b border-[var(--color-line)] last:border-0"
              data-testid={`matter-document-group-${group.stage}`}
            >
              <div className="flex items-center justify-between gap-3 bg-[var(--color-bg)] px-4 py-2.5">
                <div className="text-xs font-semibold uppercase tracking-[0.06em] text-[var(--color-mute)]">
                  {group.stage === UNCLASSIFIED
                    ? "Unclassified"
                    : labelFor(LIFECYCLE_STAGE_OPTIONS, group.stage)}
                </div>
                <Badge tone="neutral" className="py-0.5">
                  {group.documents.length}
                </Badge>
              </div>
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-[var(--color-line)] text-xs uppercase tracking-[0.06em] text-[var(--color-mute)]">
                    <th className="px-4 py-2.5 text-left font-semibold">File</th>
                    <th className="px-4 py-2.5 text-left font-semibold">Lifecycle</th>
                    <th className="px-4 py-2.5 text-left font-semibold">Date</th>
                    <th className="px-4 py-2.5 text-left font-semibold">Size</th>
                    <th className="px-4 py-2.5 text-left font-semibold">Processing</th>
                    <th className="px-4 py-2.5 text-left font-semibold">Added</th>
                    <th className="px-4 py-2.5 text-right font-semibold">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {group.documents.map((doc) => {
                    const status = (doc.processing_status ?? "unknown").toLowerCase();
                    const isPending = pendingId === doc.id;
                    const canRetry = canManage && RETRY_STATUSES.has(status);
                    const canReindex = canManage && REINDEX_STATUSES.has(status);
                    const viewHref = `/app/matters/${matterId}/documents/${doc.id}/view`;
                    const typeLabel = labelFor(
                      DOCUMENT_TYPE_OPTIONS,
                      doc.document_type,
                    );
                    const lifecycleLabel = labelFor(
                      LIFECYCLE_STAGE_OPTIONS,
                      doc.lifecycle_stage,
                    );
                    return (
                      <Fragment key={doc.id}>
                        <tr
                          className="border-b border-[var(--color-line-2)] last:border-0"
                        >
                          <td className="px-4 py-3">
                            <Link
                              href={viewHref}
                              className="inline-flex items-center gap-2 font-medium text-[var(--color-ink)] hover:underline"
                              data-testid={`matter-attachment-name-${doc.id}`}
                            >
                              <File className="h-4 w-4 text-[var(--color-mute)]" aria-hidden />
                              <span>
                                {doc.original_filename ?? doc.filename ?? "Untitled"}
                              </span>
                            </Link>
                            <div className="mt-1 flex flex-wrap gap-1.5">
                              <Badge tone={doc.document_type ? "brand" : "neutral"}>
                                {typeLabel}
                              </Badge>
                              {doc.linked_court_order_id ? (
                                <Badge tone="neutral">Linked order</Badge>
                              ) : null}
                              {/* BUG-045: hearing chip — surface the
                                  linked hearing date inline so the
                                  context is visible from the list. */}
                              {doc.hearing_id && hearingsById.has(doc.hearing_id) ? (
                                <span
                                  data-testid={`matter-attachment-hearing-${doc.id}`}
                                  className="contents"
                                >
                                  <Badge tone="neutral">
                                    Hearing:{" "}
                                    {dateLabel(
                                      hearingDate(hearingsById.get(doc.hearing_id)!),
                                    )}
                                  </Badge>
                                </span>
                              ) : null}
                            </div>
                          </td>
                          <td className="px-4 py-3 text-xs text-[var(--color-mute)]">
                            <div>{lifecycleLabel}</div>
                            {doc.sequence_index !== null && doc.sequence_index !== undefined ? (
                              <div className="mt-1 text-[var(--color-mute-2)]">
                                Seq {doc.sequence_index}
                              </div>
                            ) : null}
                          </td>
                          <td className="px-4 py-3 text-xs text-[var(--color-mute)]">
                            {dateLabel(doc.document_date)}
                          </td>
                          <td className="px-4 py-3 text-xs text-[var(--color-mute)]">
                            {humanSize(doc.size_bytes)}
                          </td>
                          <td className="px-4 py-3">
                            <StatusBadge status={doc.processing_status ?? "unknown"} />
                          </td>
                          <td className="px-4 py-3 text-xs text-[var(--color-mute)]">
                            {dateLabel(doc.created_at)}
                          </td>
                          <td className="px-4 py-3 text-right">
                            <div className="inline-flex flex-wrap justify-end gap-2">
                              <Button
                                variant="ghost"
                                size="sm"
                                href={viewHref}
                                data-testid={`matter-attachment-view-${doc.id}`}
                              >
                                <Eye className="h-4 w-4" aria-hidden />
                                View
                              </Button>
                              {canManage ? (
                                <Button
                                  type="button"
                                  variant="ghost"
                                  size="sm"
                                  onClick={() => beginEdit(doc)}
                                  data-testid={`matter-attachment-edit-${doc.id}`}
                                >
                                  <Pencil className="h-4 w-4" aria-hidden />
                                  Metadata
                                </Button>
                              ) : null}
                              {canRetry ? (
                                <Button
                                  type="button"
                                  variant="ghost"
                                  size="sm"
                                  disabled={isPending}
                                  onClick={() => retryMutation.mutate(doc.id)}
                                  data-testid={`matter-attachment-retry-${doc.id}`}
                                >
                                  {isPending && retryMutation.isPending ? (
                                    <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                                  ) : (
                                    <RefreshCw className="h-4 w-4" aria-hidden />
                                  )}
                                  Retry
                                </Button>
                              ) : null}
                              {canReindex ? (
                                <Button
                                  type="button"
                                  variant="ghost"
                                  size="sm"
                                  disabled={isPending}
                                  onClick={() => reindexMutation.mutate(doc.id)}
                                  data-testid={`matter-attachment-reindex-${doc.id}`}
                                >
                                  {isPending && reindexMutation.isPending ? (
                                    <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                                  ) : (
                                    <RefreshCw className="h-4 w-4" aria-hidden />
                                  )}
                                  Reindex
                                </Button>
                              ) : null}
                            </div>
                          </td>
                        </tr>
                        {editingId === doc.id && metadataDraft ? (
                          <tr className="border-b border-[var(--color-line-2)] bg-[var(--color-bg-2)]">
                            <td colSpan={7} className="px-4 py-3">
                              <div className="grid gap-3 lg:grid-cols-[1.1fr_1.1fr_0.8fr_0.6fr_1.2fr_auto] lg:items-end">
                                <div>
                                  <Label htmlFor={`document-type-${doc.id}`}>Document type</Label>
                                  <select
                                    id={`document-type-${doc.id}`}
                                    className={`${selectClassName()} mt-1.5`}
                                    value={metadataDraft.documentType}
                                    onChange={(event) => {
                                      const value = event.target.value as MatterDocumentType | typeof UNCLASSIFIED;
                                      updateDraft({
                                        documentType: value,
                                        lifecycleStage:
                                          value === UNCLASSIFIED
                                            ? UNCLASSIFIED
                                            : DEFAULT_STAGE_BY_TYPE[value],
                                      });
                                    }}
                                  >
                                    <option value={UNCLASSIFIED}>Unclassified</option>
                                    {DOCUMENT_TYPE_OPTIONS.map((option) => (
                                      <option key={option.value} value={option.value}>
                                        {option.label}
                                      </option>
                                    ))}
                                  </select>
                                </div>
                                <div>
                                  <Label htmlFor={`lifecycle-${doc.id}`}>Lifecycle</Label>
                                  <select
                                    id={`lifecycle-${doc.id}`}
                                    className={`${selectClassName()} mt-1.5`}
                                    value={metadataDraft.lifecycleStage}
                                    onChange={(event) =>
                                      updateDraft({
                                        lifecycleStage: event.target.value as MatterLifecycleStage | typeof UNCLASSIFIED,
                                      })
                                    }
                                  >
                                    <option value={UNCLASSIFIED}>Unclassified</option>
                                    {LIFECYCLE_STAGE_OPTIONS.map((option) => (
                                      <option key={option.value} value={option.value}>
                                        {option.label}
                                      </option>
                                    ))}
                                  </select>
                                </div>
                                <div>
                                  <Label htmlFor={`document-date-${doc.id}`}>Document date</Label>
                                  <Input
                                    id={`document-date-${doc.id}`}
                                    className="mt-1.5"
                                    type="date"
                                    value={metadataDraft.documentDate}
                                    onChange={(event) =>
                                      updateDraft({ documentDate: event.target.value })
                                    }
                                  />
                                </div>
                                <div>
                                  <Label htmlFor={`sequence-${doc.id}`}>Sequence</Label>
                                  <Input
                                    id={`sequence-${doc.id}`}
                                    className="mt-1.5"
                                    type="number"
                                    min={0}
                                    value={metadataDraft.sequenceIndex}
                                    onChange={(event) =>
                                      updateDraft({ sequenceIndex: event.target.value })
                                    }
                                  />
                                </div>
                                <div>
                                  <Label htmlFor={`linked-order-${doc.id}`}>Linked order</Label>
                                  <select
                                    id={`linked-order-${doc.id}`}
                                    className={`${selectClassName()} mt-1.5`}
                                    value={metadataDraft.linkedCourtOrderId}
                                    onChange={(event) =>
                                      updateDraft({ linkedCourtOrderId: event.target.value })
                                    }
                                  >
                                    <option value={NO_LINKED_ORDER}>No linked order</option>
                                    {courtOrders.map((order) => (
                                      <option key={order.id} value={order.id}>
                                        {orderLabel(order)}
                                      </option>
                                    ))}
                                  </select>
                                </div>
                                {/* BUG-045: hearing selector inside
                                    the metadata edit row, mirroring
                                    the upload form. */}
                                <div>
                                  <Label htmlFor={`linked-hearing-${doc.id}`}>Linked hearing</Label>
                                  <select
                                    id={`linked-hearing-${doc.id}`}
                                    className={`${selectClassName()} mt-1.5`}
                                    value={metadataDraft.hearingId}
                                    onChange={(event) =>
                                      updateDraft({ hearingId: event.target.value })
                                    }
                                    data-testid={`matter-attachment-edit-hearing-${doc.id}`}
                                  >
                                    <option value={NO_LINKED_HEARING}>No linked hearing</option>
                                    {sortedHearings.map((hearing) => (
                                      <option key={hearing.id} value={hearing.id}>
                                        {hearingLabel(hearing)}
                                      </option>
                                    ))}
                                  </select>
                                </div>
                                <div className="flex justify-end gap-2">
                                  <Button
                                    type="button"
                                    variant="outline"
                                    size="sm"
                                    onClick={() => {
                                      setEditingId(null);
                                      setMetadataDraft(null);
                                    }}
                                  >
                                    <X className="h-4 w-4" aria-hidden />
                                    Cancel
                                  </Button>
                                  <Button
                                    type="button"
                                    size="sm"
                                    disabled={metadataMutation.isPending}
                                    onClick={() =>
                                      metadataMutation.mutate({
                                        attachmentId: doc.id,
                                        draft: metadataDraft,
                                      })
                                    }
                                    data-testid={`matter-attachment-save-${doc.id}`}
                                  >
                                    {isPending && metadataMutation.isPending ? (
                                      <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                                    ) : (
                                      <Save className="h-4 w-4" aria-hidden />
                                    )}
                                    Save
                                  </Button>
                                </div>
                              </div>
                            </td>
                          </tr>
                        ) : null}
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
            </section>
          ))}
        </CardContent>
      </Card>
      )}
    </div>
  );
}
