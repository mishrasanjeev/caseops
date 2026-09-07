"use client";

import { useMutation } from "@tanstack/react-query";
import { Download } from "lucide-react";

import { Button } from "@/components/ui/Button";
import { apiErrorMessage } from "@/lib/api/config";
import { downloadApiFile, fetchIpDocument } from "@/lib/api/endpoints";
import { type PatentSource } from "@/lib/api/ip-patents";

export function PatentSourceDownload({ source }: {
  source: Extract<PatentSource, { kind: "document_version" }>;
}) {
  const download = useMutation({
    mutationFn: async () => {
      const document = await fetchIpDocument(source.document_id);
      const version = document.versions.find((candidate) => candidate.id === source.document_version_id);
      if (document.id !== source.document_id || !version || version.sha256_hex !== source.content_sha256) {
        throw new Error("The pinned source version is unavailable. Reload the record.");
      }
      return downloadApiFile(
        `/api/ip/documents/${encodeURIComponent(document.id)}/versions/${version.version}/download`,
        version.display_name,
      );
    },
  });
  return <div className="mt-4">
    <Button variant="secondary" disabled={download.isPending} onClick={() => download.mutate()}>
      <Download size={16} />{download.isPending ? "Downloading..." : "Download source version"}
    </Button>
    {download.isError && <p role="alert" className="mt-2 text-sm text-danger-500">{apiErrorMessage(download.error, "Source download failed.")}</p>}
  </div>;
}
