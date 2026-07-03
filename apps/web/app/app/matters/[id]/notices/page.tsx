"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Eye, FileText, Inbox, Loader2, Upload } from "lucide-react";
import { useParams } from "next/navigation";
import { useMemo, useRef, useState } from "react";
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
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { Textarea } from "@/components/ui/Textarea";
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

type NoticeUploadDraft = {
  source: string;
  subject: string;
  receivedOn: string;
  response: string;
};

const EMPTY_NOTICE_UPLOAD_DRAFT: NoticeUploadDraft = {
  source: "",
  subject: "",
  receivedOn: "",
  response: "",
};

function noticeDate(notice: WorkspaceAttachment): string | null | undefined {
  return notice.notice_received_on ?? notice.document_date ?? notice.created_at;
}

export default function MatterNoticesPage() {
  const params = useParams<{ id: string }>();
  const matterId = params.id;
  const queryClient = useQueryClient();
  const fileInput = useRef<HTMLInputElement | null>(null);
  const [noticeDraft, setNoticeDraft] = useState<NoticeUploadDraft>(EMPTY_NOTICE_UPLOAD_DRAFT);
  const canUpload = useCapability("documents:upload");
  const canManageDocuments = useCapability("documents:manage");
  const { data } = useMatterWorkspace(matterId);

  const notices = useMemo(
    () =>
      [...(data?.attachments ?? [])]
        .filter((attachment) => attachment.document_type === "notice")
        .sort((left, right) => {
          const leftDate = noticeDate(left) ?? "";
          const rightDate = noticeDate(right) ?? "";
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
        documentDate: noticeDraft.receivedOn || null,
        noticeSource: noticeDraft.source || null,
        noticeSubject: noticeDraft.subject || null,
        noticeReceivedOn: noticeDraft.receivedOn || null,
        noticeResponse: noticeDraft.response || null,
        sequenceIndex: null,
        linkedCourtOrderId: null,
        hearingId: null,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["matters", matterId, "workspace"],
      });
      toast.success("Notice uploaded.");
      setNoticeDraft(EMPTY_NOTICE_UPLOAD_DRAFT);
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
              {latestNotice ? latestNotice.notice_subject ?? displayName(latestNotice) : "None"}
            </div>
            <div className="mt-1 text-xs text-[var(--color-mute)]">
              {latestNotice
                ? formatDate(noticeDate(latestNotice))
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
          </div>
        </CardHeader>
        <CardContent>
          {canUpload ? (
            <div
              className="mb-5 rounded-lg border border-[var(--color-line)] bg-[var(--color-bg-2)] p-4"
              data-testid="matter-notice-upload-template"
            >
              <div className="grid gap-3 md:grid-cols-3">
                <div>
                  <Label htmlFor="notice-source">Notice source</Label>
                  <Input
                    id="notice-source"
                    className="mt-1.5"
                    value={noticeDraft.source}
                    onChange={(event) =>
                      setNoticeDraft((current) => ({
                        ...current,
                        source: event.target.value,
                      }))
                    }
                    data-testid="matter-notice-source"
                  />
                </div>
                <div className="md:col-span-2">
                  <Label htmlFor="notice-subject">Notice subject / about</Label>
                  <Input
                    id="notice-subject"
                    className="mt-1.5"
                    value={noticeDraft.subject}
                    onChange={(event) =>
                      setNoticeDraft((current) => ({
                        ...current,
                        subject: event.target.value,
                      }))
                    }
                    data-testid="matter-notice-subject"
                  />
                </div>
                <div>
                  <Label htmlFor="notice-received-on">Date received</Label>
                  <Input
                    id="notice-received-on"
                    className="mt-1.5"
                    type="date"
                    value={noticeDraft.receivedOn}
                    onChange={(event) =>
                      setNoticeDraft((current) => ({
                        ...current,
                        receivedOn: event.target.value,
                      }))
                    }
                    data-testid="matter-notice-received-on"
                  />
                </div>
                <div className="md:col-span-2">
                  <Label htmlFor="notice-response">Reply / response to notice</Label>
                  <Textarea
                    id="notice-response"
                    className="mt-1.5 min-h-20"
                    value={noticeDraft.response}
                    onChange={(event) =>
                      setNoticeDraft((current) => ({
                        ...current,
                        response: event.target.value,
                      }))
                    }
                    data-testid="matter-notice-response"
                  />
                </div>
              </div>
              <div className="mt-3 flex justify-end">
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
              </div>
            </div>
          ) : null}
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
                          {notice.notice_subject ?? displayName(notice)}
                        </h2>
                        <StatusBadge status={notice.processing_status ?? "unknown"} />
                        {notice.notice_source ? (
                          <Badge tone="brand">{notice.notice_source}</Badge>
                        ) : null}
                        {notice.lifecycle_stage ? (
                          <Badge tone="neutral">
                            {notice.lifecycle_stage.replace(/_/g, " ")}
                          </Badge>
                        ) : null}
                      </div>
                      {notice.notice_subject ? (
                        <div className="mt-1 truncate text-xs text-[var(--color-mute)]">
                          {displayName(notice)}
                        </div>
                      ) : null}
                      <div className="mt-1 flex flex-wrap gap-2 text-xs text-[var(--color-mute)]">
                        <span>Received {formatDate(noticeDate(notice))}</span>
                        <span>{humanSize(notice.size_bytes)}</span>
                        <span>{notice.mime_type ?? notice.content_type ?? "file"}</span>
                        {notice.sequence_index !== null &&
                        notice.sequence_index !== undefined ? (
                          <span>Seq {notice.sequence_index}</span>
                        ) : null}
                      </div>
                      {notice.notice_response ? (
                        <p className="mt-2 line-clamp-2 text-xs leading-5 text-[var(--color-ink-2)]">
                          {notice.notice_response}
                        </p>
                      ) : null}
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
