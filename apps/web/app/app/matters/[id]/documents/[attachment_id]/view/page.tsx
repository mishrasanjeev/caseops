"use client";

// Sprint Q11 — inline PDF viewer route for a matter attachment.
//
// URL: /app/matters/{id}/documents/{attachment_id}/view
//
// Loads the PDFViewer component dynamically so react-pdf + pdfjs
// only ship to browsers that actually open a document — keeping
// every other cockpit route lean.
import dynamic from "next/dynamic";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo } from "react";

import { Button } from "@/components/ui/Button";
import { matterAttachmentDownloadUrl } from "@/lib/api/endpoints";

const PDFViewer = dynamic(
  () => import("@/components/document/PDFViewer").then((m) => m.PDFViewer),
  { ssr: false, loading: () => <p className="p-6 text-sm">Loading viewer…</p> },
);

export default function AttachmentViewerPage(): React.JSX.Element {
  const router = useRouter();
  const params = useParams<{ id: string; attachment_id: string }>();
  const matterId = params?.id ?? "";
  const attachmentId = params?.attachment_id ?? "";

  const url = useMemo(() => {
    if (!matterId || !attachmentId) return "";
    return matterAttachmentDownloadUrl({ matterId, attachmentId });
  }, [matterId, attachmentId]);

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
        <PDFViewer url={url} filename={`attachment-${attachmentId}.pdf`} className="flex-1" />
      ) : null}
    </main>
  );
}
