"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowLeft, Download } from "lucide-react";
import dynamic from "next/dynamic";
import { useParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/Button";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { fetchContractAttachmentBlob, type ContractAttachmentSource } from "@/lib/api/contracts";
import { fetchContractWorkspace } from "@/lib/api/endpoints";
import { ApiError, apiErrorMessage } from "@/lib/api/config";

const PDFViewer = dynamic(() => import("@/components/document/PDFViewer").then((m) => m.PDFViewer), { ssr: false });
const DocxViewer = dynamic(() => import("@/components/document/DocxViewer").then((m) => m.DocxViewer), { ssr: false });
type Attachment = ContractAttachmentSource & { id: string; processing_status: string };

export default function ContractAttachmentViewerPage() {
  const { id: contractId, attachment_id: attachmentId } = useParams<{ id: string; attachment_id: string }>();
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  const [revoked, setRevoked] = useState(false);
  const downloadAbort = useRef<AbortController | null>(null);
  useEffect(() => () => downloadAbort.current?.abort(), []);
  const download = useMutation({
    mutationFn: async () => {
      if (!attachment) return;
      const controller = new AbortController();
      downloadAbort.current = controller;
      const blob = await fetchContractAttachmentBlob(contractId, attachmentId, attachment, controller.signal);
      controller.signal.throwIfAborted();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a"); link.href = url; link.download = name; link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    },
    onError: (error) => { if (error instanceof ApiError && [401, 403, 404].includes(error.status)) setRevoked(true); },
  });
  const workspace = useQuery({
    queryKey: ["contracts", contractId, "viewer", attachmentId],
    queryFn: async () => await fetchContractWorkspace(contractId) as { attachments: Attachment[] },
    gcTime: 0,
  });
  const attachment = workspace.data?.attachments.find((a) => a.id === attachmentId);
  const name = attachment?.original_filename ?? "";
  const isDocx = name.toLowerCase().endsWith(".docx");
  const isPdf = name.toLowerCase().endsWith(".pdf");
  const file = useQuery({
    queryKey: ["contracts", contractId, "viewer-bytes", attachmentId],
    queryFn: async ({ signal }) => {
      return fetchContractAttachmentBlob(contractId, attachmentId, attachment!, signal, true);
    },
    enabled: workspace.isSuccess && Boolean(attachment),
    retry: false,
    gcTime: 0,
  });
  useEffect(() => {
    if (!file.data || file.isError || revoked || workspace.isError) { setObjectUrl(null); return; }
    const url = URL.createObjectURL(file.data);
    setObjectUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file.data, file.isError, revoked, workspace.isError]);

  return <main className="flex h-[calc(100dvh-9rem)] min-h-96 min-w-0 flex-col gap-3">
    <header className="flex min-w-0 flex-wrap items-center justify-between gap-3">
      <h1 className="min-w-0 break-words text-lg font-semibold">{name || "Contract document"}</h1>
      <Button size="sm" variant="ghost" href={`/app/contracts/${contractId}`}><ArrowLeft className="h-4 w-4" aria-hidden />Back to contract</Button>
    </header>
    {workspace.isError ? <QueryErrorState title="Could not load this document" error={workspace.error} onRetry={workspace.refetch} />
      : workspace.isPending ? <p role="status">Loading document...</p>
      : !attachment ? <p role="alert">This document is unavailable.</p>
      : <>
        <div className="flex min-w-0 flex-wrap items-center gap-3 text-xs text-[var(--color-mute)]">
          <span className="min-w-0 max-w-full break-all">{attachment.content_type}</span><span>{Math.ceil(attachment.size_bytes / 1024)} KB</span><span>{attachment.processing_status}</span>
          <Button size="sm" variant="outline" disabled={download.isPending || revoked} onClick={() => download.mutate()}><Download className="h-4 w-4" aria-hidden />Download original</Button>
        </div>
        {download.isError ? <p role="alert">{apiErrorMessage(download.error, "Could not download this document.")}</p> : null}
        {revoked ? <p role="alert">Document access is no longer available.</p>
          : file.isError ? <QueryErrorState title="Could not preview this document" error={file.error} onRetry={file.refetch} />
          : !file.data || !objectUrl ? <p role="status">Preparing document...</p>
          : isPdf ? <PDFViewer key={attachmentId} url={objectUrl} className="min-h-0 min-w-0 flex-1" />
          : isDocx ? <DocxViewer key={attachmentId} blob={file.data} filename={name} />
          : <p>This file type cannot be previewed inline.</p>}
      </>}
  </main>;
}
