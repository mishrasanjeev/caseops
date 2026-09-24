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
import { useEffect, useMemo, useState } from "react";

import type { PDFAnnotation } from "@/components/document/PDFViewer";
import { Button } from "@/components/ui/Button";
import {
  type MatterAttachmentAnnotationRecord,
  fetchMatterAttachmentBlob,
  fetchMatterAttachmentPreview,
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
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const matterId = params?.id ?? "";
  const attachmentId = params?.attachment_id ?? "";

  const url = useMemo(() => {
    if (!matterId || !attachmentId) return "";
    return matterAttachmentDownloadUrl({ matterId, attachmentId });
  }, [matterId, attachmentId]);
  const inlineUrl = useMemo(() => {
    if (!matterId || !attachmentId) return "";
    return matterAttachmentDownloadUrl({ matterId, attachmentId, inline: true });
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
  const imageQuery = useQuery({
    queryKey: ["matter-attachment-image", matterId, attachmentId],
    queryFn: ({ signal }) =>
      fetchMatterAttachmentBlob({ matterId, attachmentId, inline: true, signal }),
    enabled: Boolean(matterId && attachmentId && isImage),
  });
  useEffect(() => {
    if (!imageQuery.data) {
      setImageUrl(null);
      return;
    }
    const objectUrl = URL.createObjectURL(imageQuery.data);
    setImageUrl(objectUrl);
    return () => URL.revokeObjectURL(objectUrl);
  }, [imageQuery.data]);
  const isWord =
    contentType.includes("word") ||
    lowerName.endsWith(".doc") ||
    lowerName.endsWith(".docx");
  const previewQuery = useQuery({
    queryKey: ["matter-attachment-preview", matterId, attachmentId],
    queryFn: () => fetchMatterAttachmentPreview({ matterId, attachmentId }),
    enabled: Boolean(matterId && attachmentId && isWord),
  });

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
          url={inlineUrl}
          filename={filename}
          className="flex-1"
          annotations={annotations}
        />
      ) : url && isImage ? (
        <div className="flex min-h-0 flex-1 items-center justify-center overflow-auto rounded-md border border-[var(--color-line)] bg-[var(--color-bg-2)] p-4">
          {imageUrl ? (
            <img src={imageUrl} alt={filename} className="max-h-full max-w-full object-contain" />
          ) : imageQuery.isError ? (
            <p className="text-sm text-[var(--color-danger)]">This image could not be previewed. Download the authenticated file to continue.</p>
          ) : (
            <p className="text-sm text-[var(--color-ink-2)]">Loading image…</p>
          )}
        </div>
      ) : url && isWord ? (
        <div className="flex min-h-0 flex-1 flex-col gap-3">
          <div className="min-h-0 flex-1 overflow-auto rounded-md border border-[var(--color-line)] bg-white p-5">
            {previewQuery.isPending ? (
              <p className="text-sm text-[var(--color-ink-2)]">Rendering document…</p>
            ) : previewQuery.isError ? (
              <p className="text-sm text-[var(--color-danger)]">
                This DOCX could not be previewed. Download the authenticated file to continue.
              </p>
            ) : (
              <article className="mx-auto max-w-4xl space-y-3 text-sm leading-6 text-[var(--color-ink)]">
                {previewQuery.data?.paragraphs.map((paragraph, index) => (
                  <p key={`${index}-${paragraph.slice(0, 16)}`}>{paragraph}</p>
                ))}
                {previewQuery.data?.table_rows.length ? (
                  <div className="overflow-x-auto">
                    <table className="min-w-full border-collapse border border-[var(--color-line)]">
                      <tbody>
                        {previewQuery.data.table_rows.map((row, rowIndex) => (
                          <tr key={`row-${rowIndex}`}>
                            {row.map((cell, cellIndex) => (
                              <td
                                key={`cell-${rowIndex}-${cellIndex}`}
                                className="border border-[var(--color-line)] px-3 py-2 align-top"
                              >
                                {cell}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : null}
                {!previewQuery.data?.paragraphs.length && !previewQuery.data?.table_rows.length ? (
                  <p className="text-[var(--color-ink-2)]">This document has no previewable text.</p>
                ) : null}
              </article>
            )}
          </div>
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
