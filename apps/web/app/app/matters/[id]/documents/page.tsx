"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Eye, File, FileText, Loader2, RefreshCw, Upload } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/Button";
import { Card, CardContent } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { apiErrorMessage } from "@/lib/api/config";
import {
  reindexMatterAttachment,
  retryMatterAttachment,
  uploadMatterAttachment,
} from "@/lib/api/endpoints";
import { useCapability } from "@/lib/capabilities";
import { useMatterWorkspace } from "@/lib/use-matter-workspace";

function humanSize(bytes: number | null | undefined): string {
  if (!bytes || bytes <= 0) return "—";
  const units = ["B", "KB", "MB", "GB"];
  let i = 0;
  let size = bytes;
  while (size >= 1024 && i < units.length - 1) {
    size /= 1024;
    i += 1;
  }
  return `${size.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

const RETRY_STATUSES = new Set(["failed", "needs_ocr", "pending"]);
const REINDEX_STATUSES = new Set(["indexed"]);

export default function MatterDocumentsPage() {
  const params = useParams<{ id: string }>();
  const matterId = params.id;
  const queryClient = useQueryClient();
  const { data } = useMatterWorkspace(matterId);
  const canUpload = useCapability("documents:upload");
  const canManage = useCapability("documents:manage");
  const fileInput = useRef<HTMLInputElement | null>(null);
  const [pendingId, setPendingId] = useState<string | null>(null);

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ["matters", matterId, "workspace"] });

  const uploadMutation = useMutation({
    mutationFn: (file: File) => uploadMatterAttachment({ matterId, file }),
    onSuccess: async () => {
      await invalidate();
      toast.success("Document uploaded — processing will begin shortly.");
    },
    onError: (err) => {
      toast.error(
        apiErrorMessage(err, "Could not upload the document."),
      );
    },
    onSettled: () => {
      if (fileInput.current) fileInput.current.value = "";
    },
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
      toast.error(
        apiErrorMessage(err, "Could not retry processing."),
      );
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
      toast.error(
        apiErrorMessage(err, "Could not reindex the document."),
      );
    },
    onSettled: () => setPendingId(null),
  });

  if (!data) return null;
  const attachments = data.attachments;

  function handleFileChange(event: React.ChangeEvent<HTMLInputElement>) {
    const selected = event.target.files?.[0];
    if (selected) uploadMutation.mutate(selected);
  }

  const uploader = canUpload ? (
    <div className="flex items-center justify-between gap-3 rounded-lg border border-[var(--color-line)] bg-[var(--color-bg-2)] p-4">
      <div>
        <p className="text-sm font-medium text-[var(--color-ink)]">Upload a document</p>
        <p className="text-xs text-[var(--color-mute)]">
          PDF, DOCX, TXT — processed and indexed for search, citations, and drafting.
        </p>
      </div>
      <div>
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
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Uploading…
            </>
          ) : (
            <>
              <Upload className="h-4 w-4" aria-hidden /> Upload
            </>
          )}
        </Button>
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
      <Card>
        <CardContent className="p-0">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--color-line)] bg-[var(--color-bg)] text-xs uppercase tracking-[0.06em] text-[var(--color-mute)]">
                <th className="px-4 py-2.5 text-left font-semibold">File</th>
                <th className="px-4 py-2.5 text-left font-semibold">Type</th>
                <th className="px-4 py-2.5 text-left font-semibold">Size</th>
                <th className="px-4 py-2.5 text-left font-semibold">Processing</th>
                <th className="px-4 py-2.5 text-left font-semibold">Added</th>
                <th className="px-4 py-2.5 text-right font-semibold">Actions</th>
              </tr>
            </thead>
            <tbody>
              {attachments.map((doc) => {
                const status = (doc.processing_status ?? "unknown").toLowerCase();
                const isPending = pendingId === doc.id;
                const canRetry = canManage && RETRY_STATUSES.has(status);
                const canReindex = canManage && REINDEX_STATUSES.has(status);
                // BUG-024 (Hari 2026-04-23): every uploaded attachment
                // must be openable. The view route + the
                // /attachments/{id}/download endpoint already exist;
                // the only gap was a UI affordance to reach them.
                const viewHref = `/app/matters/${matterId}/documents/${doc.id}/view`;
                return (
                  <tr
                    key={doc.id}
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
                    </td>
                    <td className="px-4 py-3 text-xs text-[var(--color-mute)]">
                      {doc.mime_type ?? "—"}
                    </td>
                    <td className="px-4 py-3 text-xs text-[var(--color-mute)]">
                      {humanSize(doc.size_bytes)}
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={doc.processing_status ?? "unknown"} />
                    </td>
                    <td className="px-4 py-3 text-xs text-[var(--color-mute)]">
                      {new Date(doc.created_at).toLocaleDateString(undefined, {
                        day: "2-digit",
                        month: "short",
                        year: "numeric",
                      })}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div className="inline-flex gap-2">
                        <Button
                          variant="ghost"
                          size="sm"
                          href={viewHref}
                          data-testid={`matter-attachment-view-${doc.id}`}
                        >
                          <Eye className="h-4 w-4" aria-hidden />
                          View
                        </Button>
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
                );
              })}
            </tbody>
          </table>
        </CardContent>
      </Card>
    </div>
  );
}
