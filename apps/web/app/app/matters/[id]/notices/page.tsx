"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Eye, FileText, Inbox, Loader2, Upload } from "lucide-react";
import { useParams } from "next/navigation";
import { useMemo, useRef } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { apiErrorMessage } from "@/lib/api/config";
import { uploadMatterAttachment } from "@/lib/api/endpoints";
import type { WorkspaceAttachment } from "@/lib/api/workspace-types";
import { useCapability } from "@/lib/capabilities";
import { formatLegalDate } from "@/lib/dates";
import { useMatterWorkspace } from "@/lib/use-matter-workspace";

function displayName(doc: WorkspaceAttachment): string {
  return doc.original_filename ?? doc.filename ?? "Notice document";
}

function formatDate(value: string | null | undefined): string {
  return formatLegalDate(value, {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

function humanSize(bytes: number | null | undefined): string {
  if (!bytes || bytes <= 0) return "-";
  const units = ["B", "KB", "MB", "GB"];
  let index = 0;
  let size = bytes;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  return `${size.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

export default function MatterNoticesPage() {
  const params = useParams<{ id: string }>();
  const matterId = params.id;
  const queryClient = useQueryClient();
  const fileInput = useRef<HTMLInputElement | null>(null);
  const canUpload = useCapability("documents:upload");
  const canManageDocuments = useCapability("documents:manage");
  const { data } = useMatterWorkspace(matterId);

  const notices = useMemo(
    () =>
      [...(data?.attachments ?? [])]
        .filter((attachment) => attachment.document_type === "notice")
        .sort((left, right) => {
          const leftDate = left.document_date ?? left.created_at;
          const rightDate = right.document_date ?? right.created_at;
          return rightDate.localeCompare(leftDate);
        }),
    [data?.attachments],
  );
  const latestNotice = notices[0] ?? null;
  const pendingCount = notices.filter((notice) =>
    ["pending", "needs_ocr", "failed"].includes(notice.processing_status ?? ""),
  ).length;

  const uploadMutation = useMutation({
    mutationFn: (file: File) =>
      uploadMatterAttachment({
        matterId,
        file,
        documentType: "notice",
        lifecycleStage: "initiation",
        documentDate: null,
        sequenceIndex: null,
        linkedCourtOrderId: null,
        hearingId: null,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["matters", matterId, "workspace"],
      });
      toast.success("Notice uploaded.");
    },
    onError: (err) => {
      toast.error(apiErrorMessage(err, "Could not upload the notice."));
    },
    onSettled: () => {
      if (fileInput.current) fileInput.current.value = "";
    },
  });

  if (!data) return null;

  return (
    <div className="flex flex-col gap-5" data-testid="matter-notices-page">
      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle>Total notices</CardTitle>
            <CardDescription>Marked notice documents on this matter.</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-semibold text-[var(--color-ink)]">
              {notices.length}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Latest notice</CardTitle>
            <CardDescription>Newest notice by document or upload date.</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="text-sm font-medium text-[var(--color-ink)]">
              {latestNotice ? displayName(latestNotice) : "None"}
            </div>
            <div className="mt-1 text-xs text-[var(--color-mute)]">
              {latestNotice
                ? formatDate(latestNotice.document_date ?? latestNotice.created_at)
                : "Upload or classify a notice to start."}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Processing attention</CardTitle>
            <CardDescription>Notices pending indexing or OCR review.</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-semibold text-[var(--color-ink)]">
              {pendingCount}
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <CardTitle as="h1">Notices</CardTitle>
            <CardDescription>
              Demand notices, legal notices, and notice correspondence linked to this matter.
            </CardDescription>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button href={`/app/matters/${matterId}/documents`} variant="outline">
              <FileText className="h-4 w-4" aria-hidden />
              Documents
            </Button>
            {canUpload ? (
              <>
                <input
                  ref={fileInput}
                  type="file"
                  className="hidden"
                  data-testid="matter-notice-file-input"
                  onChange={(event) => {
                    const file = event.target.files?.[0];
                    if (file) uploadMutation.mutate(file);
                  }}
                />
                <Button
                  type="button"
                  disabled={uploadMutation.isPending}
                  onClick={() => fileInput.current?.click()}
                  data-testid="matter-notice-upload"
                >
                  {uploadMutation.isPending ? (
                    <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                  ) : (
                    <Upload className="h-4 w-4" aria-hidden />
                  )}
                  Upload notice
                </Button>
              </>
            ) : null}
          </div>
        </CardHeader>
        <CardContent>
          {notices.length === 0 ? (
            <EmptyState
              icon={Inbox}
              title="No notices on file"
              description={
                canUpload
                  ? "Upload a notice here, or classify an existing document as Notice from the Documents tab."
                  : "Classified notice documents will appear here when available."
              }
            />
          ) : (
            <ul className="divide-y divide-[var(--color-line)] rounded-lg border border-[var(--color-line)] bg-white">
              {notices.map((notice) => {
                const viewHref = `/app/matters/${matterId}/documents/${notice.id}/view`;
                return (
                  <li
                    key={notice.id}
                    className="flex flex-col gap-3 px-4 py-3 md:flex-row md:items-center md:justify-between"
                    data-testid="matter-notice-row"
                  >
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <h2 className="truncate text-sm font-semibold text-[var(--color-ink)]">
                          {displayName(notice)}
                        </h2>
                        <StatusBadge status={notice.processing_status ?? "unknown"} />
                        {notice.lifecycle_stage ? (
                          <Badge tone="neutral">
                            {notice.lifecycle_stage.replace(/_/g, " ")}
                          </Badge>
                        ) : null}
                      </div>
                      <div className="mt-1 flex flex-wrap gap-2 text-xs text-[var(--color-mute)]">
                        <span>{formatDate(notice.document_date ?? notice.created_at)}</span>
                        <span>{humanSize(notice.size_bytes)}</span>
                        <span>{notice.mime_type ?? notice.content_type ?? "file"}</span>
                        {notice.sequence_index !== null &&
                        notice.sequence_index !== undefined ? (
                          <span>Seq {notice.sequence_index}</span>
                        ) : null}
                      </div>
                    </div>
                    <div className="flex shrink-0 flex-wrap gap-2">
                      <Button href={viewHref} variant="outline" size="sm">
                        <Eye className="h-4 w-4" aria-hidden />
                        View
                      </Button>
                      {canManageDocuments ? (
                        <Button
                          href={`/app/matters/${matterId}/documents`}
                          variant="ghost"
                          size="sm"
                        >
                          Manage metadata
                        </Button>
                      ) : null}
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
