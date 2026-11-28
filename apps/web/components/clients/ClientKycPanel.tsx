"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2,
  Download,
  Eye,
  FileText,
  Loader2,
  ShieldCheck,
  Trash2,
  Upload,
  XCircle,
} from "lucide-react";
import dynamic from "next/dynamic";
import { useCallback, useEffect, useId, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { IconButton } from "@/components/ui/IconButton";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { Skeleton } from "@/components/ui/Skeleton";
import { apiErrorMessage } from "@/lib/api/config";
import {
  fetchClientKycDocumentBlob,
  listClientKycDocuments,
  rejectClientKyc,
  removeClientKycDocument,
  submitClientKyc,
  uploadClientKycDocument,
  verifyClientKyc,
  type ClientKycDocument,
  type ClientKycDocumentList,
  type ClientRecord,
  type KycDocumentType,
} from "@/lib/api/endpoints";

// BUG-003 (Nov 27 2026): a KYC pack is the client's uploaded files. The
// submitter uploads PAN / masked Aadhaar / passport / address proof files; the
// reviewer opens each one, marks it reviewed, and only then can approve. The
// API enforces every rule (requirements, reviewed set, frozen states, and that
// this reviewer opened each named file); this panel mirrors it from the API's
// own list response, and unlocks a Reviewed tick only once the API has served
// the file to this reviewer.

// PDFs render with the same pdf.js viewer as Matter and contract documents:
// canvas, same-origin worker, no plugin frame. A blob: <iframe> is blocked by
// the app CSP (no frame-src blob:) and Chromium refuses its PDF viewer in any
// sandboxed frame, so an iframe could not be both sandboxed and visible.
const PDFViewer = dynamic(
  () => import("@/components/document/PDFViewer").then((m) => m.PDFViewer),
  { ssr: false, loading: () => <Skeleton className="h-64 w-full" /> },
);

const SUBMITTABLE = new Set(["not_required", "required", "requested", "rejected", "expired"]);
const REVIEWABLE = new Set(["submitted", "under_review"]);

type KycPanelClient = Pick<
  ClientRecord,
  | "id"
  | "kyc_status"
  | "kyc_submitted_at"
  | "kyc_verified_at"
  | "kyc_rejection_reason"
  | "kyc_documents"
>;

function formatLocal(iso: string | null | undefined): string {
  return iso
    ? new Date(iso).toLocaleString(undefined, {
        day: "2-digit",
        month: "short",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "—";
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function statusTone(status: string): "success" | "warning" | "brand" | "neutral" {
  if (status === "verified") return "success";
  if (status === "rejected" || status === "expired" || status === "required") return "warning";
  if (REVIEWABLE.has(status) || status === "requested") return "brand";
  return "neutral";
}

export function ClientKycPanel({
  client,
  canSubmit,
  canReview,
}: {
  client: KycPanelClient;
  canSubmit: boolean;
  canReview: boolean;
}) {
  const clientId = client.id;
  const queryClient = useQueryClient();
  const canRead = canSubmit || canReview;
  const documentsKey = ["clients", clientId, "kyc-documents"] as const;
  const docsQuery = useQuery({
    queryKey: documentsKey,
    queryFn: () => listClientKycDocuments(clientId),
    enabled: canRead,
  });
  const [showPack, setShowPack] = useState(false);
  const [showReject, setShowReject] = useState(false);
  const [rejectReason, setRejectReason] = useState("");
  const [openedIds, setOpenedIds] = useState<Set<string>>(new Set());
  const [reviewedIds, setReviewedIds] = useState<Set<string>>(new Set());
  const [previewId, setPreviewId] = useState<string | null>(null);
  const markOpened = useCallback(
    (id: string) => setOpenedIds((current) => (current.has(id) ? current : new Set(current).add(id))),
    [],
  );
  // A new submission is a new review: earlier opens and ticks do not carry over.
  const cycle = `${client.kyc_status}:${client.kyc_submitted_at ?? ""}`;
  const [reviewCycle, setReviewCycle] = useState(cycle);
  if (reviewCycle !== cycle) {
    setReviewCycle(cycle);
    setOpenedIds(new Set());
    setReviewedIds(new Set());
    setPreviewId(null);
  }

  const status = client.kyc_status;
  const list = docsQuery.data;
  const documents = list?.documents ?? [];
  const currentIds = new Set(documents.map((d) => d.id));
  // A reviewer's ticks only count for files still in the current pack.
  const reviewedCurrent = documents.filter((d) => reviewedIds.has(d.id)).map((d) => d.id);

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["clients"] });
  };

  const submitMutation = useMutation({
    mutationFn: () => submitClientKyc({ clientId, documents: [] }),
    onSuccess: async () => {
      toast.success("KYC submitted for review.");
      setShowPack(false);
      await refresh();
    },
    onError: (err) => toast.error(apiErrorMessage(err, "Could not submit KYC.")),
  });
  const verifyMutation = useMutation({
    mutationFn: () => verifyClientKyc({ clientId, reviewedDocumentIds: reviewedCurrent }),
    onSuccess: async () => {
      toast.success("KYC verified.");
      await refresh();
    },
    onError: async (err) => {
      toast.error(apiErrorMessage(err, "Could not verify KYC."));
      await queryClient.invalidateQueries({ queryKey: documentsKey });
    },
  });
  const rejectMutation = useMutation({
    mutationFn: (reason: string) =>
      rejectClientKyc({ clientId, reason, reviewedDocumentIds: reviewedCurrent }),
    onSuccess: async () => {
      toast.success("KYC rejected.");
      setShowReject(false);
      setRejectReason("");
      await refresh();
    },
    onError: (err) => toast.error(apiErrorMessage(err, "Could not reject KYC.")),
  });
  const removeMutation = useMutation({
    mutationFn: (documentId: string) => removeClientKycDocument({ clientId, documentId }),
    onSuccess: async () => {
      toast.success("Document removed from the KYC pack.");
      await queryClient.invalidateQueries({ queryKey: documentsKey });
    },
    onError: (err) => toast.error(apiErrorMessage(err, "Could not remove the document.")),
  });

  const missing = (list?.requirements ?? []).filter((r) => !r.satisfied);
  const submitBlocked = !list
    ? "Loading the uploaded documents."
    : missing.length > 0
      ? `Upload ${missing.map((r) => r.label).join(" and ")} before submitting.`
      : null;
  const unreviewed = documents.filter((d) => !reviewedIds.has(d.id));
  const approveBlocked = !list
    ? "Loading the uploaded documents."
    : missing.length > 0
      ? `Approval needs ${missing.map((r) => r.label).join(" and ")}. Reject the pack with a reason so the files can be uploaded.`
      : unreviewed.length > 0
        ? `Open and mark every document reviewed before approving (${unreviewed.length} left).`
        : null;

  return (
    <Card data-testid="kyc-panel">
      <CardHeader>
        <CardTitle as="h2" className="text-base">
          KYC verification
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Badge tone={statusTone(status)}>{status.replace("_", " ")}</Badge>
            {status === "verified" ? (
              <ShieldCheck className="h-4 w-4 text-[var(--color-brand-600)]" aria-hidden />
            ) : null}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {canSubmit && list?.upload_allowed && (SUBMITTABLE.has(status) || status === "submitted") ? (
              <Button
                type="button"
                size="sm"
                variant={showPack ? "ghost" : "primary"}
                onClick={() => setShowPack((s) => !s)}
                aria-expanded={showPack}
                aria-controls="kyc-pack-form"
                data-testid="kyc-submit-toggle"
              >
                <Upload className="h-4 w-4" aria-hidden />
                {showPack
                  ? "Close"
                  : status === "rejected"
                    ? "Re-submit verification"
                    : status === "submitted"
                      ? "Add documents"
                      : "Submit KYC"}
              </Button>
            ) : null}
            {canReview && REVIEWABLE.has(status) ? (
              <>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => setShowReject((s) => !s)}
                  data-testid="kyc-reject-toggle"
                >
                  <XCircle className="h-4 w-4" aria-hidden /> Reject
                </Button>
                <Button
                  type="button"
                  size="sm"
                  disabled={Boolean(approveBlocked) || verifyMutation.isPending}
                  aria-describedby={approveBlocked ? "kyc-verify-blocked" : undefined}
                  onClick={() => verifyMutation.mutate()}
                  data-testid="kyc-verify"
                >
                  <CheckCircle2 className="h-4 w-4" aria-hidden /> Approve
                </Button>
              </>
            ) : null}
          </div>
        </div>
        {canReview && REVIEWABLE.has(status) && verifyMutation.isError ? (
          <p className="text-xs text-[var(--color-danger-600)]" role="alert" data-testid="kyc-verify-error">
            {apiErrorMessage(verifyMutation.error, "Could not verify KYC.")}
          </p>
        ) : null}
        {canReview && REVIEWABLE.has(status) && approveBlocked ? (
          <p
            id="kyc-verify-blocked"
            className="text-xs text-[var(--color-mute)]"
            data-testid="kyc-verify-blocked"
          >
            {approveBlocked}
          </p>
        ) : null}

        {client.kyc_submitted_at ? (
          <div className="grid gap-2 text-xs text-[var(--color-mute)] sm:grid-cols-2">
            <div>
              <span className="font-medium text-[var(--color-ink)]">Submitted</span>
              {" — "}
              {formatLocal(client.kyc_submitted_at)}
            </div>
            {client.kyc_verified_at ? (
              <div>
                <span className="font-medium text-[var(--color-ink)]">Reviewed</span>
                {" — "}
                {formatLocal(client.kyc_verified_at)}
              </div>
            ) : null}
          </div>
        ) : null}

        {status === "rejected" && client.kyc_rejection_reason ? (
          <div className="rounded-md border border-[var(--color-warning-500)]/40 bg-[var(--color-warning-500)]/10 p-3 text-xs">
            <div className="font-medium text-[var(--color-ink)]">Rejection reason</div>
            <p className="mt-1 whitespace-pre-wrap text-[var(--color-ink-2)]">
              {client.kyc_rejection_reason}
            </p>
          </div>
        ) : null}

        {!canRead ? (
          <p className="text-xs text-[var(--color-mute)]">
            Your role can see the KYC status but not the identity documents.
          </p>
        ) : docsQuery.isPending ? (
          <Skeleton className="h-24 w-full" />
        ) : docsQuery.isError ? (
          <p className="text-xs text-[var(--color-mute)]" role="alert">
            {apiErrorMessage(docsQuery.error, "Could not load the KYC documents.")}
          </p>
        ) : list ? (
          <>
            <RequirementList list={list} />
            <DocumentTable
              clientId={clientId}
              list={list}
              canRemove={canSubmit && list.upload_allowed}
              removingId={removeMutation.isPending ? removeMutation.variables ?? null : null}
              onRemove={(id) => removeMutation.mutate(id)}
              reviewing={canReview && REVIEWABLE.has(status)}
              openedIds={openedIds}
              reviewedIds={reviewedIds}
              previewId={previewId}
              onPreview={(id) => setPreviewId((current) => (current === id ? null : id))}
              onOpened={markOpened}
              onReviewed={(id, reviewed) =>
                setReviewedIds((current) => {
                  const next = new Set(current);
                  if (reviewed) next.add(id);
                  else next.delete(id);
                  return next;
                })
              }
            />
            {previewId && currentIds.has(previewId) ? (
              <DocumentPreview
                clientId={clientId}
                document={documents.find((d) => d.id === previewId)!}
                onOpened={markOpened}
                onClose={() => setPreviewId(null)}
              />
            ) : null}
          </>
        ) : null}

        {client.kyc_documents.length > 0 ? (
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-wider text-[var(--color-mute)]">
              Checklist recorded with an earlier submission (names only, no files)
            </div>
            <ul className="mt-1 list-disc pl-5 text-xs text-[var(--color-ink-2)]">
              {client.kyc_documents.map((d, i) => (
                <li key={`${d.name}-${i}`}>
                  {d.name}
                  {d.note ? <span className="ml-1 text-[var(--color-mute)]">— {d.note}</span> : null}
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {showPack && list && canSubmit && list.upload_allowed ? (
          <div
            id="kyc-pack-form"
            className="flex flex-col gap-3 rounded-md border border-[var(--color-line)] bg-[var(--color-line-1)]/40 p-3"
          >
            <KycUploadForm
              list={list}
              upload={(input) => uploadClientKycDocument({ clientId, ...input })}
              onUploaded={async () => {
                await queryClient.invalidateQueries({ queryKey: documentsKey });
              }}
            />
            {SUBMITTABLE.has(status) ? (
              <div className="flex flex-col items-end gap-1 border-t border-[var(--color-line)] pt-3">
                <Button
                  type="button"
                  size="sm"
                  disabled={Boolean(submitBlocked) || submitMutation.isPending}
                  aria-describedby={submitBlocked ? "kyc-submit-blocked" : undefined}
                  onClick={() => submitMutation.mutate()}
                  data-testid="kyc-submit"
                >
                  {submitMutation.isPending ? (
                    <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                  ) : null}
                  Submit for review
                </Button>
                {submitBlocked ? (
                  <p
                    id="kyc-submit-blocked"
                    className="text-right text-xs text-[var(--color-mute)]"
                    data-testid="kyc-submit-blocked"
                  >
                    {submitBlocked}
                  </p>
                ) : null}
              </div>
            ) : null}
          </div>
        ) : null}

        {showReject ? (
          <form
            className="flex flex-col gap-2 rounded-md border border-[var(--color-line)] bg-[var(--color-line-1)]/40 p-3"
            onSubmit={(e) => {
              e.preventDefault();
              if (rejectReason.trim().length < 4) return;
              rejectMutation.mutate(rejectReason.trim());
            }}
          >
            <label className="flex flex-col gap-1 text-xs font-medium text-[var(--color-ink)]">
              Rejection reason (visible to the lawyer who submitted)
              <textarea
                value={rejectReason}
                onChange={(e) => setRejectReason(e.target.value)}
                rows={3}
                required
                placeholder="e.g. Address proof missing — please attach a recent utility bill."
                className="rounded-md border border-[var(--color-line)] px-2 py-1 text-sm"
                data-testid="kyc-reject-reason"
              />
            </label>
            <p className="text-xs text-[var(--color-mute)]">
              {reviewedCurrent.length} of {documents.length} documents marked reviewed will be
              recorded with this rejection.
            </p>
            {rejectMutation.isError ? (
              <p className="text-xs text-[var(--color-danger-600)]" role="alert" data-testid="kyc-reject-error">
                {apiErrorMessage(rejectMutation.error, "Could not reject KYC.")}
              </p>
            ) : null}
            <div className="flex justify-end gap-2">
              <Button type="button" variant="outline" size="sm" onClick={() => setShowReject(false)}>
                Cancel
              </Button>
              <Button
                type="submit"
                size="sm"
                disabled={rejectMutation.isPending || rejectReason.trim().length < 4}
                data-testid="kyc-reject"
              >
                Send rejection
              </Button>
            </div>
          </form>
        ) : null}
      </CardContent>
    </Card>
  );
}

export function RequirementList({ list }: { list: ClientKycDocumentList }) {
  return (
    <div>
      <div className="text-[10px] font-semibold uppercase tracking-wider text-[var(--color-mute)]">
        Required documents
      </div>
      <ul className="mt-1 flex flex-col gap-1 text-xs" data-testid="kyc-requirements">
        {list.requirements.map((r) => (
          <li key={r.key} className="flex items-center gap-2" data-testid={`kyc-requirement-${r.key}`}>
            {r.satisfied ? (
              <CheckCircle2 className="h-3.5 w-3.5 text-[var(--color-brand-600)]" aria-hidden />
            ) : (
              <XCircle className="h-3.5 w-3.5 text-[var(--color-mute)]" aria-hidden />
            )}
            <span className="text-[var(--color-ink-2)]">{r.label}</span>
            <span className="text-[var(--color-mute)]">{r.satisfied ? "on file" : "missing"}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function typeLabel(list: ClientKycDocumentList, doc: ClientKycDocument): string {
  const base = list.document_types.find((t) => t.value === doc.document_type)?.label ?? doc.document_type;
  return doc.label ? `${base}: ${doc.label}` : base;
}

function DocumentTable({
  clientId,
  list,
  canRemove,
  removingId,
  onRemove,
  reviewing,
  openedIds,
  reviewedIds,
  previewId,
  onPreview,
  onOpened,
  onReviewed,
}: {
  clientId: string;
  list: ClientKycDocumentList;
  canRemove: boolean;
  removingId: string | null;
  onRemove: (id: string) => void;
  reviewing: boolean;
  openedIds: Set<string>;
  reviewedIds: Set<string>;
  previewId: string | null;
  onPreview: (id: string) => void;
  onOpened: (id: string) => void;
  onReviewed: (id: string, reviewed: boolean) => void;
}) {
  const [downloading, setDownloading] = useState<string | null>(null);
  if (list.documents.length === 0) {
    return (
      <p className="text-xs text-[var(--color-mute)]" data-testid="kyc-documents-empty">
        {list.upload_allowed
          ? "No KYC documents uploaded yet. Upload the PAN card and a masked Aadhaar, passport or another address proof so a reviewer can check them."
          : "No KYC files are on record for this client; this verification predates file uploads."}
      </p>
    );
  }
  const download = async (doc: ClientKycDocument) => {
    setDownloading(doc.id);
    try {
      const blob = await fetchClientKycDocumentBlob({ clientId, documentId: doc.id });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = doc.original_filename;
      anchor.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      onOpened(doc.id);
    } catch (err) {
      toast.error(apiErrorMessage(err, "Could not download the document."));
    } finally {
      setDownloading(null);
    }
  };
  return (
    // A wrapping list, not a fixed-width table: a phone (393px) must show
    // every column without the page scrolling sideways.
    <ul
      className="flex min-w-0 flex-col text-xs"
      aria-label="Uploaded KYC documents"
      data-testid="kyc-documents"
    >
          {list.documents.map((doc) => {
            const label = typeLabel(list, doc);
            const opened = openedIds.has(doc.id);
            return (
              <li
                key={doc.id}
                className="grid min-w-0 grid-cols-1 gap-x-3 gap-y-1 border-t border-[var(--color-line)] py-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)_minmax(0,1fr)_auto_auto] sm:items-start"
                data-testid="kyc-document-row"
                data-document-id={doc.id}
                data-document-type={doc.document_type}
              >
                <div className="min-w-0 font-medium text-[var(--color-ink)]">{label}</div>
                <div className="min-w-0 text-[var(--color-ink-2)] [overflow-wrap:anywhere]">
                  <span className="inline-flex items-center gap-1">
                    <FileText className="h-3.5 w-3.5 shrink-0" aria-hidden />
                    {doc.original_filename}
                  </span>
                  <span className="ml-1 tabular text-[var(--color-mute)]">
                    {formatBytes(doc.size_bytes)}
                  </span>
                </div>
                <div className="min-w-0 text-[var(--color-mute)]">
                  {doc.uploaded_by_name ?? "—"}
                  <div className="tabular">{formatLocal(doc.created_at)}</div>
                </div>
                <div className="min-w-0">
                  {reviewing ? (
                    <label className="flex items-center gap-1.5 text-[var(--color-ink-2)]">
                      <input
                        type="checkbox"
                        checked={reviewedIds.has(doc.id)}
                        disabled={!opened}
                        title={opened ? undefined : "Open the document first"}
                        onChange={(e) => onReviewed(doc.id, e.target.checked)}
                        aria-label={`Reviewed ${label}`}
                        data-testid="kyc-document-reviewed"
                      />
                      Reviewed
                      {!opened ? (
                        <span className="text-[var(--color-mute)]">(open first)</span>
                      ) : null}
                    </label>
                  ) : doc.review_decision ? (
                    <Badge tone={doc.review_decision === "approved" ? "success" : "warning"}>
                      {doc.review_decision}
                    </Badge>
                  ) : (
                    <span className="text-[var(--color-mute)]">not reviewed</span>
                  )}
                </div>
                <div className="min-w-0">
                  <div className="flex flex-wrap gap-1 sm:justify-end">
                    {doc.previewable ? (
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        aria-pressed={previewId === doc.id}
                        aria-label={`Open ${label}`}
                        onClick={() => onPreview(doc.id)}
                        data-testid="kyc-document-open"
                      >
                        <Eye className="h-3.5 w-3.5" aria-hidden /> Open
                      </Button>
                    ) : null}
                    <IconButton
                      type="button"
                      size="sm"
                      variant="ghost"
                      label={`Download ${label}`}
                      disabled={downloading === doc.id}
                      onClick={() => void download(doc)}
                      data-testid="kyc-document-download"
                    >
                      <Download className="h-3.5 w-3.5" aria-hidden />
                    </IconButton>
                    {canRemove ? (
                      <IconButton
                        type="button"
                        size="sm"
                        variant="ghost"
                        label={`Remove ${label}`}
                        disabled={removingId === doc.id}
                        onClick={() => onRemove(doc.id)}
                        data-testid="kyc-document-remove"
                      >
                        <Trash2 className="h-3.5 w-3.5" aria-hidden />
                      </IconButton>
                    ) : null}
                  </div>
                </div>
              </li>
            );
          })}
    </ul>
  );
}

function DocumentPreview({
  clientId,
  document: doc,
  onOpened,
  onClose,
}: {
  clientId: string;
  document: ClientKycDocument;
  onOpened: (id: string) => void;
  onClose: () => void;
}) {
  const blobQuery = useQuery({
    queryKey: ["clients", clientId, "kyc-documents", doc.id, "inline"],
    queryFn: ({ signal }) =>
      fetchClientKycDocumentBlob({ clientId, documentId: doc.id, inline: true, signal }),
    staleTime: Infinity,
    gcTime: 0,
  });
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    // The API served (and audited) the bytes: the file counts as opened.
    if (blobQuery.data) onOpened(doc.id);
  }, [blobQuery.data, doc.id, onOpened]);
  useEffect(() => {
    if (!blobQuery.data) return undefined;
    const next = URL.createObjectURL(blobQuery.data);
    setUrl(next);
    return () => URL.revokeObjectURL(next);
  }, [blobQuery.data]);
  const isImage = (doc.content_type ?? "").startsWith("image/") ||
    /\.(png|jpe?g)$/i.test(doc.original_filename);
  return (
    <figure
      className="flex flex-col gap-2 rounded-md border border-[var(--color-line)] p-3"
      data-testid="kyc-document-preview"
      data-document-id={doc.id}
    >
      <figcaption className="flex items-center justify-between gap-2 text-xs">
        <span className="font-medium text-[var(--color-ink)] [overflow-wrap:anywhere]">
          {doc.original_filename}
        </span>
        <Button type="button" size="sm" variant="ghost" onClick={onClose}>
          Close preview
        </Button>
      </figcaption>
      {blobQuery.isError ? (
        <p className="text-xs text-[var(--color-mute)]" role="alert">
          {apiErrorMessage(blobQuery.error, "Could not open the document.")}
        </p>
      ) : !url ? (
        <Skeleton className="h-64 w-full" />
      ) : isImage ? (
        // eslint-disable-next-line @next/next/no-img-element -- a private blob URL, not an optimisable asset
        <img
          src={url}
          alt={`KYC document ${doc.original_filename}`}
          className="max-h-[32rem] w-auto max-w-full self-start rounded border border-[var(--color-line)] object-contain"
          data-testid="kyc-document-preview-image"
        />
      ) : (
        <div className="min-w-0" data-testid="kyc-document-preview-pdf">
          <PDFViewer
            url={url}
            file={blobQuery.data}
            className="max-h-[40rem] min-h-[24rem] min-w-0"
          />
        </div>
      )}
    </figure>
  );
}

export type KycUploadInput = {
  documentType: KycDocumentType;
  label: string | null;
  file: File;
};

/** Upload form shared by the client profile and the client portal. Its type
 * options, accepted extensions and size cap come from the API list response,
 * so it never offers what the upload validator refuses. */
export function KycUploadForm({
  list,
  upload: uploadFile,
  onUploaded,
}: {
  list: ClientKycDocumentList;
  upload: (input: KycUploadInput) => Promise<unknown>;
  onUploaded: () => Promise<void>;
}) {
  const formId = useId();
  const [documentType, setDocumentType] = useState<KycDocumentType>(
    (list.document_types[0]?.value ?? "pan") as KycDocumentType,
  );
  const [label, setLabel] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [inputKey, setInputKey] = useState(0);
  const option = list.document_types.find((t) => t.value === documentType);
  const accept = list.accepted_extensions.join(",");
  const tooLarge = file !== null && file.size > list.max_upload_bytes;
  const wrongType =
    file !== null &&
    !list.accepted_extensions.some((ext) => file.name.toLowerCase().endsWith(ext));
  const needsLabel = Boolean(option?.requires_label) && !label.trim();
  const blocked = !file
    ? "Choose a file."
    : wrongType
      ? `Only ${list.accepted_extensions.join(", ")} files are accepted.`
      : tooLarge
        ? `The file is larger than ${formatBytes(list.max_upload_bytes)}.`
        : needsLabel
          ? "Name the document."
          : null;
  const upload = useMutation({
    mutationFn: () =>
      uploadFile({
        documentType,
        label: option?.requires_label ? label : null,
        file: file as File,
      }),
    onSuccess: async () => {
      toast.success("Document uploaded.");
      setFile(null);
      setLabel("");
      setInputKey((k) => k + 1);
      await onUploaded();
    },
    onError: (err) => toast.error(apiErrorMessage(err, "Could not upload the document.")),
  });
  return (
    <form
      className="grid gap-3 md:grid-cols-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (!blocked) upload.mutate();
      }}
      data-testid="kyc-upload-form"
    >
      <div className="flex min-w-0 flex-col gap-1.5">
        <Label htmlFor={`${formId}-type`}>Document type</Label>
        <select
          id={`${formId}-type`}
          className="h-10 rounded-md border border-[var(--color-line)] bg-white px-3 text-sm text-[var(--color-ink)]"
          value={documentType}
          onChange={(e) => setDocumentType(e.target.value as KycDocumentType)}
          data-testid="kyc-upload-type"
        >
          {list.document_types.map((t) => (
            <option key={t.value} value={t.value}>
              {t.label}
            </option>
          ))}
        </select>
      </div>
      <div className="flex min-w-0 flex-col gap-1.5">
        <Label htmlFor={`${formId}-file`}>File (PDF, PNG or JPEG)</Label>
        <input
          key={inputKey}
          id={`${formId}-file`}
          type="file"
          accept={accept}
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          className="text-sm text-[var(--color-ink-2)] file:mr-3 file:rounded-md file:border file:border-[var(--color-line)] file:bg-white file:px-3 file:py-1.5 file:text-sm"
          data-testid="kyc-upload-file"
        />
      </div>
      {option?.requires_label ? (
        <div className="flex min-w-0 flex-col gap-1.5 md:col-span-2">
          <Label htmlFor={`${formId}-label`}>Document name</Label>
          <Input
            id={`${formId}-label`}
            value={label}
            maxLength={120}
            placeholder="Board resolution, authorisation letter…"
            onChange={(e) => setLabel(e.target.value)}
            data-testid="kyc-upload-label"
          />
        </div>
      ) : null}
      <div className="flex flex-col gap-1 text-xs md:col-span-2">
        <p className="text-[var(--color-mute)]" data-testid="kyc-upload-hint">
          {option?.hint}
        </p>
        <p className="text-[var(--color-ink-2)]" data-testid="kyc-aadhaar-notice">
          Aadhaar: upload only a masked Aadhaar (first eight digits hidden). CaseOps refuses a
          full 12-digit Aadhaar number in any field.
        </p>
      </div>
      <div className="flex flex-col items-end gap-1 md:col-span-2">
        <Button
          type="submit"
          size="sm"
          variant="outline"
          disabled={Boolean(blocked) || upload.isPending}
          aria-describedby={blocked ? `${formId}-blocked` : undefined}
          data-testid="kyc-upload-submit"
        >
          {upload.isPending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : (
            <Upload className="h-4 w-4" aria-hidden />
          )}
          Upload document
        </Button>
        {blocked && file ? (
          <p id={`${formId}-blocked`} className="text-xs text-[var(--color-mute)]" role="status">
            {blocked}
          </p>
        ) : null}
      </div>
    </form>
  );
}
