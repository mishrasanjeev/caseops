"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ClipboardList,
  Download,
  Eye,
  File,
  FileText,
  HardDrive,
  HelpCircle,
  Loader2,
  MessageSquareText,
  Pencil,
  RefreshCw,
  Save,
  Search,
  Send,
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
import { Textarea } from "@/components/ui/Textarea";
import { apiErrorMessage } from "@/lib/api/config";
import {
  askMatterFileQuestion,
  analyzeAffidavitIntelligence,
  exportMatterFileQANote,
  fetchAffidavitIntelligence,
  fetchGoogleDriveStatus,
  fetchMatterFileQAHistory,
  listGoogleDriveFiles,
  matterAttachmentBulkDownloadUrl,
  reindexMatterAttachment,
  revokeGoogleDriveConnection,
  retryMatterAttachment,
  startGoogleDriveConnection,
  updateMatterAttachmentMetadata,
  uploadMatterAttachment,
} from "@/lib/api/endpoints";
import type {
  MatterDocumentType,
  MatterLifecycleStage,
} from "@/lib/api/endpoints";
import type {
  AffidavitIntelligenceResponse,
  AffidavitQuestion,
  AffidavitStatement,
  MatterFileQAAnswerMode,
  MatterFileQAAnalysisLanguage,
  MatterFileQAHistoryEntry,
  MatterFileQAResponse,
  MatterFileQAStructuredItem,
  GoogleDriveFileRecord,
} from "@/lib/api/schemas";
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
  { value: "chief_affidavit", label: "Chief affidavit" },
  { value: "counter_affidavit", label: "Counter affidavit" },
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
  chief_affidavit: "pleadings",
  counter_affidavit: "pleadings",
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
const AFFIDAVIT_DOCUMENT_TYPES = new Set([
  "affidavit",
  "chief_affidavit",
  "counter_affidavit",
]);
const MATTER_FILE_QA_MODES: Array<{
  value: MatterFileQAAnswerMode;
  label: string;
}> = [
  { value: "direct", label: "Direct answer" },
  { value: "summary", label: "Summary" },
  { value: "sections", label: "Sections" },
  { value: "allegations", label: "Allegations" },
  { value: "evidence", label: "Evidence" },
  { value: "chronology", label: "Chronology" },
  { value: "gaps", label: "Gaps" },
];
const MATTER_FILE_QA_LANGUAGES: Array<{
  value: MatterFileQAAnalysisLanguage;
  label: string;
}> = [
  { value: "en", label: "English" },
  { value: "hi", label: "Hindi" },
  { value: "mr", label: "Marathi" },
  { value: "gu", label: "Gujarati" },
  { value: "ta", label: "Tamil" },
  { value: "te", label: "Telugu" },
  { value: "kn", label: "Kannada" },
  { value: "bn", label: "Bengali" },
];
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

function GoogleDriveDocumentsPanel({
  configured,
  missingConfigNames,
  connectedEmail,
  files,
  message,
  isBusy,
  onConnect,
  onListFiles,
  onRevoke,
}: {
  configured: boolean;
  missingConfigNames: string[];
  connectedEmail: string | null;
  files: GoogleDriveFileRecord[];
  message: string | null;
  isBusy: boolean;
  onConnect: () => void;
  onListFiles: () => void;
  onRevoke: () => void;
}) {
  return (
    <div
      className="rounded-lg border border-[var(--color-line)] bg-white p-4"
      data-testid="matter-google-drive-panel"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <span className="inline-flex h-9 w-9 items-center justify-center rounded-md bg-[var(--color-bg-2)] text-[var(--color-ink-2)]">
            <HardDrive className="h-4 w-4" aria-hidden />
          </span>
          <div>
            <h2 className="text-sm font-semibold text-[var(--color-ink)]">
              Google Drive
            </h2>
            <p className="text-xs text-[var(--color-mute)]">
              {connectedEmail
                ? `Connected as ${connectedEmail}`
                : configured
                  ? "Connect your Drive to list recent file metadata."
                  : "Google Drive OAuth is not configured."}
            </p>
            {!configured && missingConfigNames.length > 0 ? (
              <p className="mt-1 text-xs text-[var(--color-mute)]">
                Missing config: {missingConfigNames.join(", ")}
              </p>
            ) : null}
          </div>
        </div>
        <Badge tone={connectedEmail ? "success" : configured ? "brand" : "warning"}>
          {connectedEmail ? "connected" : configured ? "ready" : "blocked"}
        </Badge>
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        {connectedEmail ? (
          <>
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={isBusy}
              onClick={onListFiles}
              data-testid="matter-google-drive-list"
            >
              {isBusy ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              ) : (
                <RefreshCw className="h-4 w-4" aria-hidden />
              )}
              List files
            </Button>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              disabled={isBusy}
              onClick={onRevoke}
              data-testid="matter-google-drive-revoke"
            >
              Revoke
            </Button>
          </>
        ) : (
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={isBusy || !configured}
            onClick={onConnect}
            data-testid="matter-google-drive-connect"
          >
            Connect Drive
          </Button>
        )}
      </div>
      {message ? (
        <div
          className="mt-3 text-xs text-[var(--color-mute)]"
          data-testid="matter-google-drive-message"
        >
          {message}
        </div>
      ) : null}
      {files.length > 0 ? (
        <div
          className="mt-3 divide-y divide-[var(--color-line)] rounded-md border border-[var(--color-line)] bg-[var(--color-bg-2)]"
          data-testid="matter-google-drive-files"
        >
          {files.slice(0, 5).map((file) => (
            <div key={file.provider_file_id} className="px-3 py-2">
              <div className="truncate text-xs font-medium text-[var(--color-ink)]">
                {file.name}
              </div>
              <div className="mt-0.5 text-xs text-[var(--color-mute)]">
                {file.mime_type ?? "file"} - {humanSize(file.size_bytes)}
              </div>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function compactLabel(value: string): string {
  return value
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function affidavitViewHref(matterId: string, attachmentId: string): string {
  return `/app/matters/${encodeURIComponent(matterId)}/documents/${encodeURIComponent(
    attachmentId,
  )}/view`;
}

export default function MatterDocumentsPage() {
  const params = useParams<{ id: string }>();
  const matterId = params.id;
  const queryClient = useQueryClient();
  const { data } = useMatterWorkspace(matterId);
  const canUpload = useCapability("documents:upload");
  const canManage = useCapability("documents:manage");
  const canAnalyzeAffidavit = useCapability("hearing_packs:generate");
  const canAskCaseFile = useCapability("ai:generate");
  const fileInput = useRef<HTMLInputElement | null>(null);
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [analysisPendingId, setAnalysisPendingId] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [metadataDraft, setMetadataDraft] = useState<MetadataDraft | null>(null);
  const [selectedAttachmentIds, setSelectedAttachmentIds] = useState<string[]>([]);
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
  const [googleDriveMessage, setGoogleDriveMessage] = useState<string | null>(null);
  const [googleDriveFiles, setGoogleDriveFiles] = useState<GoogleDriveFileRecord[]>([]);

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ["matters", matterId, "workspace"] });
  const affidavitQuery = useQuery({
    queryKey: ["matters", matterId, "affidavit-intelligence"],
    queryFn: () => fetchAffidavitIntelligence({ matterId }),
    enabled: Boolean(matterId),
  });
  const googleDriveStatusQuery = useQuery({
    queryKey: ["drive", "google", "status"],
    queryFn: fetchGoogleDriveStatus,
    enabled: canUpload,
  });

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

  const affidavitMutation = useMutation({
    mutationFn: (attachmentId: string) =>
      analyzeAffidavitIntelligence({ matterId, attachmentId }),
    onMutate: (attachmentId) => setAnalysisPendingId(attachmentId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["matters", matterId, "affidavit-intelligence"],
      });
      toast.success("Affidavit analysis generated.");
    },
    onError: (err) => {
      toast.error(apiErrorMessage(err, "Could not analyze the affidavit."));
    },
    onSettled: () => setAnalysisPendingId(null),
  });
  const startGoogleDriveMutation = useMutation({
    mutationFn: startGoogleDriveConnection,
    onSuccess: (result) => {
      if (result.auth_url) {
        window.location.assign(result.auth_url);
        return;
      }
      setGoogleDriveMessage(
        result.unavailable_reason ?? "Google Drive connection is unavailable.",
      );
    },
    onError: (err) => {
      setGoogleDriveMessage(apiErrorMessage(err, "Could not start Google Drive."));
    },
  });
  const listGoogleDriveMutation = useMutation({
    mutationFn: () => listGoogleDriveFiles({ limit: 10 }),
    onSuccess: (result) => {
      setGoogleDriveFiles(result.files);
      setGoogleDriveMessage(`Loaded ${result.files.length} recent Drive files.`);
      void queryClient.invalidateQueries({ queryKey: ["drive", "google", "status"] });
    },
    onError: (err) => {
      setGoogleDriveMessage(apiErrorMessage(err, "Could not list Google Drive files."));
    },
  });
  const revokeGoogleDriveMutation = useMutation({
    mutationFn: revokeGoogleDriveConnection,
    onSuccess: () => {
      setGoogleDriveFiles([]);
      setGoogleDriveMessage("Google Drive connection revoked.");
      void queryClient.invalidateQueries({ queryKey: ["drive", "google", "status"] });
    },
    onError: (err) => {
      setGoogleDriveMessage(apiErrorMessage(err, "Could not revoke Google Drive."));
    },
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
  const attachmentIdSet = useMemo(
    () => new Set((data?.attachments ?? []).map((attachment) => attachment.id)),
    [data?.attachments],
  );
  const activeSelectedAttachmentIds = useMemo(
    () => selectedAttachmentIds.filter((attachmentId) => attachmentIdSet.has(attachmentId)),
    [attachmentIdSet, selectedAttachmentIds],
  );
  const selectedAttachmentSet = useMemo(
    () => new Set(activeSelectedAttachmentIds),
    [activeSelectedAttachmentIds],
  );
  const visibleAttachmentIds = useMemo(
    () => filteredAttachments.map((attachment) => attachment.id),
    [filteredAttachments],
  );
  const allVisibleSelected =
    visibleAttachmentIds.length > 0 &&
    visibleAttachmentIds.every((attachmentId) => selectedAttachmentSet.has(attachmentId));
  const bulkDownloadHref =
    activeSelectedAttachmentIds.length > 0
      ? matterAttachmentBulkDownloadUrl({
          matterId,
          attachmentIds: activeSelectedAttachmentIds,
        })
      : null;

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
  const storagePolicy = data.storage_governance;
  const uploadBlockedByQuota =
    storagePolicy?.state === "hard_limit" &&
    storagePolicy.quota_bytes !== null &&
    (storagePolicy.remaining_bytes ?? 0) <= 0;
  const isFiltered =
    searchQ.trim().length > 0 || hearingFilter !== HEARING_FILTER_ALL;
  const googleDriveConnection =
    googleDriveStatusQuery.data?.connections.find(
      (connection) => connection.status === "connected",
    ) ?? null;
  const googleDriveConfigured = googleDriveStatusQuery.data?.configured ?? false;
  const googleDriveBusy =
    googleDriveStatusQuery.isPending ||
    startGoogleDriveMutation.isPending ||
    listGoogleDriveMutation.isPending ||
    revokeGoogleDriveMutation.isPending;
  const googleDrivePanel = canUpload ? (
    <GoogleDriveDocumentsPanel
      configured={googleDriveConfigured}
      missingConfigNames={googleDriveStatusQuery.data?.missing_config_names ?? []}
      connectedEmail={googleDriveConnection?.display_email ?? null}
      files={googleDriveFiles}
      message={googleDriveMessage}
      isBusy={googleDriveBusy}
      onConnect={() => startGoogleDriveMutation.mutate()}
      onListFiles={() => listGoogleDriveMutation.mutate()}
      onRevoke={() => {
        if (googleDriveConnection) {
          revokeGoogleDriveMutation.mutate(googleDriveConnection.id);
        }
      }}
    />
  ) : null;
  const affidavitSection = (
    <AffidavitIntelligenceSection
      matterId={matterId}
      attachments={attachments}
      data={affidavitQuery.data}
      isLoading={affidavitQuery.isPending}
      error={affidavitQuery.error}
      canAnalyze={canAnalyzeAffidavit}
      analysisPendingId={analysisPendingId}
      isAnalyzePending={affidavitMutation.isPending}
      onAnalyze={(attachmentId) => affidavitMutation.mutate(attachmentId)}
      onRetry={() => void affidavitQuery.refetch()}
    />
  );
  const askCaseFileSection = (
    <AskCaseFileSection
      matterId={matterId}
      attachments={attachments}
      canAsk={canAskCaseFile}
    />
  );

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

  function toggleAttachmentSelection(attachmentId: string) {
    setSelectedAttachmentIds((current) =>
      current.includes(attachmentId)
        ? current.filter((selectedId) => selectedId !== attachmentId)
        : [...current, attachmentId],
    );
  }

  function toggleVisibleAttachmentSelection() {
    setSelectedAttachmentIds((current) => {
      const currentSet = new Set(current);
      if (allVisibleSelected) {
        return current.filter((attachmentId) => !visibleAttachmentIds.includes(attachmentId));
      }
      for (const attachmentId of visibleAttachmentIds) {
        currentSet.add(attachmentId);
      }
      return Array.from(currentSet);
    });
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
      {storagePolicy ? (
        <div
          className="mt-3 flex flex-wrap items-center gap-2 text-xs text-[var(--color-mute)]"
          data-testid="matter-storage-upload-policy"
        >
          <span>Max file {humanSize(storagePolicy.max_upload_size_bytes)}</span>
          <span>
            Firm quota remaining{" "}
            {storagePolicy.remaining_bytes === null
              ? "Unlimited"
              : humanSize(storagePolicy.remaining_bytes)}
          </span>
          {uploadBlockedByQuota ? (
            <span
              className="inline-flex items-center gap-1 font-medium text-red-700"
              data-testid="matter-storage-upload-blocked"
            >
              <AlertTriangle className="h-3.5 w-3.5" aria-hidden />
              Firm storage quota reached
            </span>
          ) : null}
        </div>
      ) : null}
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
            disabled={uploadMutation.isPending || uploadBlockedByQuota}
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
        {googleDrivePanel}
        {askCaseFileSection}
        {affidavitSection}
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
      {googleDrivePanel}
      {askCaseFileSection}
      {affidavitSection}
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
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-[var(--color-line)] bg-white px-3 py-2">
        <label className="inline-flex items-center gap-2 text-sm text-[var(--color-ink-2)]">
          <input
            type="checkbox"
            className="h-4 w-4 rounded border-[var(--color-line)]"
            checked={allVisibleSelected}
            disabled={visibleAttachmentIds.length === 0}
            onChange={toggleVisibleAttachmentSelection}
            data-testid="matter-documents-select-visible"
          />
          Select visible
        </label>
        <div className="flex flex-wrap items-center gap-2">
          <span
            className="text-xs text-[var(--color-mute)]"
            data-testid="matter-documents-selected-count"
          >
            {activeSelectedAttachmentIds.length} selected
          </span>
          {bulkDownloadHref ? (
            <Button
              href={bulkDownloadHref}
              variant="outline"
              size="sm"
              data-testid="matter-documents-bulk-download"
              download
            >
              <Download className="h-4 w-4" aria-hidden />
              Download selected
            </Button>
          ) : (
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled
              data-testid="matter-documents-bulk-download"
            >
              <Download className="h-4 w-4" aria-hidden />
              Download selected
            </Button>
          )}
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={activeSelectedAttachmentIds.length === 0}
            onClick={() => setSelectedAttachmentIds([])}
            data-testid="matter-documents-clear-selection"
          >
            <X className="h-4 w-4" aria-hidden />
            Clear
          </Button>
        </div>
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
                    <th className="w-10 px-4 py-2.5 text-left font-semibold">Select</th>
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
                          <td className="px-4 py-3 align-top">
                            <input
                              type="checkbox"
                              className="h-4 w-4 rounded border-[var(--color-line)]"
                              checked={selectedAttachmentSet.has(doc.id)}
                              onChange={() => toggleAttachmentSelection(doc.id)}
                              aria-label={`Select ${doc.original_filename ?? doc.filename ?? "document"}`}
                              data-testid={`matter-document-select-${doc.id}`}
                            />
                          </td>
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
                            <td colSpan={8} className="px-4 py-3">
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

const FORBIDDEN_MATTER_FILE_QA_COPY = /\b(legal[- ]advice|guaranteed outcome|guaranteed to win|will win|will lose|success probability|outcome prediction|win probability|loss probability|win\s*(?:[/-]|\s+)\s*loss|judge reputation|judge shopping|best judge|most suitable judge|judge likes|judge dislikes|favorable judge|emotion|emotional|psychological|biometric|mental[- ]health|lie detection|reveal all tenant documents|reveal tenant data|reveal all documents)\b/i;

function matterFileQAStatusLabel(status: MatterFileQAResponse["status"]): string {
  return compactLabel(status);
}

function matterFileQATone(
  status: MatterFileQAResponse["status"],
): "success" | "brand" | "warning" | "neutral" {
  if (status === "answered") return "success";
  if (status === "partial_answer") return "brand";
  if (status === "error") return "warning";
  return "neutral";
}

function matterFileQAStateCopy(status: MatterFileQAResponse["status"]): string {
  switch (status) {
    case "answered":
      return "Answer prepared from uploaded matter document chunks.";
    case "partial_answer":
      return "Partial answer prepared from the available uploaded chunks.";
    case "insufficient_evidence":
      return "The uploaded chunks did not provide enough support for this question.";
    case "processing_required":
      return "Documents exist, but usable indexed chunks are not ready yet.";
    case "no_documents":
      return "Upload matter documents before asking the case file.";
    case "error":
      return "The request could not be completed.";
  }
}

function safeMatterFileText(value: string | null | undefined): string | null {
  const text = value?.trim();
  if (!text) return null;
  return FORBIDDEN_MATTER_FILE_QA_COPY.test(text) ? null : text;
}

function safeMatterFileLimitations(values: string[]): string[] {
  return values
    .map((value) => value.trim())
    .filter((value) => value && !FORBIDDEN_MATTER_FILE_QA_COPY.test(value))
    .slice(0, 5);
}

function safeMatterFileStructuredItems(
  values: MatterFileQAStructuredItem[],
): MatterFileQAStructuredItem[] {
  return values
    .filter(
      (item) =>
        !FORBIDDEN_MATTER_FILE_QA_COPY.test(item.label) &&
        !FORBIDDEN_MATTER_FILE_QA_COPY.test(item.value),
    )
    .slice(0, 12);
}

function matterFileSourceHref(matterId: string, attachmentId: string): string {
  return `/app/matters/${encodeURIComponent(matterId)}/documents/${encodeURIComponent(
    attachmentId,
  )}/view`;
}

function matterFileHistoryEntryToResponse(
  entry: MatterFileQAHistoryEntry,
): MatterFileQAResponse {
  const analysisLanguage = entry.analysis_language ?? "en";
  return {
    matter_id: entry.matter_id,
    question: entry.question,
    status: entry.answer_status,
    answer: entry.answer,
    analysis_language: analysisLanguage,
    local_language_analysis: entry.local_language_analysis,
    translation_status: entry.translation_status ?? "not_requested",
    translation_warning: entry.translation_warning,
    confidence: entry.confidence,
    sources: entry.sources,
    structured_items: entry.structured_items,
    limitations: entry.limitations,
    provider: "caseops-matter-file-qa-v1",
    generated_at: entry.created_at,
    model_run_id: entry.model_run_id,
    history_entry_id: entry.id,
  };
}

function matterFileLanguageLabel(value: MatterFileQAAnalysisLanguage): string {
  return (
    MATTER_FILE_QA_LANGUAGES.find((language) => language.value === value)?.label ?? value
  );
}

function compactDateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("en-IN", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function AskCaseFileSection({
  matterId,
  attachments,
  canAsk,
}: {
  matterId: string;
  attachments: WorkspaceAttachment[];
  canAsk: boolean;
}) {
  const queryClient = useQueryClient();
  const [question, setQuestion] = useState("");
  const [answerMode, setAnswerMode] = useState<MatterFileQAAnswerMode>("direct");
  const [analysisLanguage, setAnalysisLanguage] =
    useState<MatterFileQAAnalysisLanguage>("en");
  const [result, setResult] = useState<MatterFileQAResponse | null>(null);
  const knownAttachmentIds = useMemo(
    () => new Set(attachments.map((attachment) => attachment.id)),
    [attachments],
  );
  const trimmedQuestion = question.trim();
  const canSubmit = canAsk && trimmedQuestion.length >= 4;

  const qaMutation = useMutation({
    mutationFn: () =>
      askMatterFileQuestion({
        matterId,
        question: trimmedQuestion,
        answerMode,
        analysisLanguage,
        limit: 8,
      }),
    onMutate: () => setResult(null),
    onSuccess: async (response) => {
      setResult(response);
      await queryClient.invalidateQueries({
        queryKey: ["matters", matterId, "file-qa-history"],
      });
    },
  });
  const historyQuery = useQuery({
    queryKey: ["matters", matterId, "file-qa-history"],
    queryFn: () => fetchMatterFileQAHistory({ matterId }),
    enabled: Boolean(matterId && canAsk),
  });
  const exportMutation = useMutation({
    mutationFn: (entryId: string) => exportMatterFileQANote({ matterId, entryId }),
    onSuccess: async (response) => {
      await queryClient.invalidateQueries({
        queryKey: ["matters", matterId, "file-qa-history"],
      });
      toast.success(
        response.already_exported
          ? "Matter File Q&A note already exported."
          : "Matter File Q&A note exported.",
      );
    },
    onError: (err) => {
      toast.error(apiErrorMessage(err, "Could not export the Matter File Q&A note."));
    },
  });

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSubmit || qaMutation.isPending) return;
    qaMutation.mutate();
  }

  const visibleLimitations = result ? safeMatterFileLimitations(result.limitations) : [];
  const answerText = result ? safeMatterFileText(result.answer) : null;
  const localLanguageText = result
    ? safeMatterFileText(result.local_language_analysis)
    : null;
  const resultAnalysisLanguage = result?.analysis_language ?? "en";
  const structuredItems = result
    ? safeMatterFileStructuredItems(result.structured_items ?? [])
    : [];
  const historyEntries = historyQuery.data?.entries ?? [];

  function reopenHistoryEntry(entry: MatterFileQAHistoryEntry) {
    setQuestion(entry.question);
    setAnswerMode(entry.answer_mode);
    setAnalysisLanguage(entry.analysis_language ?? "en");
    setResult(matterFileHistoryEntryToResponse(entry));
  }

  return (
    <Card data-testid="matter-file-qa-section">
      <CardContent className="p-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone="brand">Ask case file</Badge>
              <Badge tone="neutral">Uploaded documents only</Badge>
            </div>
            <h2 className="mt-2 text-base font-semibold text-[var(--color-ink)]">
              Matter File Q&A
            </h2>
            <p className="mt-1 max-w-3xl text-sm text-[var(--color-mute)]">
              Answers use uploaded matter documents only and require lawyer review.
            </p>
          </div>
          {result ? (
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <Badge tone={matterFileQATone(result.status)}>
                {matterFileQAStatusLabel(result.status)}
              </Badge>
              <Badge tone="neutral">{compactLabel(result.confidence)}</Badge>
            </div>
          ) : null}
        </div>

        <form
          className="mt-4 grid gap-3 lg:grid-cols-[minmax(0,1fr)_13rem_12rem_auto] lg:items-end"
          onSubmit={handleSubmit}
        >
          <div>
            <Label htmlFor="matter-file-qa-question">Question</Label>
            <Textarea
              id="matter-file-qa-question"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="Ask what the uploaded record says about sections, allegations, evidence, or dates."
              className="mt-1.5 min-h-20"
              maxLength={800}
              data-testid="matter-file-qa-question"
            />
          </div>
          <div>
            <Label htmlFor="matter-file-qa-mode">Answer mode</Label>
            <select
              id="matter-file-qa-mode"
              className={`${selectClassName()} mt-1.5`}
              value={answerMode}
              onChange={(event) =>
                setAnswerMode(event.target.value as MatterFileQAAnswerMode)
              }
              data-testid="matter-file-qa-mode"
            >
              {MATTER_FILE_QA_MODES.map((mode) => (
                <option key={mode.value} value={mode.value}>
                  {mode.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <Label htmlFor="matter-file-qa-language">Analysis language</Label>
            <select
              id="matter-file-qa-language"
              className={`${selectClassName()} mt-1.5`}
              value={analysisLanguage}
              onChange={(event) =>
                setAnalysisLanguage(event.target.value as MatterFileQAAnalysisLanguage)
              }
              data-testid="matter-file-qa-language"
            >
              {MATTER_FILE_QA_LANGUAGES.map((language) => (
                <option key={language.value} value={language.value}>
                  {language.label}
                </option>
              ))}
            </select>
          </div>
          <Button
            type="submit"
            size="md"
            disabled={!canSubmit || qaMutation.isPending}
            data-testid="matter-file-qa-submit"
          >
            {qaMutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            ) : (
              <Send className="h-4 w-4" aria-hidden />
            )}
            Ask
          </Button>
        </form>

        {!canAsk ? (
          <div
            className="mt-3 rounded-md border border-[var(--color-line)] bg-[var(--color-bg-2)] px-3 py-2 text-sm text-[var(--color-mute)]"
            data-testid="matter-file-qa-disabled"
          >
            AI generation access is required to ask the case file.
          </div>
        ) : null}

        <div className="mt-4" aria-live="polite">
          {qaMutation.isPending ? (
            <div
              className="flex items-center gap-2 rounded-md border border-[var(--color-line)] px-3 py-3 text-sm text-[var(--color-mute)]"
              data-testid="matter-file-qa-loading"
            >
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              Reading indexed matter chunks...
            </div>
          ) : qaMutation.isError ? (
            <div
              className="flex items-start gap-2 rounded-md border border-[var(--color-line)] bg-[var(--color-bg-2)] px-3 py-3 text-sm text-[var(--color-mute)]"
              data-testid="matter-file-qa-error"
            >
              <AlertTriangle className="mt-0.5 h-4 w-4 text-[var(--color-warning-500)]" aria-hidden />
              <span>{apiErrorMessage(qaMutation.error, "Could not ask the case file.")}</span>
            </div>
          ) : result ? (
            <div
              className="rounded-md border border-[var(--color-line)]"
              data-testid={`matter-file-qa-result-${result.status}`}
            >
              <div className="flex flex-col gap-2 border-b border-[var(--color-line)] px-3 py-2 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex items-center gap-2 text-sm font-semibold text-[var(--color-ink)]">
                  <MessageSquareText className="h-4 w-4 text-[var(--color-mute)]" aria-hidden />
                  {matterFileQAStatusLabel(result.status)}
                </div>
                <div className="flex flex-wrap gap-1.5">
                  <Badge tone={matterFileQATone(result.status)}>
                    {matterFileQAStatusLabel(result.status)}
                  </Badge>
                  <Badge tone="neutral">{compactLabel(result.confidence)}</Badge>
                  {resultAnalysisLanguage !== "en" ? (
                    <Badge tone="neutral">
                      {matterFileLanguageLabel(resultAnalysisLanguage)}
                    </Badge>
                  ) : null}
                  {result.model_run_id ? <Badge tone="neutral">Model run recorded</Badge> : null}
                  {result.history_entry_id ? (
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      disabled={exportMutation.isPending}
                      onClick={() => exportMutation.mutate(result.history_entry_id ?? "")}
                      data-testid="matter-file-qa-export-current"
                    >
                      {exportMutation.isPending ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                      ) : (
                        <Save className="h-3.5 w-3.5" aria-hidden />
                      )}
                      Export note
                    </Button>
                  ) : null}
                </div>
              </div>
              <div className="px-3 py-3">
                <p className="text-sm text-[var(--color-mute)]">
                  {matterFileQAStateCopy(result.status)}
                </p>
                {answerText ? (
                  <div className="mt-3 max-w-4xl">
                    {resultAnalysisLanguage !== "en" ? (
                      <div className="mb-1 text-xs font-medium uppercase tracking-[0.08em] text-[var(--color-mute)]">
                        English authoritative answer
                      </div>
                    ) : null}
                    <p className="text-sm leading-6 text-[var(--color-ink)]">
                      {answerText}
                    </p>
                  </div>
                ) : result.status === "answered" || result.status === "partial_answer" ? (
                  <p className="mt-3 text-sm text-[var(--color-mute)]">
                    The answer was withheld because it did not meet Matter File Q&A display rules.
                  </p>
                ) : null}

                {localLanguageText ? (
                  <div
                    className="mt-3 max-w-4xl rounded-md border border-[var(--color-line-2)] bg-[var(--color-bg-2)] px-3 py-2"
                    data-testid="matter-file-qa-local-language-analysis"
                  >
                    <div className="text-xs font-medium uppercase tracking-[0.08em] text-[var(--color-mute)]">
                      {matterFileLanguageLabel(resultAnalysisLanguage)} translation aid
                    </div>
                    <p className="mt-1 text-sm leading-6 text-[var(--color-ink)]">
                      {localLanguageText}
                    </p>
                  </div>
                ) : result.translation_warning ? (
                  <div
                    className="mt-3 rounded-md border border-[var(--color-line)] bg-[var(--color-bg-2)] px-3 py-2 text-sm text-[var(--color-mute)]"
                    data-testid="matter-file-qa-translation-warning"
                  >
                    {result.translation_warning}
                  </div>
                ) : null}

                {visibleLimitations.length > 0 ? (
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {visibleLimitations.map((limitation) => (
                      <Badge key={limitation} tone="neutral">
                        {limitation}
                      </Badge>
                    ))}
                  </div>
                ) : null}

                {structuredItems.length > 0 ? (
                  <div
                    className="mt-4 grid gap-2"
                    data-testid="matter-file-qa-structured-items"
                  >
                    {structuredItems.map((item, index) => (
                      <article
                        key={`${item.item_type}-${item.label}-${index}`}
                        className="rounded-md border border-[var(--color-line-2)] px-3 py-2"
                        data-testid={`matter-file-qa-structured-item-${item.item_type}`}
                      >
                        <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                          <div>
                            <div className="text-xs font-medium uppercase tracking-[0.08em] text-[var(--color-mute)]">
                              {compactLabel(item.item_type)}
                            </div>
                            <div className="mt-1 text-sm font-semibold text-[var(--color-ink)]">
                              {item.label}
                            </div>
                          </div>
                          <div className="flex flex-wrap gap-1.5">
                            <Badge tone="neutral">{compactLabel(item.confidence)}</Badge>
                            <Badge tone="neutral">
                              {compactLabel(item.evidence_status)}
                            </Badge>
                          </div>
                        </div>
                        <p className="mt-2 text-sm leading-6 text-[var(--color-ink)]">
                          {item.value}
                        </p>
                        <div className="mt-2 flex flex-wrap gap-1.5">
                          {item.source_ids.map((sourceId) => (
                            <Badge key={sourceId} tone="neutral">
                              Source {sourceId.replace(/^src_/, "")}
                            </Badge>
                          ))}
                        </div>
                      </article>
                    ))}
                  </div>
                ) : null}

                {result.sources.length > 0 ? (
                  <div className="mt-4 grid gap-2" data-testid="matter-file-qa-sources">
                    {result.sources.map((source) => {
                      const isKnownAttachment = knownAttachmentIds.has(source.attachment_id);

                      return (
                        <article
                          key={`${source.source_id}-${source.chunk_id}`}
                          className="rounded-md border border-[var(--color-line-2)] px-3 py-2"
                        >
                          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                            {isKnownAttachment ? (
                              <Link
                                href={matterFileSourceHref(matterId, source.attachment_id)}
                                className="text-sm font-medium text-[var(--color-ink)] hover:underline"
                                data-testid={`matter-file-qa-source-${source.source_id}`}
                              >
                                {source.attachment_name}
                              </Link>
                            ) : (
                              <span
                                className="text-sm font-medium text-[var(--color-ink)]"
                                data-testid={`matter-file-qa-source-${source.source_id}`}
                              >
                                {source.attachment_name}
                              </span>
                            )}
                            <div className="flex flex-wrap gap-1.5">
                              <Badge tone="neutral">Chunk {source.chunk_index + 1}</Badge>
                              {source.page_number ? (
                                <Badge tone="neutral">Page {source.page_number}</Badge>
                              ) : null}
                              <Badge tone="neutral">Score {source.score}</Badge>
                              {!isKnownAttachment ? (
                                <Badge tone="neutral">Source link unavailable</Badge>
                              ) : null}
                            </div>
                          </div>
                          <p className="mt-2 text-xs leading-5 text-[var(--color-mute)]">
                            {source.snippet}
                          </p>
                        </article>
                      );
                    })}
                  </div>
                ) : null}
              </div>
            </div>
          ) : (
            <div
              className="rounded-md border border-[var(--color-line)] bg-[var(--color-bg-2)] px-3 py-3 text-sm text-[var(--color-mute)]"
              data-testid="matter-file-qa-empty"
            >
              Ask a question about uploaded matter documents.
            </div>
          )}
        </div>

        <div
          className="mt-4 border-t border-[var(--color-line)] pt-4"
          data-testid="matter-file-qa-history"
        >
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h3 className="text-sm font-semibold text-[var(--color-ink)]">
                Recent Q&A
              </h3>
              <p className="mt-0.5 text-xs text-[var(--color-mute)]">
                Saved answers use bounded snippets from uploaded matter documents.
              </p>
            </div>
            {historyQuery.isFetching ? (
              <span
                className="inline-flex items-center gap-1.5 text-xs text-[var(--color-mute)]"
                data-testid="matter-file-qa-history-loading"
              >
                <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                Loading history
              </span>
            ) : null}
          </div>

          {historyQuery.isError ? (
            <div
              className="mt-3 rounded-md border border-[var(--color-line)] bg-[var(--color-bg-2)] px-3 py-2 text-sm text-[var(--color-mute)]"
              data-testid="matter-file-qa-history-error"
            >
              {apiErrorMessage(historyQuery.error, "Could not load Matter File Q&A history.")}
            </div>
          ) : historyEntries.length > 0 ? (
            <div className="mt-3 grid gap-2">
              {historyEntries.map((entry) => {
                const safeAnswer = safeMatterFileText(entry.answer);
                const safeSources = entry.sources.slice(0, 3);

                return (
                  <article
                    key={entry.id}
                    className="rounded-md border border-[var(--color-line-2)] px-3 py-2"
                    data-testid="matter-file-qa-history-entry"
                  >
                    <div className="flex flex-col gap-2 lg:flex-row lg:items-start lg:justify-between">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-1.5">
                          <Badge tone={matterFileQATone(entry.answer_status)}>
                            {matterFileQAStatusLabel(entry.answer_status)}
                          </Badge>
                          <Badge tone="neutral">{compactLabel(entry.answer_mode)}</Badge>
                          <Badge tone="neutral">{compactDateTime(entry.created_at)}</Badge>
                          {entry.exported_note_id ? (
                            <Badge tone="neutral">Exported</Badge>
                          ) : null}
                        </div>
                        <p className="mt-2 text-sm font-medium text-[var(--color-ink)]">
                          {entry.question}
                        </p>
                        {safeAnswer ? (
                          <p className="mt-1 line-clamp-2 text-sm leading-5 text-[var(--color-mute)]">
                            {safeAnswer}
                          </p>
                        ) : (
                          <p className="mt-1 text-sm text-[var(--color-mute)]">
                            {matterFileQAStateCopy(entry.answer_status)}
                          </p>
                        )}
                      </div>
                      <div className="flex shrink-0 flex-wrap gap-2">
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          onClick={() => reopenHistoryEntry(entry)}
                          data-testid={`matter-file-qa-history-reopen-${entry.id}`}
                        >
                          Reopen
                        </Button>
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          disabled={exportMutation.isPending}
                          onClick={() => exportMutation.mutate(entry.id)}
                          data-testid={`matter-file-qa-history-export-${entry.id}`}
                        >
                          {exportMutation.isPending ? (
                            <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                          ) : (
                            <Save className="h-3.5 w-3.5" aria-hidden />
                          )}
                          Export note
                        </Button>
                      </div>
                    </div>

                    {safeSources.length > 0 ? (
                      <div className="mt-3 grid gap-1.5">
                        {safeSources.map((source) => {
                          const isKnownAttachment = knownAttachmentIds.has(
                            source.attachment_id,
                          );

                          return (
                            <div
                              key={`${entry.id}-${source.source_id}-${source.chunk_id}`}
                              className="rounded-md bg-[var(--color-bg-2)] px-2 py-1.5"
                            >
                              <div className="flex flex-wrap items-center gap-1.5 text-xs">
                                {isKnownAttachment ? (
                                  <Link
                                    href={matterFileSourceHref(
                                      matterId,
                                      source.attachment_id,
                                    )}
                                    className="font-medium text-[var(--color-ink)] hover:underline"
                                    data-testid={`matter-file-qa-history-source-${source.source_id}`}
                                  >
                                    {source.attachment_name}
                                  </Link>
                                ) : (
                                  <span
                                    className="font-medium text-[var(--color-ink)]"
                                    data-testid={`matter-file-qa-history-source-${source.source_id}`}
                                  >
                                    {source.attachment_name}
                                  </span>
                                )}
                                <Badge tone="neutral">Chunk {source.chunk_index + 1}</Badge>
                                {!isKnownAttachment ? (
                                  <Badge tone="neutral">Source link unavailable</Badge>
                                ) : null}
                              </div>
                              <p className="mt-1 text-xs leading-5 text-[var(--color-mute)]">
                                {source.snippet}
                              </p>
                            </div>
                          );
                        })}
                      </div>
                    ) : null}
                  </article>
                );
              })}
            </div>
          ) : (
            <div
              className="mt-3 rounded-md border border-[var(--color-line)] bg-[var(--color-bg-2)] px-3 py-2 text-sm text-[var(--color-mute)]"
              data-testid="matter-file-qa-history-empty"
            >
              No saved Matter File Q&A yet.
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function AffidavitIntelligenceSection({
  matterId,
  attachments,
  data,
  isLoading,
  error,
  canAnalyze,
  analysisPendingId,
  isAnalyzePending,
  onAnalyze,
  onRetry,
}: {
  matterId: string;
  attachments: WorkspaceAttachment[];
  data?: AffidavitIntelligenceResponse;
  isLoading: boolean;
  error: Error | null;
  canAnalyze: boolean;
  analysisPendingId: string | null;
  isAnalyzePending: boolean;
  onAnalyze: (attachmentId: string) => void;
  onRetry: () => void;
}) {
  const affidavitAttachments = attachments.filter((attachment) =>
    AFFIDAVIT_DOCUMENT_TYPES.has(attachment.document_type ?? ""),
  );
  const latestRun = data?.latest_run ?? null;
  const selectedAttachment = latestRun
    ? attachments.find((attachment) => attachment.id === latestRun.attachment_id)
    : affidavitAttachments[0] ?? null;
  const statements = latestRun?.statements ?? [];
  const questions = latestRun?.questions ?? [];
  const gaps = statements.filter((statement) =>
    ["evidence_gap", "contradiction"].includes(statement.statement_type),
  );
  const questionsByCategory = questions.reduce<Record<string, AffidavitQuestion[]>>(
    (groups, question) => {
      groups[question.category] = [...(groups[question.category] ?? []), question];
      return groups;
    },
    {},
  );

  return (
    <Card data-testid="affidavit-intelligence-section">
      <CardContent className="p-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone="brand">Affidavit intelligence</Badge>
              {latestRun ? (
                <Badge tone={latestRun.status === "completed" ? "neutral" : "warning"}>
                  {compactLabel(latestRun.status)}
                </Badge>
              ) : null}
              <Badge tone="neutral">Review required</Badge>
            </div>
            <h2 className="mt-2 text-base font-semibold text-[var(--color-ink)]">
              Source-grounded hearing prep
            </h2>
            <p className="mt-1 max-w-3xl text-sm text-[var(--color-mute)]">
              {data?.disclaimer ??
                "Affidavit intelligence is source-backed hearing-preparation decision support. It is not legal advice."}
            </p>
          </div>
          <div className="text-xs text-[var(--color-mute)]">
            {latestRun ? (
              <>
                Generated {dateLabel(latestRun.created_at)} · {statements.length} statements ·{" "}
                {questions.length} questions
              </>
            ) : (
              "No analysis run"
            )}
          </div>
        </div>

        <div className="mt-4 grid gap-4 xl:grid-cols-[0.85fr_1.15fr]">
          <div className="rounded-md border border-[var(--color-line)]">
            <div className="flex items-center justify-between border-b border-[var(--color-line)] px-3 py-2">
              <div className="flex items-center gap-2 text-sm font-semibold text-[var(--color-ink)]">
                <FileText className="h-4 w-4 text-[var(--color-mute)]" aria-hidden />
                Marked affidavits
              </div>
              <Badge tone="neutral">{affidavitAttachments.length}</Badge>
            </div>
            {affidavitAttachments.length === 0 ? (
              <div
                className="px-3 py-4 text-sm text-[var(--color-mute)]"
                data-testid="affidavit-intelligence-empty"
              >
                Mark a document as chief affidavit, affidavit, or counter affidavit.
              </div>
            ) : (
              <div className="divide-y divide-[var(--color-line-2)]">
                {affidavitAttachments.map((attachment) => {
                  const isPending =
                    isAnalyzePending && analysisPendingId === attachment.id;
                  return (
                    <div
                      key={attachment.id}
                      className="flex flex-col gap-2 px-3 py-3 sm:flex-row sm:items-center sm:justify-between"
                    >
                      <div className="min-w-0">
                        <Link
                          href={affidavitViewHref(matterId, attachment.id)}
                          className="truncate text-sm font-medium text-[var(--color-ink)] hover:underline"
                          data-testid={`affidavit-source-link-${attachment.id}`}
                        >
                          {attachment.original_filename ?? attachment.filename ?? "Affidavit"}
                        </Link>
                        <div className="mt-1 flex flex-wrap gap-1.5">
                          <Badge tone="neutral">
                            {labelFor(DOCUMENT_TYPE_OPTIONS, attachment.document_type)}
                          </Badge>
                          <StatusBadge status={attachment.processing_status ?? "unknown"} />
                        </div>
                      </div>
                      {canAnalyze ? (
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          disabled={isPending}
                          onClick={() => onAnalyze(attachment.id)}
                          data-testid={`affidavit-analyze-${attachment.id}`}
                        >
                          {isPending ? (
                            <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                          ) : (
                            <ClipboardList className="h-4 w-4" aria-hidden />
                          )}
                          Analyze
                        </Button>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          <div className="rounded-md border border-[var(--color-line)]">
            <div className="flex items-center justify-between border-b border-[var(--color-line)] px-3 py-2">
              <div className="flex items-center gap-2 text-sm font-semibold text-[var(--color-ink)]">
                <ClipboardList className="h-4 w-4 text-[var(--color-mute)]" aria-hidden />
                Latest analysis
              </div>
              {selectedAttachment ? (
                <Button
                  variant="ghost"
                  size="sm"
                  href={affidavitViewHref(matterId, selectedAttachment.id)}
                >
                  <Eye className="h-4 w-4" aria-hidden />
                  Source
                </Button>
              ) : null}
            </div>

            {isLoading ? (
              <div
                className="flex items-center gap-2 px-3 py-4 text-sm text-[var(--color-mute)]"
                data-testid="affidavit-intelligence-loading"
              >
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                Loading affidavit intelligence...
              </div>
            ) : error ? (
              <div
                className="flex items-start justify-between gap-3 px-3 py-4"
                data-testid="affidavit-intelligence-error"
              >
                <div className="flex gap-2 text-sm text-[var(--color-mute)]">
                  <AlertTriangle className="mt-0.5 h-4 w-4 text-[var(--color-warning-500)]" aria-hidden />
                  <span>{apiErrorMessage(error, "Could not load affidavit intelligence.")}</span>
                </div>
                <Button type="button" variant="outline" size="sm" onClick={onRetry}>
                  Retry
                </Button>
              </div>
            ) : latestRun ? (
              <div className="divide-y divide-[var(--color-line-2)]">
                {latestRun.status !== "completed" ? (
                  <div
                    className="px-3 py-3 text-sm text-[var(--color-mute)]"
                    data-testid="affidavit-insufficient-state"
                  >
                    Missing data:{" "}
                    {latestRun.missing_data.length > 0
                      ? latestRun.missing_data.join(", ")
                      : "detectable affidavit statements"}
                  </div>
                ) : null}
                <AffidavitStatementsList statements={statements} />
                <AffidavitGapList gaps={gaps} />
                <AffidavitQuestionGroups groups={questionsByCategory} />
              </div>
            ) : (
              <div className="px-3 py-4 text-sm text-[var(--color-mute)]">
                No affidavit analysis has been generated for this matter.
              </div>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function AffidavitStatementsList({
  statements,
}: {
  statements: AffidavitStatement[];
}) {
  if (statements.length === 0) {
    return (
      <div className="px-3 py-3 text-sm text-[var(--color-mute)]">
        No extracted statements are available.
      </div>
    );
  }
  return (
    <section className="px-3 py-3" data-testid="affidavit-statements">
      <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-[var(--color-ink)]">
        <ClipboardList className="h-4 w-4 text-[var(--color-mute)]" aria-hidden />
        Extracted statements
      </div>
      <div className="grid gap-2">
        {statements.slice(0, 6).map((statement) => (
          <div
            key={statement.id}
            className="rounded-md border border-[var(--color-line-2)] px-3 py-2"
          >
            <div className="flex flex-wrap items-center gap-1.5">
              <Badge tone="neutral">{compactLabel(statement.statement_type)}</Badge>
              <Badge tone={statement.confidence_label === "low" ? "warning" : "neutral"}>
                {compactLabel(statement.confidence_label)}
              </Badge>
              {statement.review_status === "review_required" ? (
                <Badge tone="warning">Review required</Badge>
              ) : null}
            </div>
            <p className="mt-2 text-sm text-[var(--color-ink)]">
              {statement.statement_text}
            </p>
            <blockquote className="mt-2 border-l-2 border-[var(--color-line)] pl-3 text-xs text-[var(--color-mute)]">
              {statement.source_quote}
            </blockquote>
          </div>
        ))}
      </div>
    </section>
  );
}

function AffidavitGapList({ gaps }: { gaps: AffidavitStatement[] }) {
  if (gaps.length === 0) return null;
  return (
    <section className="px-3 py-3" data-testid="affidavit-gaps">
      <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-[var(--color-ink)]">
        <AlertTriangle className="h-4 w-4 text-[var(--color-warning-500)]" aria-hidden />
        Evidence gaps and contradictions
      </div>
      <div className="grid gap-2">
        {gaps.slice(0, 4).map((gap) => (
          <div
            key={gap.id}
            className="rounded-md border border-[var(--color-line-2)] px-3 py-2 text-sm"
          >
            <div className="flex flex-wrap items-center gap-1.5">
              <Badge tone="warning">{compactLabel(gap.statement_type)}</Badge>
              <Badge tone="warning">Review required</Badge>
            </div>
            <p className="mt-2 text-[var(--color-ink)]">{gap.statement_text}</p>
            <p className="mt-1 text-xs text-[var(--color-mute)]">{gap.source_quote}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

function AffidavitQuestionGroups({
  groups,
}: {
  groups: Record<string, AffidavitQuestion[]>;
}) {
  const entries = Object.entries(groups);
  if (entries.length === 0) {
    return (
      <div className="px-3 py-3 text-sm text-[var(--color-mute)]">
        No cross-examination questions are available.
      </div>
    );
  }
  return (
    <section className="px-3 py-3" data-testid="affidavit-question-bank">
      <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-[var(--color-ink)]">
        <HelpCircle className="h-4 w-4 text-[var(--color-mute)]" aria-hidden />
        Cross-examination question bank
      </div>
      <div className="grid gap-3">
        {entries.map(([category, questions]) => (
          <div key={category}>
            <div className="mb-1 text-xs font-semibold uppercase tracking-[0.06em] text-[var(--color-mute)]">
              {compactLabel(category)}
            </div>
            <div className="grid gap-2">
              {questions.map((question) => (
                <article
                  key={question.id}
                  className="rounded-md border border-[var(--color-line-2)] px-3 py-2"
                >
                  <div className="flex flex-wrap items-center gap-1.5">
                    <Badge tone={question.confidence_label === "low" ? "warning" : "neutral"}>
                      {compactLabel(question.confidence_label)}
                    </Badge>
                    {question.review_required ? (
                      <Badge tone="warning">Review required</Badge>
                    ) : null}
                  </div>
                  <p className="mt-2 text-sm font-medium text-[var(--color-ink)]">
                    {question.question_text}
                  </p>
                  <p className="mt-1 text-xs text-[var(--color-mute)]">{question.reason}</p>
                  <blockquote className="mt-2 border-l-2 border-[var(--color-line)] pl-3 text-xs text-[var(--color-mute)]">
                    {question.source_quote}
                  </blockquote>
                </article>
              ))}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
