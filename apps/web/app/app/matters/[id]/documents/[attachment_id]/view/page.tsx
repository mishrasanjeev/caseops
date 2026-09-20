"use client";

// Sprint Q11 — inline PDF viewer route for a matter attachment.
// Sprint Q10 — annotations overlay pulled from
// `/api/matters/{id}/attachments/{aid}/annotations`.
//
// URL: /app/matters/{id}/documents/{attachment_id}/view
//
// Loads the PDFViewer component dynamically so react-pdf + pdfjs
// only ship to browsers that actually open a document — keeping
// every other cockpit route lean.
import { useQuery } from "@tanstack/react-query";
import dynamic from "next/dynamic";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo } from "react";

import type { PDFAnnotation } from "@/components/document/PDFViewer";
import { Button } from "@/components/ui/Button";
import {
  type MatterAttachmentAnnotationRecord,
  fetchMatterWorkspace,
  listMatterAttachmentAnnotations,
  matterAttachmentDownloadUrl,
} from "@/lib/api/endpoints";
import type { WorkspaceAttachment, WorkspaceResponse } from "@/lib/api/workspace-types";

const PDFViewer = dynamic(
  () => import("@/components/document/PDFViewer").then((m) => m.PDFViewer),
  { ssr: false, loading: () => <p className="p-6 text-sm">Loading viewer…</p> },
);

function recordToAnnotation(r: MatterAttachmentAnnotationRecord): PDFAnnotation {
  const bbox =
    Array.isArray(r.bbox) && r.bbox.length === 4
      ? ([r.bbox[0], r.bbox[1], r.bbox[2], r.bbox[3]] as [number, number, number, number])
      : null;
  return {
    id: r.id,
    kind: r.kind,
    page: r.page,
    bbox,
    body: r.body ?? null,
    color: r.color ?? null,
  };
}

export default function AttachmentViewerPage(): React.JSX.Element {
  const router = useRouter();
  const params = useParams<{ id: string; attachment_id: string }>();
  const matterId = params?.id ?? "";
  const attachmentId = params?.attachment_id ?? "";

  const url = useMemo(() => {
    if (!matterId || !attachmentId) return "";
    return matterAttachmentDownloadUrl({ matterId, attachmentId });
  }, [matterId, attachmentId]);

  const annotationsQuery = useQuery({
    queryKey: ["matter-attachment-annotations", matterId, attachmentId],
    queryFn: () =>
      listMatterAttachmentAnnotations({ matterId, attachmentId }),
    enabled: Boolean(matterId && attachmentId),
  });

  const annotations = useMemo(
    () => (annotationsQuery.data ?? []).map(recordToAnnotation),
    [annotationsQuery.data],
  );
  const workspaceQuery = useQuery({
    queryKey: ["matter-workspace", matterId, "attachment-viewer"],
    queryFn: () => fetchMatterWorkspace(matterId) as Promise<WorkspaceResponse>,
    enabled: Boolean(matterId),
  });
  const attachment: WorkspaceAttachment | undefined = useMemo(
    () =>
      workspaceQuery.data?.attachments.find((item) => item.id === attachmentId),
    [attachmentId, workspaceQuery.data?.attachments],
  );
  const filename =
    attachment?.original_filename ?? attachment?.filename ?? `attachment-${attachmentId}`;
  const contentType = (attachment?.content_type ?? attachment?.mime_type ?? "").toLowerCase();
  const lowerName = filename.toLowerCase();
  const isPdf = contentType.includes("pdf") || lowerName.endsWith(".pdf");
  const isImage =
    contentType.startsWith("image/") ||
    lowerName.endsWith(".png") ||
    lowerName.endsWith(".jpg") ||
    lowerName.endsWith(".jpeg");
  const isWord =
    contentType.includes("word") ||
    lowerName.endsWith(".doc") ||
    lowerName.endsWith(".docx");

  useEffect(() => {
    if (!matterId || !attachmentId) {
      router.replace("/app/matters");
    }
  }, [matterId, attachmentId, router]);

  return (
    <main className="flex h-[calc(100vh-64px)] w-full flex-col gap-3 px-6 py-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Document viewer</h1>
        <Button
          type="button"
          variant="ghost"
          onClick={() => router.push(`/app/matters/${matterId}/documents`)}
        >
          ← Back to documents
        </Button>
      </div>
      {url && isPdf ? (
        <PDFViewer
          url={url}
          filename={filename}
          className="flex-1"
          annotations={annotations}
        />
      ) : url && isImage ? (
        <div className="flex min-h-0 flex-1 items-center justify-center overflow-auto rounded-md border border-[var(--color-line)] bg-[var(--color-bg-2)] p-4">
          <img
            src={url}
            alt={filename}
            className="max-h-full max-w-full object-contain"
          />
        </div>
      ) : url && isWord ? (
        <div className="flex min-h-0 flex-1 flex-col gap-3">
          <div className="rounded-md border border-[var(--color-line)] bg-[var(--color-bg-2)] px-3 py-2 text-sm text-[var(--color-ink-2)]">
            Word files open with the browser's document handling when available. If the frame
            stays blank, use Download to open the same authenticated file locally.
          </div>
          <iframe
            title={filename}
            src={url}
            className="min-h-0 flex-1 rounded-md border border-[var(--color-line)] bg-white"
          />
          <Button type="button" variant="outline" href={url}>
            Download
          </Button>
        </div>
      ) : url ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 rounded-md border border-[var(--color-line)] bg-[var(--color-bg-2)] text-center">
          <p className="text-sm text-[var(--color-ink-2)]">
            This file type cannot be previewed inline.
          </p>
          <Button type="button" href={url}>
            Download
          </Button>
        </div>
      ) : null}
    </main>
  );
}
