"use client";

import { File, FileText } from "lucide-react";
import { useParams } from "next/navigation";

import { Card, CardContent } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { StatusBadge } from "@/components/ui/StatusBadge";
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

export default function MatterDocumentsPage() {
  const params = useParams<{ id: string }>();
  const { data } = useMatterWorkspace(params.id);
  if (!data) return null;
  const attachments = data.attachments;

  if (attachments.length === 0) {
    return (
      <EmptyState
        icon={FileText}
        title="No documents attached yet"
        description="Upload pleadings, orders, and correspondence from the legacy console for now — the upload surface for the new cockpit is part of the documents workstream (§9.1)."
      />
    );
  }

  return (
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
            </tr>
          </thead>
          <tbody>
            {attachments.map((doc) => (
              <tr
                key={doc.id}
                className="border-b border-[var(--color-line-2)] last:border-0"
              >
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <File className="h-4 w-4 text-[var(--color-mute)]" aria-hidden />
                    <span className="font-medium text-[var(--color-ink)]">
                      {doc.original_filename ?? doc.filename ?? "Untitled"}
                    </span>
                  </div>
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
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}
