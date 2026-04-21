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
  listMatterAttachmentAnnotations,
  matterAttachmentDownloadUrl,
} from "@/lib/api/endpoints";

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
      {url ? (
        <PDFViewer
          url={url}
          filename={`attachment-${attachmentId}.pdf`}
          className="flex-1"
          annotations={annotations}
        />
      ) : null}
    </main>
  );
}
